"""A visible dashboard control for a bounded, reversible gradual CPU slowdown."""
import threading
import time

class GradualLag:
    def __init__(self,cpu,other_active=lambda:False,power_pending=lambda:False,clock=time.monotonic):
        self.cpu=cpu;self.other_active=other_active;self.power_pending=power_pending;self.clock=clock
        self.lock=threading.RLock();self.active=None;self.state='idle';self.error=''
    def blocked(self):
        with self.lock:return self.active is not None or self.cpu.file.exists()
    def status(self):
        with self.lock:
            mode=self.active
            return {'active':mode is not None,'state':self.state,'error':self.error,
                'ac':mode['values'][0] if mode else None,'battery':mode['values'][1] if mode else None,
                'floor':mode['floor'] if mode else None,'rate':1,
                'seconds':max(0,round(mode['end']-self.clock(),1)) if mode else 0,
                'recoveryPending':self.cpu.file.exists() and not self.other_active()}
    def start(self,floor=10,hold=30):
        if type(floor) is not int or not 1<=floor<=99:raise ValueError('Minimum CPU cap must be 1–99%.')
        if type(hold) is not int or not 0<=hold<=60:raise ValueError('Hold must be 0–60 seconds.')
        with self.lock:
            if self.blocked() or self.other_active():raise RuntimeError('Cancel the active mode or recover its CPU settings first.')
            if self.power_pending():raise RuntimeError('Cancel the pending power action first.')
            self.error='';self.state='starting'
            try:
                # 100→1 takes at most 99 seconds; independent recovery includes the hold and margin.
                saved=self.cpu.arm(99+hold+15)
                values=saved['values']
                if any(type(v) is not int or not 1<=v<=100 for v in values):raise RuntimeError('Current CPU settings are unavailable.')
                steps=max(values)-floor
                if steps<=0:raise ValueError('Choose a minimum below the current CPU cap.')
                now=self.clock()
                self.active={'original':values,'values':list(values),'floor':floor,'start':now,'end':now+steps+hold,'last':now,'step':0}
                self.state='lowering'
            except Exception as exc:
                self._finish('failed',str(exc));raise RuntimeError(self.error) from None
            return self.status()
    def _finish(self,state,error=''):
        self.active=None;self.state=state;self.error=error
        try:self.cpu.restore(force=True)
        except Exception as exc:self.state='recovery_needed';self.error+=' CPU recovery: '+str(exc)
    def cancel(self):
        with self.lock:
            if self.other_active():raise RuntimeError('Cancel Tweakout using its dashboard control.')
            self._finish('cancelled');return self.status()
    def tick(self):
        with self.lock:
            mode=self.active
            if not mode:return
            now=self.clock()
            if now-mode['last']>5:
                self._finish('cancelled','Computer resumed or control was delayed. Previous CPU settings restored.');return
            mode['last']=now
            if now>=mode['end']:
                self._finish('finished');return
            step=int(now-mode['start'])
            if step==mode['step']:return
            try:
                values=[min(v,max(mode['floor'],v-step)) for v in mode['original']]
                if values!=mode['values']:self.cpu.set_values(values)
                mode['values']=values;mode['step']=step
                self.state='holding' if max(values)<=mode['floor'] else 'lowering'
            except Exception as exc:self._finish('failed',str(exc))
    def close(self):
        with self.lock:
            if self.active:self._finish('cancelled')
