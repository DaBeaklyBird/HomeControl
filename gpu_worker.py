"""Disposable compute process. Parent job + watchdog + bounded work + expiry."""
import ctypes as C
from ctypes import wintypes as W
import json
from pathlib import Path
import sys
import time
from gpu_native import Compute
from win_support import atomic_json

def run(control,status):
    config=json.loads(control.read_text()); end=time.monotonic()+min(900,config['seconds'])
    api=C.WinDLL('kernel32'); api.OpenProcess.argtypes=[W.DWORD,W.BOOL,W.DWORD]; api.OpenProcess.restype=W.HANDLE
    api.WaitForSingleObject.argtypes=[W.HANDLE,W.DWORD]; api.CloseHandle.argtypes=[W.HANDLE]
    owner=api.OpenProcess(0x100000,False,config['parentPid'])
    if not owner: raise RuntimeError('HomeControl owner is no longer running')
    compute=None; reason='Session expired'
    try:
        compute=Compute(config['adapter'])
        atomic_json(status,{'running':True,'priorityAccepted':compute.priorityAccepted,'priorityError':compute.priorityError})
        while time.monotonic()<end:
            if api.WaitForSingleObject(owner,0)==0: reason='HomeControl exited'; break
            cfg=json.loads(control.read_text())
            if cfg.get('stop'): reason=cfg.get('reason','Stopped'); break
            duty=cfg['duty']
            if type(duty) is not int or not 0<=duty<=90: raise RuntimeError('Invalid duty setting')
            cycle=time.monotonic(); work_end=cycle+.1*duty/100
            while time.monotonic()<work_end and time.monotonic()<end:
                compute.dispatch(time.monotonic()+.25)
            # Each 100 ms cycle yields; a single dispatch never grows with duty.
            time.sleep(max(.001,cycle+.1-time.monotonic()))
    finally:
        if compute: compute.close()
        api.CloseHandle(owner)
        atomic_json(status,{'running':False,'reason':reason})

if __name__=='__main__':
    control=Path(sys.argv[1]); status=Path(sys.argv[2])
    try: run(control,status)
    except Exception as exc: atomic_json(status,{'running':False,'error':str(exc)})
