"""Selected PnP devices only, with a journal and an independent recovery task."""
import argparse
from contextlib import contextmanager
import ctypes as C
from ctypes import wintypes as W
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
from win_support import atomic_json, powershell, ps_config, HIDDEN, GUID

INSTANCE = re.compile(r'[A-Za-z0-9\\&_.{}#:+\-]{1,512}\Z')
STORAGE_CLASSES = {'diskdrive','volume','scsiadapter','storage','hdc'}

def network_connections():
    """A missing/failed reading never grants permission to stop a network ancestor."""
    try:
        items=json.loads(powershell("@(Get-NetAdapter -IncludeHidden -ErrorAction Stop | Select-Object PnPDeviceID,Status) | ConvertTo-Json -Compress"))
        if isinstance(items,dict): items=[items]
        return {r['PnPDeviceID'].upper():str(r.get('Status')) not in ('Disconnected','Disabled','Not Present','LowerLayerDown') for r in items or [] if r.get('PnPDeviceID')}
    except Exception: return {}

def raw_inventory():
    # Native enumeration avoids invoking a slow CIM query for every device.
    class Info(C.Structure):
        _fields_=[('size',W.DWORD),('guid',GUID),('instance',W.DWORD),('reserved',C.c_size_t)]
    setup=C.WinDLL('setupapi',use_last_error=True); cfg=C.WinDLL('cfgmgr32')
    setup.SetupDiGetClassDevsW.argtypes=[C.c_void_p,W.LPCWSTR,W.HWND,W.DWORD]; setup.SetupDiGetClassDevsW.restype=W.HANDLE
    setup.SetupDiEnumDeviceInfo.argtypes=[W.HANDLE,W.DWORD,C.POINTER(Info)]
    setup.SetupDiGetDeviceInstanceIdW.argtypes=[W.HANDLE,C.POINTER(Info),W.LPWSTR,W.DWORD,C.c_void_p]
    setup.SetupDiGetDeviceRegistryPropertyW.argtypes=[W.HANDLE,C.POINTER(Info),W.DWORD,C.c_void_p,C.c_void_p,W.DWORD,C.c_void_p]
    setup.SetupDiDestroyDeviceInfoList.argtypes=[W.HANDLE]
    cfg.CM_Get_Parent.argtypes=[C.POINTER(W.DWORD),W.DWORD,W.DWORD]
    cfg.CM_Get_Device_IDW.argtypes=[W.DWORD,W.LPWSTR,W.ULONG,W.ULONG]
    cfg.CM_Get_DevNode_Status.argtypes=[C.POINTER(W.ULONG),C.POINTER(W.ULONG),W.DWORD,W.ULONG]
    handle=setup.SetupDiGetClassDevsW(None,None,None,6)
    if handle==C.c_void_p(-1).value: raise C.WinError(C.get_last_error())
    rows=[]
    try:
        for index in range(8192):
            info=Info(); info.size=C.sizeof(info)
            if not setup.SetupDiEnumDeviceInfo(handle,index,C.byref(info)):
                if C.get_last_error()==259: break
                raise C.WinError(C.get_last_error())
            uid=C.create_unicode_buffer(512)
            if not setup.SetupDiGetDeviceInstanceIdW(handle,C.byref(info),uid,len(uid),None): continue
            def prop(code):
                buf=C.create_unicode_buffer(2048)
                return buf.value if setup.SetupDiGetDeviceRegistryPropertyW(handle,C.byref(info),code,None,buf,C.sizeof(buf),None) else ''
            parent=W.DWORD(); parent_id=C.create_unicode_buffer(512)
            if cfg.CM_Get_Parent(C.byref(parent),info.instance,0)==0: cfg.CM_Get_Device_IDW(parent,parent_id,len(parent_id),0)
            status=W.ULONG(); problem=W.ULONG()
            ok=cfg.CM_Get_DevNode_Status(C.byref(status),C.byref(problem),info.instance,0)==0
            rows.append({'id':uid.value,'name':prop(12) or prop(0) or uid.value,'class':prop(7),
                         'service':prop(4),'parent':parent_id.value,'problem':problem.value if ok else None})
    finally: setup.SetupDiDestroyDeviceInfoList(handle)
    return rows

def safe_inventory(rows,connections=None):
    by_id = {r['id'].upper():r for r in rows}
    protected = {}
    for row in rows:
        kind = (row.get('class') or '').lower(); service = (row.get('service') or '').lower()
        name = (row.get('name') or '').lower()
        # A disconnected Bluetooth PAN is optional. Other network adapters remain protected.
        optional_pan=kind=='net' and service=='bthpan' and (connections or {}).get(row['id'].upper()) is False
        controller=service.startswith(('usbxhci','usbehci','usbohci','usbuhci')) or 'host controller' in name
        system=kind=='system' and not row['id'].upper().startswith('BTH')
        if kind in STORAGE_CLASSES or kind=='net' and not optional_pan or controller or system:
            reason='Active or unverified Bluetooth network' if service=='bthpan' else 'Network device' if kind=='net' else 'Storage device' if kind in STORAGE_CLASSES else 'USB host controller' if controller else 'System device'
            current = row['id'].upper(); visited=set()
            while current and current not in visited:
                visited.add(current)
                if current==row['id'].upper():protected[current]=reason
                else:protected.setdefault(current,'Required by '+(row.get('name') or reason))
                current = (by_id.get(current,{}).get('parent') or '').upper()
    result=[]
    for row in rows:
        uid=row['id']; kind=(row.get('class') or '').lower()
        current=uid.upper(); ancestors=set()
        while current and current not in ancestors:
            ancestors.add(current); current=(by_id.get(current,{}).get('parent') or '').upper()
        # Bluetooth logical services are not USB peripherals, even when their radio is USB-attached.
        usb=any(a.startswith('USB\\') for a in ancestors) and not uid.upper().startswith(('BTH','SWD\\'))
        keyboard=kind=='keyboard'
        # Only USB descendants and keyboard devices appear. Protected entries remain visible with a reason.
        if not usb and not keyboard: continue
        excluded=uid.upper() in protected or not INSTANCE.fullmatch(uid)
        service=(row.get('service') or '').lower()
        hub=service.startswith('usbhub') or 'usb root hub' in (row.get('name') or '').lower()
        radio=service=='bthusb'
        warning='Controls the whole USB hub and its connected devices, including inputs and Bluetooth.' if hub else 'Controls Bluetooth accessories, including wireless mice, controllers and audio.' if radio else ''
        result.append({'id':uid,'name':row.get('name') or uid,'class':row.get('class'),
                       'groups':(['usb'] if usb else [])+(['keyboard'] if keyboard else []),
                       'enabled':None if row.get('problem') is None else row.get('problem')!=22,
                       'problemCode':row.get('problem'),'protected':bool(excluded),
                       'reason':('Protected · '+protected.get(uid.upper(),'Invalid device instance ID')) if excluded else '',
                       'warning':warning,'requiresConfirmation':bool(warning),'parent':row.get('parent','')})
    return result

def pnp_action(action,uid):
    if action not in ('enable','disable','restart') or not isinstance(uid,str) or not INSTANCE.fullmatch(uid):
        raise ValueError('Invalid device action or instance ID')
    # Pass the ID as a subprocess argument; never build a shell command with it.
    result=subprocess.run(['pnputil.exe','/'+action+'-device',uid],capture_output=True,timeout=25,creationflags=HIDDEN)
    raw=result.stdout+result.stderr
    output=raw.decode('utf-16' if raw.startswith((b'\xff\xfe',b'\xfe\xff')) else 'utf-16-le' if b'\x00' in raw else 'utf-8',errors='replace').strip()
    if result.returncode: raise RuntimeError(output or 'Windows rejected the device action (code '+str(result.returncode)+')')
    return output[:1500]

def task_name(data): return 'HomeControl-DeviceRecovery-'+hashlib.sha256(str(data.resolve()).lower().encode()).hexdigest()[:12]

def register_recovery(data,deadline):
    root=Path(__file__).resolve().parent
    executable=Path(sys.executable).with_name('pythonw.exe')
    if not executable.exists(): executable=Path(sys.executable)
    config={'name':task_name(data),'exe':str(executable),'script':str(root/'device_controls.py'),
            'data':str(data.resolve()),'delay':max(1,deadline-time.time())}
    powershell(ps_config(config)+r'''
    $account=[Security.Principal.WindowsIdentity]::GetCurrent().Name
    $args='"'+$cfg.script+'" --recover --data "'+$cfg.data+'"'
    $action=New-ScheduledTaskAction -Execute $cfg.exe -Argument $args
    $once=New-ScheduledTaskTrigger -Once -At (Get-Date).AddSeconds($cfg.delay) -RepetitionInterval (New-TimeSpan -Minutes 1)
    $logon=New-ScheduledTaskTrigger -AtLogOn -User $account
    $principal=New-ScheduledTaskPrincipal -UserId $account -LogonType Interactive -RunLevel Highest
    $settings=New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 5)
    Register-ScheduledTask -TaskName $cfg.name -Action $action -Trigger @($once,$logon) -Principal $principal -Settings $settings -Description 'Re-enable only devices disabled by HomeControl after 60 seconds; retry disconnected peripherals.' -Force | Out-Null
    $verify=Get-ScheduledTask -TaskName $cfg.name
    if($verify.Principal.RunLevel -ne 'Highest' -or $verify.State -eq 'Disabled'){throw 'Recovery task was not armed'}
    ''')

class Journal:
    def __init__(self,data,clock=time.time):
        self.data=data; self.file=data/'device-recovery.json'; self.clock=clock
        self.name='Global\\'+task_name(data)
        self.api=C.WinDLL('kernel32',use_last_error=True)
        self.api.CreateMutexW.argtypes=[C.c_void_p,W.BOOL,W.LPCWSTR]; self.api.CreateMutexW.restype=W.HANDLE
        self.api.WaitForSingleObject.argtypes=[W.HANDLE,W.DWORD]; self.api.ReleaseMutex.argtypes=[W.HANDLE]; self.api.CloseHandle.argtypes=[W.HANDLE]
    @contextmanager
    def locked(self):
        mutex=self.api.CreateMutexW(None,False,self.name)
        if not mutex: raise C.WinError(C.get_last_error())
        owned=False
        try:
            outcome=self.api.WaitForSingleObject(mutex,30000)
            if outcome not in (0,0x80): raise RuntimeError('Device recovery is busy')
            owned=True; yield
        finally:
            if owned: self.api.ReleaseMutex(mutex)
            self.api.CloseHandle(mutex)
    def read(self):
        return json.loads(self.file.read_text(encoding='utf-8')) if self.file.exists() else {}
    def write(self,records): atomic_json(self.file,records)
    def recover(self,action=pnp_action,inventory=raw_inventory):
        results=[]
        with self.locked():
            records=self.read()
            due=[(uid,r) for uid,r in records.items() if r['deadline']<=self.clock()]
            if not due: return results
            def depth(item):
                uid=item[0]; seen=set()
                while uid in records and uid not in seen:
                    seen.add(uid); uid=records[uid].get('parent','')
                return len(seen)
            due.sort(key=depth)
            # Recovery is enable-only, and records only exist for previously enabled devices.
            for uid,record in due:
                if not INSTANCE.fullmatch(uid) or record.get('wasEnabled') is not True:
                    record['error']='Invalid recovery record'; continue
                try:
                    before=next((r for r in inventory() if r['id'].upper()==uid.upper()),None)
                    if not before or before.get('problem') is None:
                        raise RuntimeError('Device disconnected or state unavailable; will retry')
                    if before['problem']!=22:
                        # It is already enabled; never issue a redundant enable for a failed disable.
                        del records[uid]; results.append({'id':uid,'ok':True}); self.write(records); continue
                    action('enable',uid)
                    current=next((r for r in inventory() if r['id'].upper()==uid.upper()),None)
                    if not current or current.get('problem') in (None,22):
                        raise RuntimeError('Device disconnected or enabled state could not be confirmed; will retry')
                    del records[uid]; results.append({'id':uid,'ok':True})
                except Exception as exc:
                    record['error']=str(exc); results.append({'id':uid,'ok':False,'error':str(exc)})
                self.write(records)
            self.write(records)
        return results

class Devices:
    def __init__(self,data,inventory=raw_inventory,action=pnp_action,register=register_recovery,clock=time.time,connections=network_connections):
        self.data=data; self.inventory=inventory; self.action=action; self.register=register; self.clock=clock; self.connections=connections
        self.journal=Journal(data,clock); self.file=data/'device-selections.json'; self.lock=threading.RLock()
        self.selections=json.loads(self.file.read_text()) if self.file.exists() else {'usb':[],'keyboard':[]}
        self.cached=[]; self.error=''; self.sampledAt=None
    def refresh(self):
        rows=safe_inventory(self.inventory(),self.connections())
        with self.lock: self.cached=rows; self.sampledAt=self.clock(); self.error=''
        return rows
    def status(self):
        with self.lock:
            with self.journal.locked(): recovery=self.journal.read()
            return {'devices':self.cached,'selections':self.selections,'recovery':recovery,'error':self.error,'sampledAt':self.sampledAt}
    def select(self,groups):
        if not isinstance(groups,dict) or set(groups)!= {'usb','keyboard'}: raise ValueError('USB and keyboard selections required')
        with self.lock:
            inventory={d['id']:d for d in self.refresh()}
            chosen={}
            for group,ids in groups.items():
                if not isinstance(ids,list) or len(ids)>16 or any(not isinstance(uid,str) for uid in ids): raise ValueError('Select up to 16 devices per group')
                chosen[group]=list(dict.fromkeys(ids))
                for uid in chosen[group]:
                    d=inventory.get(uid)
                    if not d or d['protected'] or group not in d['groups']: raise ValueError('Selection includes an unavailable or protected device')
            atomic_json(self.file,chosen); self.selections=chosen
        return self.status()
    def perform(self,group,action,confirmed=False):
        if group not in ('usb','keyboard','both') or action not in ('enable','disable','restart'): raise ValueError('Invalid device group or action')
        with self.lock:
            chosen=list(dict.fromkeys(uid for g in (('usb','keyboard') if group=='both' else (group,)) for uid in self.selections[g]))
            if not chosen: raise ValueError('Select and save devices first')
            inventory={d['id']:d for d in self.refresh()}
            if action in ('disable','restart') and confirmed is not True and any(inventory.get(uid,{}).get('requiresConfirmation') for uid in chosen):
                raise ValueError('Confirm the USB hub or Bluetooth action before continuing')
            # Disable children first; enable/restart parents first. This keeps child recovery intents valid.
            def depth(uid):
                seen=set()
                while uid in inventory and uid not in seen:
                    seen.add(uid); uid=inventory[uid]['parent']
                return len(seen)
            chosen.sort(key=depth,reverse=action=='disable')
            results=[]
            with self.journal.locked():
                records=self.journal.read()
                for uid in chosen:
                    # Connections and attachments can change since selections were saved or the last action.
                    if action in ('disable','restart'):
                        inventory={d['id']:d for d in self.refresh()}
                    d=inventory.get(uid)
                    if not d or d['protected'] or not INSTANCE.fullmatch(uid):
                        results.append({'id':uid,'ok':False,'error':'Unavailable or protected device'}); continue
                    if d['enabled'] is None:
                        results.append({'id':uid,'ok':False,'error':'Enabled state is unavailable'}); continue
                    if action=='disable' and d['enabled'] is False:
                        results.append({'id':uid,'ok':True,'message':'Already disabled; no recovery change'}); continue
                    if action=='restart' and not d['enabled']:
                        results.append({'id':uid,'ok':False,'error':'Enable the device before restarting it'}); continue
                    needs_recovery=action=='disable' or action=='restart' and d['requiresConfirmation']
                    if needs_recovery and uid in records:
                        results.append({'id':uid,'ok':False,'error':'Automatic recovery already pending'}); continue
                    try:
                        if needs_recovery:
                            # Durable intent and an independently verified task must both precede disable.
                            records[uid]={'wasEnabled':True,'deadline':self.clock()+60,'name':d['name'],'parent':d['parent']}
                            self.journal.write(records)
                            try: self.register(self.data,min(r['deadline'] for r in records.values()))
                            except Exception:
                                del records[uid]; self.journal.write(records); raise
                        output=self.action(action,uid)
                        if action in ('enable','disable','restart'):
                            expected=22 if action=='disable' else None
                            for attempt in range(5):
                                state=next((r for r in self.inventory() if r['id'].upper()==uid.upper()),None)
                                confirmed=state and state.get('problem') is not None and (state['problem']==22 if expected==22 else state['problem']!=22)
                                if confirmed:break
                                if attempt<4:time.sleep(.15)
                            if not confirmed:raise RuntimeError('Windows returned without confirming the device '+('disabled' if action=='disable' else 'enabled')+' state. '+output)
                        # Never discard a recovery record based on command output alone.
                        if action=='enable' and uid in records:
                            state=next((r for r in self.inventory() if r['id']==uid),None)
                            if state and state.get('problem') not in (None,22): del records[uid]; self.journal.write(records)
                        results.append({'id':uid,'name':d['name'],'ok':True,'message':output,
                                        'recoverySeconds':60 if needs_recovery else None})
                    except Exception as exc:
                        # A partially successful disable still has its pre-armed recovery record.
                        results.append({'id':uid,'name':d['name'],'ok':False,'error':str(exc)})
            return {'results':results}
    def reconcile(self): return self.journal.recover(self.action,self.inventory)
    def arm_pending(self):
        with self.journal.locked():
            records=self.journal.read()
            if records: self.register(self.data,min(r['deadline'] for r in records.values()))

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--recover',action='store_true'); parser.add_argument('--data',type=Path,required=True)
    args=parser.parse_args(); args.data.mkdir(parents=True,exist_ok=True)
    if args.recover:
        try: Journal(args.data).recover()
        except Exception as exc:
            with (args.data/'device-recovery.log').open('a',encoding='utf-8') as log: log.write(str(exc)+'\n')
            raise
