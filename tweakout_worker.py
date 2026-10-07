"""A bounded full-screen simulation: slow dark colour changes, visual corruption and audio."""
import argparse
import json
import math
from pathlib import Path
import random
import struct
import time
import tkinter as tk
import wave
import winsound
from win_support import atomic_json

PALETTE=[('#101a23','#7db9b5'),('#171423','#c0a1b5'),('#122021','#9fbb94'),('#24191a','#c4a18d')]
COLOUR_SECONDS=2.5

def make_audio(path):
    rate=22050;frames=bytearray();rng=random.Random(70)
    for n in range(int(rate*.8)):
        t=n/rate;envelope=.55+.45*math.sin(2*math.pi*6*t)**2
        sample=envelope*(.075*(1 if math.sin(2*math.pi*73*t)>0 else -1)+.025*math.sin(2*math.pi*146*t)+.012*rng.uniform(-1,1))
        frames.extend(struct.pack('<h',round(sample*32767)))
    with wave.open(str(path),'wb') as output:
        output.setnchannels(1);output.setsampwidth(2);output.setframerate(rate);output.writeframes(frames)

def main(data):
    control=data/'tweakout-control.json';result=data/'tweakout-result.json';audio=data/'tweakout-audio.wav'
    cfg=json.loads(control.read_text(encoding='utf-8'));mode_id=cfg['id'];started=time.monotonic();rng=random.Random(42)
    root=tk.Tk();root.title('HomeControl Tweakout — simulation')
    root.attributes('-fullscreen',True);root.attributes('-topmost',True);root.configure(background='#101a23')
    canvas=tk.Canvas(root,background='#101a23',highlightthickness=0);canvas.pack(fill='both',expand=True)
    root.update();width=canvas.winfo_width();height=canvas.winfo_height()
    # The full-screen program has no Cancel control or input capture. Cancellation lives on the dashboard.
    canvas.create_text(52,42,anchor='nw',text='HOMECONTROL  /  TWEAKOUT',fill='#c3cdcf',font=('Consolas',18,'bold'))
    canvas.create_text(52,85,anchor='nw',text='SIMULATED DISPLAY FAULT',fill='#94a4aa',font=('Consolas',12))
    title=canvas.create_text(53,height*.26,anchor='nw',text='FRAMEBUFFER DESYNC',fill='#7db9b5',font=('Consolas',max(22,int(width/33)),'bold'))
    shadow=canvas.create_text(57,height*.26+2,anchor='nw',text='FRAMEBUFFER DESYNC',fill='#57776e',font=('Consolas',max(22,int(width/33)),'bold'))
    canvas.tag_lower(shadow,title)
    status=canvas.create_text(54,height*.39,anchor='nw',text='',fill='#c3cdcf',font=('Consolas',15))
    logs=canvas.create_text(54,height*.5,anchor='nw',text='',fill='#7f9199',font=('Consolas',12),width=width-110)
    countdown=canvas.create_text(width-55,height-92,anchor='se',text='',fill='#c7d5d8',font=('Consolas',38,'bold'))
    canvas.create_text(54,height-62,anchor='sw',text='CANCEL FROM YOUR HOMECONTROL DASHBOARD',fill='#a4b1b6',font=('Consolas',12))
    canvas.create_text(width-55,height-40,anchor='se',text='VISUAL SIMULATION • NO DRIVER RESTART',fill='#718087',font=('Consolas',10))
    audio_error=''
    try:make_audio(audio);winsound.PlaySound(str(audio),winsound.SND_FILENAME|winsound.SND_ASYNC|winsound.SND_LOOP|winsound.SND_NODEFAULT)
    except Exception:audio_error='Buzzing audio is unavailable. Check the laptop’s audio output and volume.'
    lines=[];last_art=-1;last_colour=-1;last_log=-1
    def frame():
        nonlocal cfg,last_art,last_colour,last_log
        try:
            cfg=json.loads(control.read_text(encoding='utf-8'))
            if cfg.get('id')!=mode_id or time.time()>=cfg['deadline']:root.destroy();return
            elapsed=time.monotonic()-started;phase=int(elapsed/COLOUR_SECONDS)
            if phase!=last_colour:
                bg,accent=PALETTE[phase%len(PALETTE)];canvas.configure(background=bg);canvas.itemconfigure(title,fill=accent);last_colour=phase
            # Thin low-contrast tears update twice a second; the full-screen palette changes only every 2.5s.
            art=int(elapsed*2)
            if art!=last_art:
                canvas.delete('corruption')
                for _ in range(12):
                    y=rng.randrange(125,max(126,height-130));x=rng.randrange(0,max(1,width-160))
                    canvas.create_rectangle(x,y,min(width,x+rng.randint(30,340)),y+rng.randint(1,5),fill='#36444d',outline='',tags='corruption')
                for _ in range(5):
                    x=rng.randrange(width);y=rng.randrange(125,max(126,height-130))
                    canvas.create_text(x,y,text=f'{rng.getrandbits(32):08X}',fill='#52616b',font=('Consolas',9),tags='corruption')
                canvas.coords(shadow,57+rng.randint(-4,4),height*.26+2);last_art=art
            log=int(elapsed)
            if log!=last_log:
                messages=['DISPLAY_STREAM   simulated packet fault','FRAMEBUFFER_CRC  simulated mismatch','SYNC_RECOVERY    staging visual recovery','AUDIO_BUS        synthetic buzz loop','CONTROL_CHANNEL  dashboard available']
                lines.append(f'[{elapsed:05.1f}]  '+messages[log%len(messages)]);lines[:]=lines[-7:]
                canvas.itemconfigure(logs,text='\n'.join(lines));last_log=log
            preview=cfg.get('preview',True);remaining=max(0,math.ceil(cfg['deadline']-time.time()))
            text=('PREVIEW / CPU UNCHANGED / NO SHUTDOWN' if preview else 'CPU PERFORMANCE STATE: 1% / NORMAL SHUTDOWN QUEUED') if cfg.get('started') else 'INITIALIZING / WAITING FOR CONTROL CHANNEL'
            canvas.itemconfigure(status,text=text);canvas.itemconfigure(countdown,text=str(remaining)+'s')
            atomic_json(result,{'id':mode_id,'ready':True,'heartbeat':time.time(),'audioError':audio_error})
            root.after(200,frame)
        except Exception:root.destroy()
    try:frame();root.mainloop()
    finally:winsound.PlaySound(None,0)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--data',type=Path,required=True)
    main(parser.parse_args().data)
