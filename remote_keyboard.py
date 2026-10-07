"""One-shot input to the interactive Windows desktop; no held keys."""
import ctypes as C
from ctypes import wintypes as W
import threading

class KeyboardInput(C.Structure):
    _fields_=[('vk',W.WORD),('scan',W.WORD),('flags',W.DWORD),('time',W.DWORD),('extra',C.c_size_t)]
class MouseInput(C.Structure):
    _fields_=[('dx',W.LONG),('dy',W.LONG),('data',W.DWORD),('flags',W.DWORD),('time',W.DWORD),('extra',C.c_size_t)]
class InputUnion(C.Union):
    _fields_=[('keyboard',KeyboardInput),('mouse',MouseInput)]
class Input(C.Structure):
    _anonymous_=('data',)
    _fields_=[('type',W.DWORD),('data',InputUnion)]
KEYS={'Enter':13,'Tab':9,'Backspace':8,'Escape':27,'Left':37,'Up':38,'Right':39,'Down':40,'Delete':46,'Space':32}
LOCK=threading.Lock()
def send(body):
    kind=body.get('kind')
    if kind=='text':
        text=body.get('text')
        if not isinstance(text,str) or not 1<=len(text)<=1000:raise ValueError('Send 1–1000 characters at a time.')
        if any(ord(c)<32 and c not in '\n\t' for c in text):raise ValueError('Unsupported control character.')
        raw=text.encode('utf-16-le'); events=[]
        for i in range(0,len(raw),2):
            unit=int.from_bytes(raw[i:i+2],'little')
            events.extend([Input(type=1,keyboard=KeyboardInput(scan=unit,flags=4)),Input(type=1,keyboard=KeyboardInput(scan=unit,flags=6))])
    elif kind=='key':
        key=body.get('key')
        if key not in KEYS:raise ValueError('Unsupported key.')
        events=[Input(type=1,keyboard=KeyboardInput(vk=KEYS[key])),Input(type=1,keyboard=KeyboardInput(vk=KEYS[key],flags=2))]
    else:raise ValueError('Choose text or key.')
    with LOCK:
        api=C.WinDLL('user32',use_last_error=True)
        api.SendInput.argtypes=[W.UINT,C.POINTER(Input),C.c_int];api.SendInput.restype=W.UINT
        inputs=(Input*len(events))(*events)
        sent=api.SendInput(len(events),inputs,C.sizeof(Input))
        if sent!=len(events):raise RuntimeError('Windows blocked keyboard input. Unlock the PC and focus an application first.')
    return {'sent':sent//2}
