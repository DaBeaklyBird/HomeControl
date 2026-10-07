"""Optional visible D3D11 acceptance fixture; run manually on Windows."""
import ctypes as C
from ctypes import wintypes as W
from collections import deque
import json,os,sys,threading,time,urllib.request
from pathlib import Path
import tkinter as tk
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from gpu_native import Compute,adapters
from win_support import com,query,check,GUID,release

class SwapDesc(C.Structure):
    _fields_=[(n,W.UINT) for n in ['width','height','format','stereo','sampleCount','sampleQuality','usage','buffers','scaling','effect','alpha','flags']]

def run(seconds=8):
    data=Path((ROOT/'data-location.txt').read_text().strip()); key=(data/'key.txt').read_text().strip()
    def api(path,body=None):
        request=urllib.request.Request('http://127.0.0.1:8765'+path,data=json.dumps(body).encode() if body is not None else None,
                                       headers={'X-Access-Key':key,'Content-Type':'application/json'})
        with urllib.request.urlopen(request,timeout=5) as response:return json.load(response)
    window=tk.Tk(); window.title('HomeControl · FPS test'); window.geometry('420x240')
    label=tk.Label(window,text='Direct3D 11 reference · 60 FPS',bg='#101724',fg='white');label.pack();window.update()
    user=C.WinDLL('user32');user.GetAncestor.argtypes=[W.HWND,W.UINT];user.GetAncestor.restype=W.HWND
    hwnd=user.GetAncestor(window.winfo_id(),2)
    gpu=Compute(adapters()[0]['id']); factory=None; swap=C.c_void_p(); texture=C.c_void_p(); target=C.c_void_p()
    reference=deque(); samples=[]; done=threading.Event()
    try:
        api_dxgi=C.WinDLL('dxgi'); api_dxgi.CreateDXGIFactory1.argtypes=[C.POINTER(GUID),C.POINTER(C.c_void_p)]
        api_dxgi.CreateDXGIFactory1.restype=C.c_long; base=C.c_void_p(); iid=GUID.parse('770aae78-f26f-4dba-a829-253c83d1b387')
        check(api_dxgi.CreateDXGIFactory1(C.byref(iid),C.byref(base)),'Factory')
        try: factory=query(base,'50c83a1c-e072-4c48-87b0-3630fa36a6d0')
        finally: release(base)
        desc=SwapDesc(420,240,28,0,1,0,0x20,2,0,4,3,0)
        check(com(factory,15,C.c_long,C.c_void_p,W.HWND,C.POINTER(SwapDesc),C.c_void_p,C.c_void_p,C.POINTER(C.c_void_p))(factory,gpu.device,hwnd,C.byref(desc),None,None,C.byref(swap)),'Swap chain')
        iid=GUID.parse('6f15aaf2-d208-4e89-9ab4-489535d34f9c')
        check(com(swap,9,C.c_long,W.UINT,C.POINTER(GUID),C.POINTER(C.c_void_p))(swap,0,C.byref(iid),C.byref(texture)),'Backbuffer')
        check(com(gpu.device,9,C.c_long,C.c_void_p,C.c_void_p,C.POINTER(C.c_void_p))(gpu.device,texture,None,C.byref(target)),'Render target')
        api('/api/fps/settings',{'enabled':True,'pid':os.getpid()})
        def sample():
            while not done.wait(2):
                reading=api('/api/fps'); samples.append({'referenceFps':round((len(reference)-1)/(reference[-1]-reference[0]),1) if len(reference)>1 else None,'appFps':reading['fps'],'state':reading['state']})
        thread=threading.Thread(target=sample,daemon=True);thread.start()
        start=time.monotonic(); next_frame=start; color=(C.c_float*4)(.08,.17,.24,1)
        while time.monotonic()-start<seconds:
            now=time.monotonic()
            if now<next_frame: time.sleep(min(.002,next_frame-now));continue
            window.update()
            com(gpu.context,50,None,C.c_void_p,C.POINTER(C.c_float))(gpu.context,target,color)
            check(com(swap,8,C.c_long,W.UINT,W.UINT)(swap,0,0),'Present')
            reference.append(time.monotonic())
            while reference and reference[0]<now-2:reference.popleft()
            next_frame+=1/60
            if now-next_frame>.1: next_frame=now+1/60
        done.set();thread.join(timeout=6)
        (ROOT/'work'/'render-acceptance-result.json').write_text(json.dumps(samples,indent=2))
        print(json.dumps(samples,indent=2))
    finally:
        done.set();api('/api/fps/settings',{'enabled':True,'pid':None})
        release(target);release(texture);release(swap);release(factory);gpu.close();window.destroy()

if __name__=='__main__':run(min(30,max(5,int(sys.argv[1]))) if len(sys.argv)>1 else 8)
