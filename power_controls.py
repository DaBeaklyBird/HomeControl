"""Ten-second app countdown; Windows /t > 0 would imply forced closure."""
import ctypes
import subprocess
import threading
import time
from win_support import HIDDEN

class PowerActions:
    def __init__(self,clock=time.monotonic,runner=subprocess.run,locker=None):
        self.clock=clock; self.runner=runner; self.locker=locker or ctypes.WinDLL('user32').LockWorkStation
        self.lock=threading.Lock(); self.pending=None; self.error=''
    def status(self):
        with self.lock:
            return {'pending':{'action':self.pending[0],'seconds':max(0,round(self.pending[1]-self.clock(),1))} if self.pending else None,'error':self.error}
    def request(self,action):
        if action not in ['lock','restart','shutdown']: raise ValueError('Choose lock, restart or shutdown')
        with self.lock:
            if action=='lock':
                if not self.locker(): raise RuntimeError('Windows could not lock this session')
            else:
                if self.pending: raise RuntimeError('Cancel the pending power action first')
                self.pending=(action,self.clock()+10); self.error=''
        return self.status()
    def cancel(self):
        with self.lock: self.pending=None
        return self.status()
    def _execute(self,action):
        result=self.runner(['shutdown.exe','/r' if action=='restart' else '/s','/t','0'],capture_output=True,timeout=5,creationflags=HIDDEN)
        if result.returncode:raise RuntimeError(result.stderr.decode(errors='replace') or 'Windows rejected the power action')
    def execute(self,action):
        if action not in ('restart','shutdown'):raise ValueError('Choose restart or shutdown')
        with self.lock:
            if self.pending:raise RuntimeError('Cancel the pending power action first')
            self._execute(action)
    def tick(self):
        with self.lock:
            if not self.pending or self.clock()<self.pending[1]: return
            action=self.pending[0]; self.pending=None
            # Serialize cancellation with dispatch so it has an unambiguous deadline.
            try:
                self._execute(action)
            except Exception as exc: self.error=str(exc)
