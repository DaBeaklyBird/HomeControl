"""Direct3D 11 hardware-only compute worker; no driver changes or injection."""
import ctypes as C
from ctypes import wintypes as W
from win_support import GUID,com,check,release,query

class LUID(C.Structure):_fields_=[('low',W.DWORD),('high',W.LONG)]
class Desc(C.Structure):
    _fields_=[('name',W.WCHAR*128),('vendor',W.UINT),('device',W.UINT),('subsystem',W.UINT),('revision',W.UINT),
              ('videoMemory',C.c_size_t),('systemMemory',C.c_size_t),('sharedMemory',C.c_size_t),('luid',LUID),('flags',W.UINT)]

def adapters(keep=False):
    dxgi=C.WinDLL('dxgi');factory=C.c_void_p();iid=GUID.parse('770aae78-f26f-4dba-a829-253c83d1b387')
    dxgi.CreateDXGIFactory1.argtypes=[C.POINTER(GUID),C.POINTER(C.c_void_p)]
    dxgi.CreateDXGIFactory1.restype=C.c_long
    check(dxgi.CreateDXGIFactory1(C.byref(iid),C.byref(factory)),'CreateDXGIFactory1')
    found=[]
    try:
        for index in range(16):
            ptr=C.c_void_p()
            hr=com(factory,12,C.c_long,W.UINT,C.POINTER(C.c_void_p))(factory,index,C.byref(ptr))
            if hr & 0xffffffff == 0x887a0002:break
            check(hr,'EnumAdapters1')
            desc=Desc()
            try:
                check(com(ptr,10,C.c_long,C.POINTER(Desc))(ptr,C.byref(desc)),'GetDesc1')
                if not desc.flags & 2:
                    found.append({'id':f'{desc.luid.high & 0xffffffff:08x}:{desc.luid.low:08x}', 'index':index,
                        'name':desc.name,'vendorId':desc.vendor,'dedicatedBytes':desc.videoMemory,
                        **({'ptr':ptr} if keep else {})})
                    if keep:ptr=None
            finally:release(ptr)
    finally:release(factory)
    return found

class BufferDesc(C.Structure):_fields_=[(n,W.UINT) for n in ['bytes','usage','bind','cpuAccess','misc','stride']]
class Initial(C.Structure):_fields_=[('data',C.c_void_p),('pitch',W.UINT),('slice',W.UINT)]
class UavDesc(C.Structure):_fields_=[(n,W.UINT) for n in ['format','dimension','first','elements','flags']]
class QueryDesc(C.Structure):_fields_=[('query',W.UINT),('misc',W.UINT)]

class Compute:
    def __init__(self,adapter_id):
        self.resources=[];self.priorityAccepted=False;self.priorityError='';self.device=C.c_void_p();self.context=C.c_void_p()
        choices=adapters(keep=True)
        try:
            selected=next((a for a in choices if a['id']==adapter_id),None)
            if not selected:raise ValueError('Selected hardware GPU is no longer present')
            api=C.WinDLL('d3d11')
            api.D3D11CreateDevice.argtypes=[C.c_void_p,W.UINT,C.c_void_p,W.UINT,C.POINTER(W.UINT),W.UINT,W.UINT,C.POINTER(C.c_void_p),C.POINTER(W.UINT),C.POINTER(C.c_void_p)]
            api.D3D11CreateDevice.restype=C.c_long
            feature=W.UINT(0xb000);actual=W.UINT()
            check(api.D3D11CreateDevice(selected['ptr'],0,None,0,C.byref(feature),1,7,C.byref(self.device),C.byref(actual),C.byref(self.context)),'D3D11 hardware device')
            self.resources.extend([self.device,self.context])
            dxgi_device=None
            try:
                dxgi_device=query(self.device,'54ec77fa-1377-44e6-8c32-88fd5f44c84c')
                check(com(dxgi_device,10,C.c_long,C.c_int)(dxgi_device,1),'GPU relative priority +1')
                current=C.c_int()
                check(com(dxgi_device,11,C.c_long,C.POINTER(C.c_int))(dxgi_device,C.byref(current)),'GPU priority readback')
                self.priorityAccepted=current.value==1
            except Exception as exc:self.priorityError=str(exc)
            finally:release(dxgi_device)
            source=b'''RWStructuredBuffer<float> output : register(u0);
            [numthreads(64,1,1)] void main(uint3 tid:SV_DispatchThreadID) {
              float x=output[tid.x]+0.01;
              [loop] for(uint i=0;i<256;i++) { x=frac(x*1.6180339+0.0137); x=x*x+0.001; }
              output[tid.x]=x;
            }'''
            compiler=C.WinDLL('d3dcompiler_47')
            compiler.D3DCompile.argtypes=[C.c_void_p,C.c_size_t,C.c_char_p,C.c_void_p,C.c_void_p,C.c_char_p,C.c_char_p,W.UINT,W.UINT,C.POINTER(C.c_void_p),C.POINTER(C.c_void_p)]
            compiler.D3DCompile.restype=C.c_long
            blob=C.c_void_p();errors=C.c_void_p()
            try:
                check(compiler.D3DCompile(source,len(source),None,None,None,b'main',b'cs_5_0',0,0,C.byref(blob),C.byref(errors)),'Compute shader compilation')
                code=com(blob,3,C.c_void_p)(blob);size=com(blob,4,C.c_size_t)(blob)
                shader=C.c_void_p()
                check(com(self.device,18,C.c_long,C.c_void_p,C.c_size_t,C.c_void_p,C.POINTER(C.c_void_p))(self.device,code,size,None,C.byref(shader)),'CreateComputeShader')
                self.resources.append(shader)
            finally:release(blob);release(errors)
            desc=BufferDesc(4096*4,0,0x80,0,0x40,4);seed=(C.c_float*4096)(*[0.1]*4096);initial=Initial(C.cast(seed,C.c_void_p),0,0);buffer=C.c_void_p()
            check(com(self.device,3,C.c_long,C.POINTER(BufferDesc),C.POINTER(Initial),C.POINTER(C.c_void_p))(self.device,C.byref(desc),C.byref(initial),C.byref(buffer)),'CreateBuffer')
            self.resources.append(buffer)
            uav=C.c_void_p();udesc=UavDesc(0,1,0,4096,0)
            check(com(self.device,8,C.c_long,C.c_void_p,C.POINTER(UavDesc),C.POINTER(C.c_void_p))(self.device,buffer,C.byref(udesc),C.byref(uav)),'CreateUnorderedAccessView')
            self.resources.append(uav)
            self.event=C.c_void_p();qdesc=QueryDesc(0,0)
            check(com(self.device,24,C.c_long,C.POINTER(QueryDesc),C.POINTER(C.c_void_p))(self.device,C.byref(qdesc),C.byref(self.event)),'CreateQuery')
            self.resources.append(self.event)
            com(self.context,69,None,C.c_void_p,C.c_void_p,W.UINT)(self.context,shader,None,0)
            views=(C.c_void_p*1)(uav.value)
            com(self.context,68,None,W.UINT,W.UINT,C.POINTER(C.c_void_p),C.c_void_p)(self.context,0,1,views,None)
        except Exception:
            self.close();raise
        finally:
            for item in choices:release(item['ptr'])
    def dispatch(self,deadline):
        import time
        com(self.context,41,None,W.UINT,W.UINT,W.UINT)(self.context,64,1,1)
        com(self.context,28,None,C.c_void_p)(self.context,self.event)
        # Flush once, then poll without queuing additional work.
        com(self.context,111,None)(self.context)
        done=W.BOOL()
        while True:
            hr=com(self.context,29,C.c_long,C.c_void_p,C.c_void_p,W.UINT,W.UINT)(self.context,self.event,C.byref(done),C.sizeof(done),1)
            check(hr,'GPU completion')
            if hr==0 and done.value:return
            if time.monotonic()>deadline:raise RuntimeError('GPU dispatch exceeded its 250 ms deadline')
            time.sleep(0.001)
    def close(self):
        for ptr in reversed(self.resources):release(ptr)
        self.resources=[]
