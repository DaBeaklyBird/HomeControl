"""Disposable, bounded packet shaper. Closing its handles restores normal routing."""
import ctypes as C
from ctypes import wintypes as W
import json
from pathlib import Path
import sys
import threading
import time
from network_native import Divert,Pace,packet_filter,validate_rate
from win_support import atomic_json

class Shaper:
    def __init__(self,root,mbps,filters=None,divert=None,clock=time.monotonic):
        self.divert=divert or Divert(root);self.mbps=validate_rate(mbps);self.clock=clock
        self.stop=threading.Event();self.lock=threading.Lock();self.handles=[];self.threads=[]
        self.sent=[0,0];self.error=''
        filters=filters or [packet_filter('inbound'),packet_filter('outbound')]
        try:
            for text in filters:self.handles.append(self.divert.open(text))
            for index,handle in enumerate(self.handles):
                thread=threading.Thread(target=self.pump,args=(index,handle),daemon=True)
                self.threads.append(thread);thread.start()
        except Exception:
            self.close();raise
    def update(self,mbps):
        value=validate_rate(mbps)
        if value is None:raise ValueError('Close the shaper for Unlimited.')
        with self.lock:self.mbps=value
    def pump(self,index,handle):
        rate=self.mbps;pace=Pace(rate,self.clock)
        try:
            while True:
                item=self.divert.receive(handle)
                if item is None:break
                packet,size,address=item
                with self.lock:rate=self.mbps
                if rate!=pace.bytes_per_second*8/1_000_000:pace.set_rate(rate)
                delay=pace.delay(size)
                # Python's Windows sleep timer avoids coarse Event.wait pacing.
                # Short waits also let Stop and rate changes interrupt large packets.
                while not self.stop.is_set() and delay>0:
                    time.sleep(min(.005,delay))
                    with self.lock:updated=self.mbps
                    if updated!=rate:
                        rate=updated;pace.set_rate(rate);delay=pace.delay(size)
                    else:delay=max(0,pace.deadline-self.clock())
                self.divert.send(handle,packet,size,address)
                with self.lock:self.sent[index]+=size
        except Exception as exc:
            with self.lock:self.error=str(exc)
            self.stop.set()
    def totals(self):
        with self.lock:return list(self.sent)
    def close(self):
        self.stop.set()
        for handle in self.handles:self.divert.shutdown(handle)
        # RECV shutdown lets queued packets drain without further throttling.
        for thread in self.threads:thread.join(timeout=1)
        for handle in self.handles:self.divert.close(handle)
        self.handles=[]

def run(root,control,status):
    cfg=json.loads(control.read_text()); session=cfg['session'];shaper=None
    api=C.WinDLL('kernel32',use_last_error=True)
    api.OpenProcess.argtypes=[W.DWORD,W.BOOL,W.DWORD];api.OpenProcess.restype=W.HANDLE
    api.WaitForSingleObject.argtypes=[W.HANDLE,W.DWORD];api.CloseHandle.argtypes=[W.HANDLE]
    owner=api.OpenProcess(0x100000,False,cfg['parentPid'])
    if not owner:raise RuntimeError('HomeControl owner is no longer running')
    reason='Unlimited';error=''
    try:
        deadline=time.monotonic()+5
        while not cfg.get('armed'):
            if api.WaitForSingleObject(owner,0)==0:raise RuntimeError('HomeControl exited')
            if time.monotonic()>deadline:raise RuntimeError('Network worker could not join its owner job')
            time.sleep(.05);cfg=json.loads(control.read_text())
        shaper=Shaper(root,cfg['mbps']);previous=[0,0];sample=time.monotonic();rates=[0,0]
        while True:
            now=time.monotonic()
            if api.WaitForSingleObject(owner,0)==0:reason='HomeControl exited';break
            cfg=json.loads(control.read_text())
            if cfg.get('stop') or cfg.get('session')!=session:break
            shaper.update(cfg['mbps'])
            if shaper.error:raise RuntimeError(shaper.error)
            if now-sample>=1:
                totals=shaper.totals();rates=[round((a-b)*8/(now-sample)/1_000_000,2) for a,b in zip(totals,previous)]
                previous=totals;sample=now
            atomic_json(status,{'session':session,'running':True,'mbps':shaper.mbps,
                                'downloadMbps':rates[0],'uploadMbps':rates[1],'heartbeat':time.time()})
            time.sleep(.2)
    except Exception as exc:error=str(exc)
    finally:
        if shaper:shaper.close()
        api.CloseHandle(owner)
        atomic_json(status,{'session':session,'running':False,'reason':reason,'error':error})

if __name__=='__main__':
    control=Path(sys.argv[1]);status=Path(sys.argv[2])
    try:run(Path(__file__).resolve().parent,control,status)
    except Exception as exc:atomic_json(status,{'running':False,'error':str(exc)})
