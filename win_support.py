"""Small Windows helpers shared by the optional dashboard features."""
import base64
import ctypes as C
from ctypes import wintypes as W
import json
import subprocess
import uuid

HIDDEN = subprocess.CREATE_NO_WINDOW
def powershell(script, timeout=25):
    prefix = "$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'; [Console]::OutputEncoding=[Text.UTF8Encoding]::new(); "
    encoded = base64.b64encode((prefix+script).encode('utf-16-le')).decode()
    result = subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-EncodedCommand',encoded],
                            capture_output=True,timeout=timeout,creationflags=HIDDEN)
    output = result.stdout.decode('utf-8',errors='replace').strip()
    if result.returncode: raise RuntimeError(result.stderr.decode('utf-8',errors='replace').strip() or output)
    return output

def ps_config(value):
    data = base64.b64encode(json.dumps(value).encode()).decode()
    return "$cfg = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('"+data+"')) | ConvertFrom-Json; "

def atomic_json(path, value):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value),encoding='utf-8')
    temp.replace(path)

class GUID(C.Structure):
    _fields_=[('data',C.c_ubyte*16)]
    @classmethod
    def parse(cls,value):return cls.from_buffer_copy(uuid.UUID(value).bytes_le)

def com(ptr,index,result,*argtypes):
    table=C.cast(ptr,C.POINTER(C.POINTER(C.c_void_p))).contents
    return C.WINFUNCTYPE(result,C.c_void_p,*argtypes)(table[index])

def release(ptr):
    if ptr:com(ptr,2,W.ULONG)(ptr)

def check(hr,context):
    if hr < 0:raise RuntimeError(f'{context}: HRESULT 0x{hr & 0xffffffff:08X}')

def query(ptr,iid):
    out=C.c_void_p();guid=GUID.parse(iid)
    check(com(ptr,0,C.c_long,C.POINTER(GUID),C.POINTER(C.c_void_p))(ptr,C.byref(guid),C.byref(out)),'QueryInterface')
    return out
