"""Fast two-second Windows sampling, independent of NVIDIA cap discovery."""
import ctypes as C
from ctypes import wintypes as W
import csv
import io
import json
import re
import threading
import time
from gpu_native import adapters
from fps_monitor import running_apps

class Memory(C.Structure):
    _fields_=[('length',W.DWORD),('load',W.DWORD)]+[(n,C.c_uint64) for n in ['total','available','pageTotal','pageAvailable','virtualTotal','virtualAvailable','extended']]
class Battery(C.Structure):
    _fields_=[('ac',W.BYTE),('flags',W.BYTE),('percent',W.BYTE),('reserved',W.BYTE),('life',W.DWORD),('fullLife',W.DWORD)]
class CounterValue(C.Structure):_fields_=[('status',W.DWORD),('value',C.c_double)]
class CounterItem(C.Structure):_fields_=[('name',W.LPWSTR),('value',CounterValue)]

class GpuCounters:
    def __init__(self):
        self.api=C.WinDLL('pdh'); self.query=C.c_void_p(); self.counter=C.c_void_p()
        self.api.PdhOpenQueryW.argtypes=[W.LPCWSTR,C.c_size_t,C.POINTER(C.c_void_p)]
        self.api.PdhAddEnglishCounterW.argtypes=[C.c_void_p,W.LPCWSTR,C.c_size_t,C.POINTER(C.c_void_p)]
        self.api.PdhCollectQueryData.argtypes=[C.c_void_p]
        self.api.PdhCloseQuery.argtypes=[C.c_void_p]
        self.api.PdhGetFormattedCounterArrayW.argtypes=[C.c_void_p,W.DWORD,C.POINTER(W.DWORD),C.POINTER(W.DWORD),C.c_void_p]
        if self.api.PdhOpenQueryW(None,0,C.byref(self.query)): raise RuntimeError('GPU performance counters unavailable')
        if self.api.PdhAddEnglishCounterW(self.query,r'\GPU Engine(*)\Utilization Percentage',0,C.byref(self.counter)):
            self.close(); raise RuntimeError('GPU engine counters unsupported by this driver')
        self.api.PdhCollectQueryData(self.query)
    def sample(self):
        if self.api.PdhCollectQueryData(self.query): return {}
        size=W.DWORD(); count=W.DWORD()
        hr=self.api.PdhGetFormattedCounterArrayW(self.counter,0x200,C.byref(size),C.byref(count),None)
        if hr & 0xffffffff != 0x800007d2 or not size.value: return {}
        buf=C.create_string_buffer(size.value)
        if self.api.PdhGetFormattedCounterArrayW(self.counter,0x200,C.byref(size),C.byref(count),buf): return {}
        totals={}
        for item in C.cast(buf,C.POINTER(CounterItem))[:count.value]:
            match=re.search(r'luid_0x([0-9a-f]+)_0x([0-9a-f]+)_phys_(\d+)_eng_(\d+)',item.name,re.I)
            if match and item.value.status in (0,1):
                high,low,physical,engine=match.groups(); uid=f'{int(high,16):08x}:{int(low,16):08x}'
                key=(uid,physical,engine); totals[key]=totals.get(key,0)+max(0,item.value.value)
        result={}
        for (uid,_,_),value in totals.items(): result[uid]=max(result.get(uid,0),min(100,value))
        return result
    def close(self):
        if self.query: self.api.PdhCloseQuery(self.query); self.query=None

class Metrics:
    def __init__(self, fps, stop, smi):
        self.fps=fps; self.stop=stop; self.smi=smi; self.lock=threading.Lock()
        self.value={'cpuPercent':None,'ram':None,'battery':None,'gpus':[],'cpuTemperatureC':None,'sampledAt':None,'apps':[]}
        self.previous=None; self.nvidia={}; self.gpu_error=''; self.adapter_list=[]
    def status(self):
        with self.lock: result=json.loads(json.dumps(self.value))
        if result['sampledAt'] and time.time()-result['sampledAt']>5:
            result.update(cpuPercent=None,ram=None,battery=None,gpus=[],error='Hardware sampler is stale')
        result['fps']=self.fps.status()
        return result
    def sample(self,counters):
        self.adapter_list=adapters()
        kernel=C.WinDLL('kernel32'); idle=C.c_uint64(); system=C.c_uint64(); user=C.c_uint64()
        cpu=None
        if kernel.GetSystemTimes(C.byref(idle),C.byref(system),C.byref(user)):
            current=(idle.value,system.value+user.value)
            if self.previous:
                elapsed=current[1]-self.previous[1]; idle_delta=current[0]-self.previous[0]
                if elapsed>0: cpu=round(max(0,min(100,100*(elapsed-idle_delta)/elapsed)),1)
            self.previous=current
        memory=Memory(); memory.length=C.sizeof(memory); ram=None
        if kernel.GlobalMemoryStatusEx(C.byref(memory)):
            ram={'usedBytes':memory.total-memory.available,'totalBytes':memory.total,'percent':memory.load}
        battery=Battery(); bat=None
        if kernel.GetSystemPowerStatus(C.byref(battery)) and battery.flags!=128 and battery.percent!=255:
            bat={'percent':battery.percent,'charging':bool(battery.flags&8),'pluggedIn':battery.ac==1,'secondsLeft':None if battery.life==0xffffffff else battery.life}
        usage=counters.sample() if counters else {}
        with self.lock: nv=dict(self.nvidia)
        gpus=[]
        for adapter in self.adapter_list:
            extra=nv.get(adapter['name'],{})
            gpus.append({**adapter,'usagePercent':round(usage[adapter['id']],1) if adapter['id'] in usage else extra.get('usagePercent'),
                         'temperatureC':extra.get('temperatureC'),'powerW':extra.get('powerW')})
        apps=running_apps(); self.fps.update_target(apps)
        with self.lock:
            self.value={'cpuPercent':cpu,'ram':ram,'battery':bat,'gpus':gpus,'cpuTemperatureC':None,
                        'sampledAt':time.time(),'apps':apps,'error':self.gpu_error}
    def start(self):
        def run():
            counters=None
            try: self.adapter_list=adapters()
            except Exception as exc: self.gpu_error=str(exc)
            try: counters=GpuCounters()
            except Exception as exc: self.gpu_error=str(exc)
            try:
                while not self.stop.is_set():
                    started=time.monotonic()
                    try: self.sample(counters)
                    except Exception as exc:
                        with self.lock: self.value['error']=str(exc)
                    if self.stop.wait(max(.05,2-(time.monotonic()-started))): break
            finally:
                if counters: counters.close()
        def temperatures():
            while not self.stop.is_set():
                found={}
                try:
                    text=self.smi('--query-gpu=name,utilization.gpu,temperature.gpu,power.draw','--format=csv,noheader,nounits')
                    def number(v):
                        try: return float(v)
                        except ValueError: return None
                    for row in csv.reader(io.StringIO(text)):
                        if len(row)>=4: found[row[0].strip()]={'usagePercent':number(row[1]),'temperatureC':number(row[2]),'powerW':number(row[3])}
                except Exception: pass
                with self.lock: self.nvidia=found
                if self.stop.wait(2): break
        threading.Thread(target=run,daemon=True).start()
        threading.Thread(target=temperatures,daemon=True).start()
