"""WinDivert's signed x64 library. Loading the DLL alone does not load its driver."""
import ctypes as C
from ctypes import wintypes as W
import hashlib
import math

CHECKSUMS={
    'WinDivert.dll':'c1e060ee19444a259b2162f8af0f3fe8c4428a1c6f694dce20de194ac8d7d9a2',
    'WinDivert64.sys':'8da085332782708d8767bcace5327a6ec7283c17cfb85e40b03cd2323a90ddc2',
}

def verify_vendor(root):
    if C.sizeof(C.c_void_p)!=8: raise RuntimeError('Internet limiting requires 64-bit Python on Windows x64.')
    directory=root/'vendor'/'windivert'
    for filename,digest in CHECKSUMS.items():
        if not (directory/filename).is_file(): raise RuntimeError('WinDivert files are missing. Copy the entire vendor folder.')
        if hashlib.sha256((directory/filename).read_bytes()).hexdigest()!=digest:
            raise RuntimeError('WinDivert checksum mismatch: '+filename)
    return directory

def validate_rate(value):
    if value is None: return None
    if type(value) not in (int,float) or not math.isfinite(value) or not .1<=value<=1000:
        raise ValueError('Choose 0.1–1000 Mbps, or Unlimited.')
    if round(value,1)!=value: raise ValueError('Use Mbps in steps of 0.1.')
    return float(value)

class Pace:
    """Serialize one direction's bytes with at most 10 ms of idle/burst credit."""
    def __init__(self,mbps,clock): self.clock=clock; self.set_rate(mbps)
    def set_rate(self,mbps):
        self.bytes_per_second=validate_rate(mbps)*1_000_000/8
        self.deadline=self.clock()
    def delay(self,size):
        now=self.clock()
        self.deadline=max(now-.01,self.deadline)+size/self.bytes_per_second
        return max(0,self.deadline-now)

def packet_filter(direction,port=8765):
    # RFC1918, loopback, link-local, multicast, ULA and link-local IPv6 bypass
    # the shaper in the kernel; the dashboard does not depend on its worker.
    if direction not in ('inbound','outbound'): raise ValueError('Invalid direction')
    endpoint='SrcAddr' if direction=='inbound' else 'DstAddr'
    v4='ip.'+endpoint; v6='ipv6.'+endpoint
    public4=' and '.join(f'({v4} < {low} or {v4} > {high})' for low,high in [
        ('0.0.0.0','0.255.255.255'),('10.0.0.0','10.255.255.255'),
        ('127.0.0.0','127.255.255.255'),('169.254.0.0','169.254.255.255'),
        ('172.16.0.0','172.31.255.255'),('192.168.0.0','192.168.255.255'),
        ('224.0.0.0','255.255.255.255')])
    public=f'((ip and {public4}) or (ipv6 and {v6} > ::1 and {v6} < fc00::))'
    return f'{direction} and not loopback and not impostor and (tcp or udp) and (not tcp or (tcp.SrcPort != {port} and tcp.DstPort != {port})) and {public}'

class Address(C.Structure):
    _fields_=[('timestamp',C.c_int64),('flags',C.c_uint32),('reserved',C.c_uint32),('data',C.c_uint8*64)]
assert C.sizeof(Address)==80

class Divert:
    def __init__(self,root):
        directory=verify_vendor(root)
        self.api=C.WinDLL(str(directory/'WinDivert.dll'),use_last_error=True)
        self.api.WinDivertOpen.argtypes=[C.c_char_p,C.c_int,C.c_int16,C.c_uint64]; self.api.WinDivertOpen.restype=W.HANDLE
        self.api.WinDivertRecv.argtypes=[W.HANDLE,C.c_void_p,W.UINT,C.POINTER(W.UINT),C.POINTER(Address)]
        self.api.WinDivertSend.argtypes=[W.HANDLE,C.c_void_p,W.UINT,C.POINTER(W.UINT),C.POINTER(Address)]
        self.api.WinDivertClose.argtypes=[W.HANDLE]
        self.api.WinDivertShutdown.argtypes=[W.HANDLE,C.c_int]
        self.api.WinDivertSetParam.argtypes=[W.HANDLE,C.c_int,C.c_uint64]
        self.api.WinDivertHelperCalcChecksums.argtypes=[C.c_void_p,W.UINT,C.POINTER(Address),C.c_uint64]
        self.api.WinDivertHelperCompileFilter.argtypes=[C.c_char_p,C.c_int,C.c_void_p,W.UINT,C.POINTER(C.c_char_p),C.POINTER(W.UINT)]
        self.api.WinDivertHelperEvalFilter.argtypes=[C.c_char_p,C.c_void_p,W.UINT,C.POINTER(Address)]
    def check_filter(self,text):
        error=C.c_char_p();position=W.UINT()
        if not self.api.WinDivertHelperCompileFilter(text.encode(),0,None,0,C.byref(error),C.byref(position)):
            raise RuntimeError('Invalid packet filter: '+(error.value or b'').decode()+f' at {position.value}')
    def open(self,text):
        self.check_filter(text)
        handle=self.api.WinDivertOpen(text.encode(),0,0,0)
        if handle in (None,C.c_void_p(-1).value):
            code=C.get_last_error()
            detail={5:'Run HomeControl through its elevated startup task.',577:'Windows rejected the driver signature.',
                    654:'Another incompatible WinDivert version is running.',1275:'Windows or security software blocked the driver. Security settings were not changed.'}
            raise RuntimeError(f'Internet limiter could not start (Windows {code}). '+detail.get(code,str(C.WinError(code))))
        try:
            for param,value in [(0,2048),(1,1000),(2,2*1024*1024)]:
                if not self.api.WinDivertSetParam(handle,param,value): raise C.WinError(C.get_last_error())
        except Exception:
            self.close(handle);raise
        return handle
    def receive(self,handle):
        packet=C.create_string_buffer(65535);size=W.UINT();address=Address()
        if not self.api.WinDivertRecv(handle,packet,len(packet),C.byref(size),C.byref(address)):
            code=C.get_last_error()
            if code==232:return None
            raise C.WinError(code)
        return packet,size.value,address
    def send(self,handle,packet,size,address):
        # NIC offloading can leave checksums incomplete at the capture point.
        if not self.api.WinDivertHelperCalcChecksums(packet,size,C.byref(address),0):
            raise RuntimeError('Could not calculate network packet checksums')
        sent=W.UINT()
        if not self.api.WinDivertSend(handle,packet,size,C.byref(sent),C.byref(address)):
            raise C.WinError(C.get_last_error())
        if sent.value!=size:raise RuntimeError('Network packet reinjection was incomplete')
    def shutdown(self,handle):self.api.WinDivertShutdown(handle,1)
    def close(self,handle):self.api.WinDivertClose(handle)
