"""PresentMon CSV stays in memory. Presented frames are not displayed frames."""
import csv
import ctypes
from ctypes import wintypes as W
from collections import deque
import hashlib
import json
import math
import subprocess
import threading
import time
from app_limits import processes
from remote_terminal import CommandJob
from win_support import atomic_json, HIDDEN

CHECKSUM = 'b2a706bc6ad475749e3b7e3409263aa1e6906d45bdcf993f6dbc0f660188f1af'

class Frames:
    def __init__(self): self.reset()
    def reset(self):
        self.chains = {}; self.last_arrival = None; self.last_event = None
    def add(self, chain, timestamp, now):
        if not math.isfinite(timestamp): return
        if self.last_event is not None and timestamp < self.last_event - 2: self.reset()
        self.prune(timestamp)
        if chain not in self.chains and len(self.chains) >= 16: return
        points = self.chains.setdefault(chain, deque(maxlen=8192))
        if points and timestamp <= points[-1]: return
        points.append(timestamp)
        self.last_event = max(timestamp, self.last_event or timestamp)
        self.last_arrival = now
        self.prune(timestamp)
    def prune(self, timestamp):
        for chain, points in list(self.chains.items()):
            while points and points[0] < timestamp - 2: points.popleft()
            if not points: del self.chains[chain]
    def reading(self, now):
        if self.last_arrival is None: return {'fps':None, 'state':'no_frames'}
        age = max(0, now - self.last_arrival)
        if age >= 5:
            self.reset()
            return {'fps':None, 'state':'stale'}
        self.prune(self.last_event + age)
        if not self.chains: return {'fps':None, 'state':'no_frames'}
        chain, points = max(self.chains.items(), key=lambda item:len(item[1]))
        span = points[-1] - points[0] if len(points) > 1 else 0
        return {'fps':round((len(points)-1)/span, 1) if span > 0 else None,
                'state':'tracking' if span > 0 else 'warming_up', 'swapChain':chain, 'frameCount':len(points)}

def running_apps():
    return [{'pid':pid,'name':name} for pid,name in processes() if pid > 4 and name]

def foreground_pid():
    user = ctypes.WinDLL('user32'); user.GetForegroundWindow.restype = W.HWND
    user.GetWindowThreadProcessId.argtypes = [W.HWND,ctypes.POINTER(W.DWORD)]
    pid = W.DWORD(); user.GetWindowThreadProcessId(user.GetForegroundWindow(),ctypes.byref(pid))
    return pid.value

class FpsMonitor:
    def __init__(self, root, data):
        self.root = root; self.file = data/'fps-settings.json'
        settings = json.loads(self.file.read_text()) if self.file.exists() else {}
        self.enabled = settings.get('enabled',True) is True
        self.pin = None; self.target = None; self.name = 'No foreground app'
        self.lock = threading.RLock(); self.lifecycle = threading.Lock(); self.frames = Frames()
        self.process = None; self.job = None; self.error = ''; self.error_state = ''; self.closing = False
        self.csv_fields=[]; self.frames_seen=0
        self.exe = root/'vendor'/'presentmon'/'PresentMon-2.6.0-x64.exe'
        self.session = 'HomeControlFPS-'+hashlib.sha256(str(data.resolve()).lower().encode()).hexdigest()[:16]
    def update_target(self, apps=None, pid=None):
        apps = running_apps() if apps is None else apps
        names = {app['pid']:app['name'] for app in apps}
        with self.lock:
            selected = self.pin if self.pin is not None else (foreground_pid() if pid is None else pid)
            if selected not in names: selected = None
            if selected != self.target: self.frames.reset(); self.target = selected
            self.name = names.get(selected,'Pinned app exited' if self.pin is not None else 'No foreground app')
    def settings(self, enabled, pid):
        if type(enabled) is not bool: raise ValueError('FPS enabled must be true or false')
        if pid is not None and (type(pid) is not int or pid not in {a['pid'] for a in running_apps()}):
            raise ValueError('Choose a running application or automatic foreground tracking')
        with self.lifecycle:
            with self.lock:
                changed = self.enabled != enabled
                self.enabled = enabled; self.pin = pid; self.frames.reset()
                atomic_json(self.file,{'enabled':enabled})
            if not enabled: self._stop()
            elif changed or self.process is None or self.process.poll() is not None: self._launch()
        self.update_target()
        return self.status()
    def status(self):
        with self.lock:
            result = self.frames.reading(time.monotonic()) if self.enabled else {'fps':None,'state':'disabled'}
            if self.enabled and self.error_state: result = {'fps':None,'state':self.error_state}
            return {**result,'enabled':self.enabled,'mode':'pinned' if self.pin else 'foreground',
                    'pid':self.target,'pinnedPid':self.pin,'application':self.name,'error':self.error,'windowSeconds':2,
                    'helperFramesSeen':self.frames_seen,'helperColumns':self.csv_fields}
    def feed(self, row, now=None):
        self.frames_seen+=1
        try:
            pid = int(row['ProcessID']); chain = row['SwapChainAddress']
            timestamp = float(row['TimeInSeconds'])
        except (KeyError,ValueError): return
        with self.lock:
            if pid == self.target: self.frames.add(chain,timestamp,time.monotonic() if now is None else now)
    def start(self):
        with self.lifecycle:
            # This dedicated name is ours; never terminate another PresentMon session.
            try: self._cleanup_session()
            except Exception as exc: self.error=str(exc)
            if self.enabled: self._launch()
    def _cleanup_session(self):
        if self.exe.exists():
            subprocess.run([str(self.exe),'--session_name',self.session,'--terminate_existing_session'],
                           stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=5,creationflags=HIDDEN)
    def _launch(self):
        if self.job: self.job.close(); self.job=None
        self.error = ''; self.error_state = ''; self.closing = False
        try:
            if hashlib.sha256(self.exe.read_bytes()).hexdigest() != CHECKSUM:
                raise RuntimeError('Bundled PresentMon checksum mismatch')
            job = CommandJob()
            try:
                process = subprocess.Popen([str(self.exe),'--output_stdout','--no_console_stats','--v1_metrics',
                    '--no_track_gpu','--no_track_input','--no_track_display','--session_name',self.session,
                    '--stop_existing_session'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                    stdin=subprocess.DEVNULL,creationflags=HIDDEN,text=True,encoding='utf-8',errors='replace',bufsize=1)
                job.add(process.pid)
            except Exception:
                job.close()
                if 'process' in locals(): process.kill(); process.wait()
                raise
            self.job = job; self.process = process
            def read():
                try:
                    fields=None
                    for line in process.stdout:
                        values=next(csv.reader([line]))
                        if 'ProcessID' in values and 'SwapChainAddress' in values: fields=values; self.csv_fields=values
                        elif fields and len(values)==len(fields): self.feed(dict(zip(fields,values)))
                except Exception as exc:
                    with self.lock: self.error = str(exc); self.error_state = 'helper_error'
                finally:
                    process.stdout.close()
                    process.wait()
                    if not self.closing and self.process is process:
                        with self.lock:
                            if not self.error_state: self.error_state = 'helper_error'; self.error = 'PresentMon exited (code '+str(process.returncode)+')'
            def errors():
                for line in process.stderr:
                    with self.lock:
                        if self.process is not process: continue
                        self.error = (self.error+line)[-2048:]
                        lower = line.lower()
                        if any(word in lower for word in ['access denied','administrator','privilege','0x80070005']):
                            self.error_state = 'insufficient_permissions'
                process.stderr.close()
            threading.Thread(target=errors,daemon=True).start()
            threading.Thread(target=read,daemon=True).start()
        except Exception as exc:
            self.error = str(exc); self.error_state = 'helper_error'
    def _stop(self):
        self.closing = True
        try: self._cleanup_session()
        except Exception: pass
        if self.job: self.job.close(); self.job = None
        if self.process:
            try: self.process.wait(timeout=3)
            except subprocess.TimeoutExpired: self.process.kill(); self.process.wait()
            self.process = None
        with self.lock: self.frames.reset(); self.error = ''; self.error_state = ''
    def close(self):
        with self.lifecycle: self._stop()
