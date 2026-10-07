"""Bounded simulated glitch effects, a temporary CPU cap and cancellable shutdown."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid
from device_controls import Journal
from remote_terminal import CommandJob
from win_support import HIDDEN,atomic_json,cpu_state,powershell,ps_config

SECONDS=20
PREVIEW_SECONDS=12

def task_name(data):return 'HomeControl-TweakoutRecovery-'+hashlib.sha256(str(Path(data).resolve()).lower().encode()).hexdigest()[:12]

def register_recovery(data,deadline):
    exe=Path(sys.executable).with_name('pythonw.exe')
    if not exe.exists():exe=Path(sys.executable)
    cfg={'name':task_name(data),'exe':str(exe),'script':str(Path(__file__).resolve()),'data':str(Path(data).resolve()),'delay':max(1,deadline-time.time())}
    powershell(ps_config(cfg)+r'''
    $account=[Security.Principal.WindowsIdentity]::GetCurrent().Name
    $args='"'+$cfg.script+'" --recover --data "'+$cfg.data+'"'
    $action=New-ScheduledTaskAction -Execute $cfg.exe -Argument $args
    $once=New-ScheduledTaskTrigger -Once -At (Get-Date).AddSeconds($cfg.delay) -RepetitionInterval (New-TimeSpan -Minutes 1)
    $logon=New-ScheduledTaskTrigger -AtLogOn -User $account
    $principal=New-ScheduledTaskPrincipal -UserId $account -LogonType Interactive -RunLevel Highest
    $settings=New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 2)
    Register-ScheduledTask -TaskName $cfg.name -Action $action -Trigger @($once,$logon) -Principal $principal -Settings $settings -Description 'Restore temporary HomeControl Tweakout CPU settings after expiry or sign-in.' -Force | Out-Null
    $verify=Get-ScheduledTask -TaskName $cfg.name
    if($verify.Principal.RunLevel -ne 'Highest' -or $verify.State -eq 'Disabled'){throw 'CPU recovery task was not armed'}
    ''',timeout=8)

def remove_recovery(data):
    powershell(ps_config({'name':task_name(data)})+"$task=Get-ScheduledTask -TaskName $cfg.name -ErrorAction SilentlyContinue; if($task){Unregister-ScheduledTask -TaskName $cfg.name -Confirm:$false}; Write-Output 'Recovery task cleared'",timeout=8)

def power_command(*args):
    result=subprocess.run(['powercfg.exe',*args],capture_output=True,timeout=5,creationflags=HIDDEN)
    if result.returncode:raise RuntimeError('Windows rejected the temporary CPU setting.')

class CpuRecovery:
    def __init__(self,data,read=cpu_state,command=power_command,register=register_recovery,clock=time.time):
        self.data=Path(data);self.file=self.data/'tweakout-cpu.json';self.read=read;self.command=command;self.register=register;self.clock=clock
        self.mutex=Journal(self.data);self.mutex.name='Global\\'+task_name(self.data)
    def apply(self):
        with self.mutex.locked():
            if self.file.exists():raise RuntimeError('Temporary CPU recovery is pending. Cancel Tweakout to retry recovery.')
            scheme,values=self.read()
            saved={'scheme':scheme,'values':values,'deadline':self.clock()+60}
            atomic_json(self.file,saved)
            # Durable record and a verified independent task precede the first CPU write.
            self.register(self.data,saved['deadline'])
            for flag in ('/setacvalueindex','/setdcvalueindex'):self.command(flag,scheme,'SUB_PROCESSOR','PROCTHROTTLEMAX','1')
            self.command('/setactive',scheme)
    def restore(self,force=False):
        with self.mutex.locked():
            if not self.file.exists():return
            saved=json.loads(self.file.read_text(encoding='utf-8'))
            scheme=str(uuid.UUID(saved['scheme']));values=saved['values']
            if not isinstance(values,list) or len(values)!=2 or any(type(v) is not int or not 0<=v<=100 for v in values):raise ValueError('Invalid temporary CPU recovery record')
            if not force and self.clock()<saved['deadline']:return
            for flag,value in zip(('/setacvalueindex','/setdcvalueindex'),values):self.command(flag,scheme,'SUB_PROCESSOR','PROCTHROTTLEMAX',str(value))
            self.command('/setactive',scheme)
            self.file.unlink()

class Effects:
    def __init__(self,root,data):
        self.root=Path(root);self.data=Path(data);self.process=None;self.job=None
        self.control=self.data/'tweakout-control.json';self.result=self.data/'tweakout-result.json';self.mode_id=None
    def launch(self,preview):
        self.mode_id=uuid.uuid4().hex;self.result.unlink(missing_ok=True)
        atomic_json(self.control,{'id':self.mode_id,'deadline':time.time()+60,'preview':preview})
        self.job=CommandJob()
        try:
            self.process=subprocess.Popen([sys.executable,str(self.root/'tweakout_worker.py'),'--data',str(self.data)],
                stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=HIDDEN)
            self.job.add(self.process.pid)
            end=time.monotonic()+6
            while time.monotonic()<end:
                if self.process.poll() is not None:raise RuntimeError('The effects window could not start. Install Python with Tcl/Tk support.')
                result=self.reading()
                if result.get('ready'):return
                time.sleep(.05)
            raise RuntimeError('The effects window did not become ready.')
        except Exception:self.close();raise
    def reading(self):
        try:
            value=json.loads(self.result.read_text(encoding='utf-8'))
            return value if value.get('id')==self.mode_id else {}
        except (OSError,ValueError):return {}
    def begin(self,preview,seconds):
        atomic_json(self.control,{'id':self.mode_id,'deadline':time.time()+seconds,'preview':preview,'started':True})
    def healthy(self):
        value=self.reading()
        return bool(self.process and self.process.poll() is None and value.get('ready') and time.time()-value.get('heartbeat',0)<5)
    def stale(self):return time.time()-self.reading().get('heartbeat',0)>=5
    def close(self):
        if self.job:self.job.close();self.job=None
        if self.process:
            try:self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait(timeout=3)
            self.process=None
        for path in (self.control,self.result,self.data/'tweakout-audio.wav'):path.unlink(missing_ok=True)

class Tweakout:
    def __init__(self,root,data,shutdown,power_pending=lambda:False,cpu=None,effects=None,clock=time.monotonic):
        self.cpu=cpu or CpuRecovery(data);self.effects=effects or Effects(root,data)
        self.shutdown=shutdown;self.power_pending=power_pending;self.clock=clock
        self.lock=threading.RLock();self.active=None;self.state='idle';self.error='';self.audio_error=''
    def blocked(self):
        with self.lock:return self.active is not None or self.cpu.file.exists()
    def status(self):
        with self.lock:return {'active':self.active is not None,'preview':self.active['preview'] if self.active else False,
            'seconds':max(0,round(self.active['end']-self.clock(),1)) if self.active else 0,
            'state':self.state,'error':self.error,'audioError':self.audio_error,'recoveryPending':self.cpu.file.exists()}
    def start(self,preview=False,confirmed=False):
        if type(preview) is not bool or type(confirmed) is not bool:raise ValueError('Preview and confirmation must be true or false.')
        if not preview and not confirmed:raise ValueError('Confirm the 20-second shutdown sequence on the dashboard.')
        with self.lock:
            if self.blocked():raise RuntimeError('Cancel the active Tweakout sequence or recover its CPU settings first.')
            if self.power_pending():raise RuntimeError('Cancel the pending power action first.')
            self.error='';self.audio_error='';self.state='starting'
            try:
                self.effects.launch(preview)
                if not preview:self.cpu.apply()
                duration=PREVIEW_SECONDS if preview else SECONDS
                self.effects.begin(preview,duration)
                self.active={'preview':preview,'end':self.clock()+duration};self.state='preview' if preview else 'running'
                self.audio_error=self.effects.reading().get('audioError','')
            except Exception as exc:
                self._finish('failed',str(exc));raise RuntimeError(self.error) from None
            return self.status()
    def _finish(self,state,error=''):
        self.active=None;self.state=state;self.error=error
        try:self.effects.close()
        except Exception as exc:self.error+=' Effects cleanup: '+str(exc)
        try:self.cpu.restore(force=True)
        except Exception as exc:self.state='recovery_needed';self.error+=' CPU recovery: '+str(exc)
    def cancel(self):
        with self.lock:self._finish('cancelled');return self.status()
    def tick(self):
        with self.lock:
            if not self.active:return
            if self.effects.stale():
                self._finish('failed','The effects worker stalled or the laptop resumed after a delay. Shutdown was cancelled.');return
            if self.clock()>=self.active['end']:
                preview=self.active['preview'];self._finish('preview_finished' if preview else 'shutdown_requested')
                if not preview and not self.cpu.file.exists() and not self.error:
                    try:self.shutdown()
                    except Exception as exc:self.state='failed';self.error=str(exc)
            elif not self.effects.healthy():self._finish('failed','The effects worker stopped or stalled. Shutdown was cancelled.')
    def reconcile(self):
        with self.lock:
            if not self.active:
                try:self.cpu.restore(force=True)
                except Exception as exc:self.state='recovery_needed';self.error=str(exc)
    def close(self):
        with self.lock:self._finish('cancelled' if self.active else self.state)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--recover',action='store_true');parser.add_argument('--data',type=Path,required=True)
    args=parser.parse_args()
    if args.recover:
        try:
            cpu=CpuRecovery(args.data);cpu.restore()
            if not cpu.file.exists():remove_recovery(args.data)
        except Exception as exc:
            with (args.data/'tweakout-recovery.log').open('a',encoding='utf-8') as log:log.write(str(exc)+'\n')
