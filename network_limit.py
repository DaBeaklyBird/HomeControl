"""Explicit internet limits; no saved rate is restored after startup."""
import json
import os
import secrets
import subprocess
import sys
import threading
import time
from network_native import verify_vendor,validate_rate
from remote_terminal import CommandJob
from win_support import atomic_json,HIDDEN

class NetworkLimit:
    def __init__(self,root,data):
        self.root=root;self.control=data/'network-limit-control.json';self.result=data/'network-limit-status.json'
        self.lock=threading.RLock();self.process=None;self.job=None;self.config=None;self.detail={}
        self.reason='Unlimited';self.error='';self.available=True
        try:verify_vendor(root)
        except Exception as exc:self.available=False;self.error=str(exc)
    def _detail(self):
        try:
            detail=json.loads(self.result.read_text())
            if self.config and detail.get('session')==self.config['session']:self.detail=detail
        except (OSError,ValueError):pass
    def apply(self,mbps):
        rate=validate_rate(mbps)
        if rate is None:return self.stop()
        with self.lock:
            self.tick()
            if not self.available:raise RuntimeError(self.error)
            if self.process:
                self.config['mbps']=rate;atomic_json(self.control,self.config)
                self.reason='Limiting';return self.status()
            self.error='';self.detail={};self.result.unlink(missing_ok=True)
            self.config={'mbps':rate,'parentPid':os.getpid(),'session':secrets.token_hex(16),'armed':False}
            atomic_json(self.control,self.config);job=CommandJob();process=None
            try:
                process=subprocess.Popen([sys.executable,str(self.root/'network_worker.py'),str(self.control),str(self.result)],
                    stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=HIDDEN)
                job.add(process.pid)
                self.config['armed']=True;atomic_json(self.control,self.config)
                self.process=process;self.job=job;self.reason='Starting'
                end=time.monotonic()+8
                while time.monotonic()<end:
                    self._detail()
                    if self.detail.get('running'):self.reason='Limiting';return self.status()
                    if process.poll() is not None:break
                    time.sleep(.05)
                self._detail();message=self.detail.get('error') or 'Internet limiter did not become ready. Normal internet access was restored.'
                self.error=message;raise RuntimeError(message)
            except Exception:
                if self.process:self.stop()
                else:
                    job.close()
                    if process:process.kill();process.wait()
                    self.config=None
                raise
    def stop(self):
        with self.lock:
            if self.process:
                atomic_json(self.control,{**self.config,'stop':True})
                try:self.process.wait(timeout=2.5)
                except subprocess.TimeoutExpired:pass
                self.job.close();self.process.wait(timeout=3)
            self.process=None;self.job=None;self.config=None;self.detail={};self.reason='Unlimited'
        return self.status()
    def tick(self):
        with self.lock:
            if not self.process:return
            self._detail()
            if self.process.poll() is not None or (self.detail.get('heartbeat') and time.time()-self.detail['heartbeat']>5):
                message=self.detail.get('error') or 'Internet limiter stopped. Normal internet access was restored.'
                self.stop();self.error=message
    def status(self):
        with self.lock:
            self._detail()
            return {'available':self.available,'running':self.process is not None,'mbps':self.config['mbps'] if self.config else None,
                    'reason':self.reason,'error':self.error,'downloadMbps':self.detail.get('downloadMbps'),
                    'uploadMbps':self.detail.get('uploadMbps')}
