"""Explicit opt-in load. Active sessions are never restored from disk."""
import json
import os
import subprocess
import sys
import threading
import time
from gpu_native import adapters
from remote_terminal import CommandJob
from win_support import atomic_json,HIDDEN

class GpuLoad:
    def __init__(self,root,data):
        self.root=root; self.control=data/'gpu-load-control.json'; self.result=data/'gpu-load-status.json'
        self.lock=threading.RLock(); self.process=None; self.job=None; self.config=None; self.end=0; self.reason='Off'; self.detail={}
    def start(self,adapter,duty=25,minutes=1):
        if type(duty) is not int or not 0<=duty<=90: raise ValueError('Workload duty must be 0–90%')
        if type(minutes) is not int or minutes not in (1,5,15): raise ValueError('Choose a 1, 5 or 15 minute session')
        if adapter not in {a['id'] for a in adapters()}: raise ValueError('Choose a connected hardware GPU')
        with self.lock:
            if self.process is not None: raise RuntimeError('Stop the current workload before starting another')
            self.result.unlink(missing_ok=True)
            self.config={'adapter':adapter,'duty':duty,'seconds':minutes*60,'parentPid':os.getpid()}
            atomic_json(self.control,self.config); job=CommandJob(); process=None
            try:
                process=subprocess.Popen([sys.executable,str(self.root/'gpu_worker.py'),str(self.control),str(self.result)],
                                         stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=HIDDEN)
                job.add(process.pid)
            except Exception:
                job.close()
                if process: process.kill(); process.wait()
                self.config=None
                raise
            self.process=process; self.job=job; self.end=time.monotonic()+minutes*60; self.detail={}; self.reason='Starting'
        return self.status()
    def update(self,duty):
        if type(duty) is not int or not 0<=duty<=90: raise ValueError('Workload duty must be 0–90%')
        with self.lock:
            if not self.process: raise RuntimeError('Start a workload first')
            self.config['duty']=duty; atomic_json(self.control,self.config)
        return self.status()
    def stop(self,reason='Stopped'):
        with self.lock:
            if self.process:
                atomic_json(self.control,{**self.config,'stop':True,'reason':reason})
                try: self.process.wait(timeout=1)
                except subprocess.TimeoutExpired: pass
                self.job.close(); self.job=None
                self.process.wait(timeout=3); self.process=None
            self.reason=reason; self.config=None
        return self.status()
    def tick(self,gpus):
        with self.lock:
            if not self.process: return
            selected=next((a for a in gpus if a['id']==self.config['adapter']),None)
            if self.result.exists():
                try: self.detail=json.loads(self.result.read_text())
                except (OSError,ValueError): pass
            reason=None
            if selected and selected.get('temperatureC') is not None and selected['temperatureC']>=85: reason='Stopped at 85°C'
            elif selected is None: reason='Selected GPU unavailable'
            elif time.monotonic()>=self.end: reason='Session expired'
            elif self.process.poll() is not None: reason=self.detail.get('error',self.detail.get('reason','GPU worker exited'))
            if reason: self.stop(reason)
    def status(self):
        with self.lock:
            return {'running':self.process is not None,'adapter':self.config['adapter'] if self.config else None,
                    'duty':self.config['duty'] if self.config else 25,'secondsLeft':max(0,round(self.end-time.monotonic())) if self.process else 0,
                    'reason':self.reason,**{k:v for k,v in self.detail.items() if k in ('priorityAccepted','priorityError','error')}}
