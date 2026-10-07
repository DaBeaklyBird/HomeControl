"""Bounded Windows-style fault simulation, with layered local error sounds and buzz."""
import argparse
from array import array
import ctypes as C
from ctypes import wintypes as W
import json
import math
import os
from pathlib import Path
import random
import struct
import time
import tkinter as tk
import wave
import winsound
from win_support import atomic_json,GUID,com,check,release

RATE=22050
AUDIO_SECONDS=10
ERROR_SOUNDS=('Windows Error.wav','Windows Critical Stop.wav','Windows Exclamation.wav','Windows Hardware Fail.wav')

class WaveFormat(C.Structure):
    _pack_=2
    _fields_=[('tag',W.WORD),('channels',W.WORD),('rate',W.DWORD),('average',W.DWORD),('align',W.WORD),('bits',W.WORD),('extra',W.WORD)]

class WaveHeader(C.Structure):
    _fields_=[('data',C.c_void_p),('length',W.DWORD),('recorded',W.DWORD),('user',C.c_size_t),('flags',W.DWORD),('loops',W.DWORD),('next',C.c_void_p),('reserved',C.c_size_t)]

class WavePlayer:
    """Retain a bounded PCM buffer until the asynchronous native output is reset/closed."""
    def __init__(self,api=None):
        self.api=api or C.WinDLL('winmm');self.handle=C.c_void_p();self.header=None;self.buffer=None;self.prepared=False;self.device=None
        if api is None:
            self.api.waveOutOpen.argtypes=[C.POINTER(C.c_void_p),W.UINT,C.POINTER(WaveFormat),C.c_size_t,C.c_size_t,W.DWORD]
            for name in ('waveOutPrepareHeader','waveOutWrite','waveOutUnprepareHeader'):getattr(self.api,name).argtypes=[C.c_void_p,C.POINTER(WaveHeader),W.UINT]
            self.api.waveOutReset.argtypes=self.api.waveOutClose.argtypes=[C.c_void_p]
    def start(self,path):
        if self.handle:raise RuntimeError('Audio is already playing')
        with wave.open(str(path),'rb') as source:
            if source.getnchannels()!=1 or source.getsampwidth()!=2 or source.getframerate()!=RATE or source.getnframes()>RATE*AUDIO_SECONDS:raise ValueError('Invalid effect audio')
            pcm=source.readframes(source.getnframes())
        self.buffer=C.create_string_buffer(pcm);fmt=WaveFormat(1,1,RATE,RATE*2,2,16,0)
        try:
            # Some drivers reject WAVE_MAPPER despite having working explicit outputs.
            for device in [0xffffffff,*range(min(64,self.api.waveOutGetNumDevs()))]:
                handle=C.c_void_p()
                if self.api.waveOutOpen(C.byref(handle),device,C.byref(fmt),0,0,0)==0:
                    self.handle=handle;self.device=device;break
            if not self.handle:raise RuntimeError('No playable Windows audio output')
            self.header=WaveHeader(C.cast(self.buffer,C.c_void_p),len(pcm),0,0,12,0xffffffff,None,0)
            if self.api.waveOutPrepareHeader(self.handle,C.byref(self.header),C.sizeof(self.header)):raise RuntimeError('Cannot prepare effect audio')
            self.prepared=True
            if self.api.waveOutWrite(self.handle,C.byref(self.header),C.sizeof(self.header)):raise RuntimeError('Cannot start effect audio')
            return self.device
        except Exception:self.close();raise
    def close(self):
        if self.handle:
            if self.api.waveOutReset(self.handle):raise RuntimeError('Cannot stop effect audio')
            if self.prepared and self.api.waveOutUnprepareHeader(self.handle,C.byref(self.header),C.sizeof(self.header)):raise RuntimeError('Effect audio cleanup failed')
            self.prepared=False
            if self.api.waveOutClose(self.handle):raise RuntimeError('Cannot close effect audio output')
        self.handle=C.c_void_p();self.prepared=False;self.header=None;self.buffer=None

def audio_output():
    """Read default-speaker mute, volume and peak. Never alter volume or capture audio."""
    ole=C.WinDLL('ole32');pointers=[];initialized=False
    try:
        ole.CoInitializeEx.restype=C.c_long
        hr=ole.CoInitializeEx(None,2);initialized=hr in (0,1)
        if hr<0 and (hr & 0xffffffff)!=0x80010106:check(hr,'Audio diagnostics')
        ole.CoCreateInstance.argtypes=[C.POINTER(GUID),C.c_void_p,C.c_ulong,C.POINTER(GUID),C.POINTER(C.c_void_p)]
        ole.CoCreateInstance.restype=C.c_long
        clsid=GUID.parse('bcde0395-e52f-467c-8e3d-c4579291692e');iid=GUID.parse('a95664d2-9614-4f35-a746-de8db63617e6')
        enumerator=C.c_void_p();check(ole.CoCreateInstance(C.byref(clsid),None,23,C.byref(iid),C.byref(enumerator)),'Audio output');pointers.append(enumerator)
        device=C.c_void_p();check(com(enumerator,4,C.c_long,C.c_int,C.c_int,C.POINTER(C.c_void_p))(enumerator,0,0,C.byref(device)),'Default speakers');pointers.append(device)
        def activate(value):
            guid=GUID.parse(value);out=C.c_void_p()
            check(com(device,3,C.c_long,C.POINTER(GUID),C.c_ulong,C.c_void_p,C.POINTER(C.c_void_p))(device,C.byref(guid),23,None,C.byref(out)),'Audio information');pointers.append(out);return out
        volume=activate('5cdf2c82-841e-4546-9722-0cf74078229a');level=C.c_float();muted=C.c_int()
        check(com(volume,9,C.c_long,C.POINTER(C.c_float))(volume,C.byref(level)),'Speaker volume')
        check(com(volume,15,C.c_long,C.POINTER(C.c_int))(volume,C.byref(muted)),'Speaker mute')
        meter=activate('c02216f6-8c67-4b5b-9d00-d008e73e0064');peak=C.c_float()
        check(com(meter,3,C.c_long,C.POINTER(C.c_float))(meter,C.byref(peak)),'Speaker peak')
        return {'available':True,'muted':bool(muted.value),'volume':round(level.value*100),'peak':round(peak.value,4)}
    except Exception as exc:return {'available':False,'error':str(exc)}
    finally:
        for ptr in reversed(pointers):release(ptr)
        if initialized:ole.CoUninitialize()

def read_sound(path,rate=RATE):
    """Read only bounded PCM from local Windows Media; return mono samples at our rate."""
    with wave.open(str(path),'rb') as source:
        channels=source.getnchannels();width=source.getsampwidth();hz=source.getframerate()
        if width!=2 or channels not in (1,2) or not 8000<=hz<=192000:raise ValueError('Unsupported Windows sound format')
        pcm=array('h');pcm.frombytes(source.readframes(min(source.getnframes(),hz*3)))
    mono=[sum(pcm[n:n+channels])/channels/32768 for n in range(0,len(pcm)-channels+1,channels)]
    return [mono[min(len(mono)-1,int(n*hz/rate))] for n in range(int(len(mono)*rate/hz))] if mono else []

def make_audio(path,media=None):
    media=Path(media) if media is not None else Path(os.environ.get('SystemRoot',r'C:\Windows'))/'Media'
    rng=random.Random(70);samples=[]
    for n in range(RATE*AUDIO_SECONDS):
        t=n/RATE
        envelope=min(1,t/.06,(AUDIO_SECONDS-t)/.06)*(.48+.32*math.sin(2*math.pi*4*t)**2)
        gate=.32 if 2.1<t%3.4<2.45 else 1
        samples.append(envelope*gate*(.17*math.tanh(3*math.sin(2*math.pi*88*t))+.04*math.sin(2*math.pi*176*t)+.008*rng.uniform(-1,1)))
    loaded=[]
    for index,name in enumerate(ERROR_SOUNDS):
        try:cue=read_sound(media/name)
        except (OSError,ValueError,wave.Error,EOFError):cue=[]
        if cue:loaded.append(name)
        else:
            cue=[.3*math.sin(2*math.pi*(740 if n/RATE<.15 else 554)*n/RATE)*math.sin(math.pi*n/(RATE*.38))**2 for n in range(int(RATE*.38))]
        start=int((.15+index*2.3)*RATE)
        peak=max((abs(v) for v in cue),default=1) or 1
        for j,value in enumerate(cue[:len(samples)-start]):samples[start+j]+=.42*value/peak
    frames=b''.join(struct.pack('<h',round(max(-.75,min(.75,v))*32767)) for v in samples)
    with wave.open(str(path),'wb') as output:
        output.setnchannels(1);output.setsampwidth(2);output.setframerate(RATE);output.writeframes(frames)
    return loaded

class FaultDisplay:
    """Canvas decoration only: no countdown, Cancel control or keyboard interception."""
    def __init__(self,canvas,width,height):
        self.c=canvas;self.w=width;self.h=height;self.scale=max(.65,min(1.5,width/1600));self.rng=random.Random(42);self.last=None
    def text(self,x,y,text,size=12,colour='#161616',**kw):
        return self.c.create_text(x,y,text=text,font=('Segoe UI',max(9,round(size*self.scale))),fill=colour,anchor='nw',**kw)
    def dialog(self,x,y,title,message,code):
        c=self.c;s=self.scale;w=round(600*s);h=round(176*s)
        c.create_rectangle(x+6,y+7,x+w+6,y+h+7,fill='#17212e',outline='')
        c.create_rectangle(x,y,x+w,y+h,fill='#f3f3f3',outline='#9fa4aa')
        c.create_rectangle(x,y,x+w,y+35*s,fill='#fff',outline='')
        self.text(x+13*s,y+8*s,title,12)
        self.text(x+w-28*s,y+7*s,'×',16)
        c.create_oval(x+22*s,y+54*s,x+54*s,y+86*s,fill='#c83f42',outline='')
        self.text(x+30*s,y+50*s,'×',23,'white')
        self.text(x+70*s,y+53*s,message,12,width=w-90*s)
        self.text(x+70*s,y+101*s,code,10,'#676767')
        c.create_rectangle(x+w-98*s,y+h-40*s,x+w-17*s,y+h-13*s,fill='#e7e7e7',outline='#b0b0b0')
        self.text(x+w-75*s,y+h-36*s,'Close',11)
    def draw(self,elapsed):
        c=self.c;w=self.w;h=self.h;s=self.scale
        phase=0 if elapsed<4 else 1 if elapsed<8 else 2
        step=int(elapsed/.9)
        key=(phase,step if phase<2 else 0)
        if key==self.last:return
        self.last=key;c.delete('all')
        if phase<2:
            c.configure(background='#20334c' if phase==0 else '#172b40')
            c.create_rectangle(0,h-48*s,w,h,fill='#1b2534',outline='')
            self.text(w*.43,h-35*s,'⊞      Search      ▣      ▤',14,'#d5dbe1')
            self.dialog(w*.2,h*.18,'Desktop Window Manager',"The display stopped responding. Windows is attempting to recover the current desktop session.",'Display recovery • 0x887A0005')
            self.dialog(w*.27,h*.34,'Application Error',"An unexpected rendering error occurred. The application was unable to complete the requested operation.",'Exception code: 0xc0000005')
            if phase==1:
                self.dialog(w*.34,h*.5,'explorer.exe — System Warning',"A device attached to the system is not functioning. The graphics session is being recovered.",'Device response timeout • 0x00000102')
            for _ in range(20):
                x=self.rng.randrange(w);y=self.rng.randrange(max(1,int(h-60*s)))
                c.create_rectangle(x,y,min(w,x+self.rng.randint(20,180)),y+self.rng.randint(1,6),fill=self.rng.choice(('#526676','#283c4e','#879299')),outline='')
        else:
            c.configure(background='#102b48')
            self.text(w*.16,h*.17,':(',64,'#e2ebf4')
            self.text(w*.16,h*.34,"Your device ran into a display problem.\nThe current session could not be recovered.",24,'#e2ebf4',width=w*.67)
            self.text(w*.16,h*.57,'Stop code: VIDEO_TDR_FAILURE\nWhat failed: display rendering session',14,'#b7c9da')
        self.text(20,h-23,'HomeControl • visual effect',10,'#aab7c6')

def main(data):
    control=data/'tweakout-control.json';result=data/'tweakout-result.json';audio=data/'tweakout-audio.wav'
    cfg=json.loads(control.read_text(encoding='utf-8'));mode_id=cfg['id'];started=time.monotonic()
    root=tk.Tk();root.title('HomeControl Tweakout — visual effects')
    root.attributes('-fullscreen',True);root.attributes('-topmost',True)
    canvas=tk.Canvas(root,background='#20334c',highlightthickness=0);canvas.pack(fill='both',expand=True)
    root.update();display=FaultDisplay(canvas,canvas.winfo_width(),canvas.winfo_height())
    audio_error='';loaded=[];output=audio_output();last_audio=-10;player=WavePlayer()
    try:
        loaded=make_audio(audio)
        player.start(audio)
    except Exception:
        try:winsound.MessageBeep(winsound.MB_ICONHAND)
        except Exception:pass
        audio_error='Effect audio could not start. Check the computer’s output device and volume.'
    def frame():
        nonlocal output,last_audio
        try:
            cfg=json.loads(control.read_text(encoding='utf-8'))
            if cfg.get('id')!=mode_id or time.time()>=cfg['deadline']:root.destroy();return
            display.draw(time.monotonic()-started)
            if time.monotonic()-last_audio>=2:output=audio_output();last_audio=time.monotonic()
            warning='Speakers are muted or at zero volume. Unmute the selected computer to hear the effects.' if output.get('muted') or output.get('volume')==0 else ''
            atomic_json(result,{'id':mode_id,'ready':True,'heartbeat':time.time(),'audioError':audio_error or warning,'sounds':loaded,'audioOutput':{**output,'fallbackDevice':player.device if player.device!=0xffffffff else None}})
            root.after(200,frame)
        except Exception:root.destroy()
    try:frame();root.mainloop()
    finally:player.close()

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--data',type=Path,required=True)
    main(parser.parse_args().data)
