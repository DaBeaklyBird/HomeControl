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

def atomic_json(path, value, private=False):
    temp = path.with_suffix('.tmp')
    if private:
        # Set a private ACL before writing credentials, including on an existing temp file.
        temp.touch(exist_ok=True)
        powershell(ps_config({'path':str(temp.resolve())})+r'''
        $acl=[Security.AccessControl.FileSecurity]::new()
        $acl.SetAccessRuleProtection($true,$false)
        $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.WindowsIdentity]::GetCurrent().User,'FullControl','Allow'))
        $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new('S-1-5-18'),'FullControl','Allow'))
        [IO.File]::SetAccessControl($cfg.path,$acl)
        ''')
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

def cpu_state():
    """Read the active Windows power plan and AC/DC maximum processor states."""
    api=C.WinDLL('powrprof');kernel=C.WinDLL('kernel32')
    ptr=C.POINTER(GUID)()
    if api.PowerGetActiveScheme(None,C.byref(ptr)):raise RuntimeError('Cannot read active power plan')
    try:
        scheme=str(uuid.UUID(bytes_le=bytes(ptr.contents)))
        sub=GUID.parse('54533251-82be-4824-96c1-47b60b740d00')
        setting=GUID.parse('bc5038f7-23e0-4960-96da-33abaf5935ec')
        values=[]
        for name in ('PowerReadACValueIndex','PowerReadDCValueIndex'):
            value=W.DWORD()
            if getattr(api,name)(None,ptr,C.byref(sub),C.byref(setting),C.byref(value)):
                raise RuntimeError('Maximum processor state is unavailable')
            values.append(value.value)
        return scheme,values
    finally:
        kernel.LocalFree.argtypes=[C.c_void_p];kernel.LocalFree(ptr)
