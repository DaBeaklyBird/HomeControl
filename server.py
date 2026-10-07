import ctypes, datetime, json, os, secrets, socket, sqlite3, subprocess, threading, time, shutil, csv, io, math
from ctypes import wintypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from contextlib import contextmanager,nullcontext
from version import VERSION

ROOT = Path(__file__).parent
DATA = Path(os.environ.get('LOCALAPPDATA', str(ROOT))) / 'HomeControl'
LOCATION = ROOT / 'data-location.txt'
if LOCATION.exists(): DATA = Path(LOCATION.read_text(encoding='utf-8-sig').strip())
if os.environ.get('HOMECONTROL_DATA'): DATA = Path(os.environ['HOMECONTROL_DATA'])
DATA.mkdir(parents=True, exist_ok=True)
from app_limits import Limits
from remote_terminal import Terminal
from remote_keyboard import send as send_keyboard
from fps_monitor import FpsMonitor
from telemetry import Metrics
from power_controls import PowerActions
from device_controls import Devices
from network_limit import NetworkLimit
from laptop_controls import Laptops
from tweakout import Tweakout
from gradual_lag import GradualLag
from app_launcher import AppLauncher
from win_support import cpu_state
TOKEN_FILE = DATA / 'key.txt'
if not TOKEN_FILE.exists(): TOKEN_FILE.write_text(secrets.token_urlsafe(24))
TOKEN = TOKEN_FILE.read_text().strip()
DB = DATA / 'usage.sqlite'
lock = threading.Lock()
power_lock = threading.Lock()
control_lock = threading.RLock()
active = 'Starting'
error = ''
stop = threading.Event()

@contextmanager
def connect():
    db = sqlite3.connect(DB, timeout=10)
    try:
        with db: yield db
    finally: db.close()

with connect() as db:
    db.execute('CREATE TABLE IF NOT EXISTS usage (day TEXT, app TEXT, seconds REAL, PRIMARY KEY(day, app))')
limits = Limits(DATA, connect)
terminal = Terminal(ROOT)
terminal_enabled = None  # Optional override for tests; normal operation checks the local switch live.
def terminal_is_enabled():
    return terminal_enabled if terminal_enabled is not None else (DATA/'terminal-enabled.txt').exists()
limit_error = ''

def enforce_limits():
    global limit_error
    while not stop.wait(5):
        try:
            with control_lock:
                if not tweakout.blocked() and not gradual_lag.blocked():limits.tick()
                limit_error = ''
        except Exception as exc: limit_error = str(exc)

user = ctypes.WinDLL('user32', use_last_error=True)
kernel = ctypes.WinDLL('kernel32', use_last_error=True)
user.GetForegroundWindow.restype = wintypes.HWND
kernel.OpenProcess.restype = wintypes.HANDLE
kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
kernel.CloseHandle.argtypes = [wintypes.HANDLE]
user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]

class LastInput(ctypes.Structure):
    _fields_ = [('cbSize', wintypes.UINT), ('dwTime', wintypes.DWORD)]

def foreground():
    info = LastInput(ctypes.sizeof(LastInput), 0)
    if not user.GetLastInputInfo(ctypes.byref(info)): return 'Unavailable', False
    idle = ((kernel.GetTickCount() & 0xffffffff) - info.dwTime) & 0xffffffff
    if idle > 60000: return 'Idle', False
    pid = wintypes.DWORD()
    user.GetWindowThreadProcessId(user.GetForegroundWindow(), ctypes.byref(pid))
    handle = kernel.OpenProcess(0x1000, False, pid.value)
    if not handle: return 'Unavailable', False
    try:
        buf = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(buf))
        if kernel.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return Path(buf.value).name, True
        return 'Unavailable', False
    finally: kernel.CloseHandle(handle)

def track():
    global active, error
    last = time.monotonic()
    previous, count = foreground()
    while not stop.wait(2):
        now = time.monotonic()
        elapsed = now-last
        try:
            current, valid = foreground()
            if count and valid and current == previous and elapsed < 5:
                with connect() as db:
                    db.execute('INSERT INTO usage VALUES(?,?,?) ON CONFLICT(day,app) DO UPDATE SET seconds=seconds+excluded.seconds', (datetime.date.today().isoformat(), previous, elapsed))
            active = current
            previous, count = current, valid
        except Exception as exc: error = str(exc)
        last = now

def command(*args):
    result = subprocess.run(['powercfg', *args], capture_output=True, text=True, timeout=15, creationflags=0x08000000)
    if result.returncode: raise RuntimeError(result.stderr.strip() or result.stdout.strip() or 'Windows rejected this power setting.')
    return result.stdout

def power_state():
    return cpu_state()

BACKUP = DATA / 'original-power.json'
GPU_BACKUP = DATA / 'original-gpu.json'
TIMER_BACKUP = DATA / 'timer-original-power.json'
gpu_lock = threading.Lock()

def timer_system_cap(percent):
    with power_lock:
        if percent is None:
            if not TIMER_BACKUP.exists(): return
            saved = json.loads(TIMER_BACKUP.read_text())
            for flag, amount in zip(['/setacvalueindex','/setdcvalueindex'],saved['values']):
                command(flag,saved['scheme'],'SUB_PROCESSOR','PROCTHROTTLEMAX',str(amount))
            command('/setactive',saved['scheme'])
            TIMER_BACKUP.unlink()
        else:
            scheme, values = power_state()
            if not TIMER_BACKUP.exists(): TIMER_BACKUP.write_text(json.dumps({'scheme':scheme,'values':values}))
            saved = json.loads(TIMER_BACKUP.read_text())
            if saved['scheme'] != scheme: raise RuntimeError('Power plan changed during laptop timer cap. Remove the expired timer to restore.')
            target = [min(v,percent) for v in saved['values']]
            if values == target: return
            for flag, amount in zip(['/setacvalueindex','/setdcvalueindex'],target):
                command(flag,scheme,'SUB_PROCESSOR','PROCTHROTTLEMAX',str(amount))
            command('/setactive',scheme)

limits.system_cap = timer_system_cap

def smi(*args):
    executable = shutil.which('nvidia-smi')
    if not executable:
        candidate = Path(os.environ.get('WINDIR', r'C:\Windows'))/'System32'/'nvidia-smi.exe'
        if candidate.exists(): executable = str(candidate)
    if not executable:
        candidate = Path(os.environ.get('ProgramFiles', r'C:\Program Files'))/'NVIDIA Corporation'/'NVSMI'/'nvidia-smi.exe'
        if candidate.exists(): executable = str(candidate)
    if not executable: raise RuntimeError('NVIDIA driver tool not found. Install the NVIDIA driver on this computer.')
    result = subprocess.run([executable,*args], capture_output=True, text=True, timeout=15, creationflags=0x08000000)
    if result.returncode: raise RuntimeError(result.stderr.strip() or result.stdout.strip() or 'GPU control rejected by driver')
    return result.stdout

def gpu_state():
    try:
        result = smi('--query-gpu=uuid,name,power.limit,power.default_limit,power.min_limit,power.max_limit,utilization.gpu', '--format=csv,noheader,nounits')
        row = next(csv.reader(io.StringIO(result)))
        uid, name = row[0].strip(), row[1].strip()
        try:
            current, default, minimum, maximum = map(float, row[2:6])
            if not all(math.isfinite(v) and v > 0 for v in [current,default,minimum,maximum]): raise ValueError()
            low = math.ceil(minimum/default*100)
            available = minimum < default <= maximum and low < 100
        except ValueError:
            return {'uuid':uid,'name':name,'available':False,'reason':'Power limits unavailable. Try GPU clock mode; this also depends on driver support.', 'canRestore':GPU_BACKUP.exists()}
        return {'uuid':uid,'name':name,'available':available,'reason':'' if available else 'This laptop exposes no lower adjustable power range.', 'current':current,'default':default,'minimum':minimum,'maximum':maximum,'minPercent':low,'percent':round(current/default*100), 'utilization':row[6].strip(),'canRestore':GPU_BACKUP.exists()}
    except Exception as exc: return {'name':'NVIDIA GPU','available':False,'reason':str(exc),'canRestore':GPU_BACKUP.exists()}

def gpu_clocks():
    state = gpu_state()
    if not state.get('uuid'): return {'available':False,'reason':state['reason']}
    try:
        result = smi('-i',state['uuid'],'--query-supported-clocks=gr','--format=csv,noheader,nounits')
        clocks = sorted(set(int(line.strip()) for line in result.splitlines() if line.strip().isdigit()))
        if len(clocks) < 2: raise RuntimeError('GPU clock range is not exposed by this driver')
        saved = json.loads(GPU_BACKUP.read_text()) if GPU_BACKUP.exists() else {}
        return {'available':True,'uuid':state['uuid'],'minimum':clocks[0],'maximum':clocks[-1], 'minPercent':math.ceil(clocks[0]/clocks[-1]*100),'percent':saved.get('percent',100) if saved.get('mode')=='clock' else 100}
    except Exception as exc: return {'available':False,'reason':str(exc)}

def gpu_diagnostics():
    reports = {}
    for name, args in [('summary',()),('power',('-q','-d','POWER')),('clocks',('-q','-d','SUPPORTED_CLOCKS'))]:
        try: reports[name] = smi(*args)[:16000]
        except Exception as exc: reports[name] = str(exc)
    reports['administrator'] = bool(ctypes.windll.shell32.IsUserAnAdmin())
    return reports

def set_gpu(value=None, restore=False, mode='power'):
    with gpu_lock:
        if restore:
            if not GPU_BACKUP.exists(): return
            saved = json.loads(GPU_BACKUP.read_text())
            uid = saved['uuid']
            if saved.get('mode') == 'clock':
                smi('-i',uid,'-rgc')
                GPU_BACKUP.unlink()
                return
            watts = saved['watts']
        else:
            if mode not in ['power','clock']: raise ValueError('Choose power or clock mode')
            if mode == 'clock':
                state = gpu_clocks()
                if not state['available']: raise RuntimeError(state['reason'])
                if type(value) is not int or not state['minPercent'] <= value <= 100:
                    raise ValueError('Clock cap must be '+str(state['minPercent'])+'–100%')
                if GPU_BACKUP.exists() and json.loads(GPU_BACKUP.read_text()).get('mode','power') != 'clock':
                    raise RuntimeError('Restore GPU settings before switching modes')
                uid = state['uuid']
                if GPU_BACKUP.exists() and json.loads(GPU_BACKUP.read_text())['uuid'] != uid:
                    raise RuntimeError('GPU changed. Restore before changing another GPU.')
                cap = max(state['minimum'], round(state['maximum']*value/100))
                if not GPU_BACKUP.exists(): GPU_BACKUP.write_text(json.dumps({'uuid':uid,'mode':'clock'}))
                smi('-i',uid,'-lgc','0,'+str(cap))
                GPU_BACKUP.write_text(json.dumps({'uuid':uid,'mode':'clock','percent':value}))
                return
            state = gpu_state()
            if not state['available']: raise RuntimeError(state['reason'])
            if type(value) is not int or not state['minPercent'] <= value <= 100:
                raise ValueError('GPU limit must be between '+str(state['minPercent'])+'% and 100%')
            uid = state['uuid']
            watts = max(state['minimum'], min(state['default'], round(state['default']*value/100, 2)))
            if GPU_BACKUP.exists() and json.loads(GPU_BACKUP.read_text())['uuid'] != uid:
                raise RuntimeError('GPU changed. Restore the saved GPU before changing another one.')
            if GPU_BACKUP.exists() and json.loads(GPU_BACKUP.read_text()).get('mode') == 'clock':
                raise RuntimeError('Restore GPU settings before switching modes')
            if not GPU_BACKUP.exists(): GPU_BACKUP.write_text(json.dumps({'uuid':uid,'watts':state['current']}))
        smi('-i',uid,'-pl',str(watts))
        if restore: GPU_BACKUP.unlink()

def set_power(value=None, restore=False):
    with power_lock:
        scheme, values = power_state()
        if restore:
            if not BACKUP.exists(): return
            saved = json.loads(BACKUP.read_text())
            scheme, target = saved['scheme'], saved['values']
        else:
            if BACKUP.exists() and json.loads(BACKUP.read_text())['scheme'] != scheme:
                raise RuntimeError('Power plan changed. Restore original settings before changing another plan.')
            if not BACKUP.exists(): BACKUP.write_text(json.dumps({'scheme': scheme, 'values': values}))
            target = [value, value]
        try:
            for flag, amount in zip(['/setacvalueindex', '/setdcvalueindex'], target):
                command(flag, scheme, 'SUB_PROCESSOR', 'PROCTHROTTLEMAX', str(amount))
            command('/setactive', scheme)
        except Exception:
            # Keep backup for recovery even if Windows partially applied the change.
            raise
        if restore: BACKUP.unlink()

fps = FpsMonitor(ROOT, DATA)
metrics = Metrics(fps, stop, smi)
power_actions = PowerActions()
tweakout = Tweakout(ROOT,DATA,shutdown=lambda:power_actions.execute('shutdown'),power_pending=lambda:bool(power_actions.status()['pending']))
gradual_lag = GradualLag(tweakout.cpu,other_active=lambda:tweakout.active is not None,power_pending=lambda:bool(power_actions.status()['pending']))
devices = Devices(DATA)
network_limit = NetworkLimit(ROOT, DATA)
laptops = Laptops(DATA,socket.gethostname())
launcher = AppLauncher()
cap_cache = {'gpu':{'name':'GPU','available':False,'reason':'Checking GPU driver support…','canRestore':GPU_BACKUP.exists()},
             'gpuClocks':{'available':False,'reason':'Checking GPU driver support…'}}
cap_refresh = threading.Event()

def discover_caps():
    global cap_cache
    while not stop.is_set():
        cap_cache = {'gpu':gpu_state(),'gpuClocks':gpu_clocks()}
        cap_refresh.wait(30); cap_refresh.clear()

def supervise():
    while not stop.wait(.25):
        try:
            with control_lock:
                tweakout.tick()
                gradual_lag.tick()
                power_actions.tick()
            network_limit.tick()
        except Exception as exc: print('Control supervisor:',exc)

def maintain_devices():
    # The wall-clock journal expiry also catches a resume from sleep.
    last_inventory = 0
    try: devices.arm_pending()
    except Exception as exc: devices.error=str(exc)
    while not stop.is_set():
        try:
            devices.reconcile()
            if time.monotonic()-last_inventory>30:
                devices.refresh(); last_inventory=time.monotonic()
        except Exception as exc: devices.error=str(exc)
        if stop.wait(5): break

def maintain_apps():
    while not stop.is_set():
        launcher.refresh()
        if stop.wait(120):break

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def respond(self, value, status=200):
        data = json.dumps(value).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)
    def authorized(self):
        return secrets.compare_digest(self.headers.get('X-Access-Key', '').strip().encode('utf-8'), TOKEN.encode('utf-8'))
    def do_GET(self):
        public_assets={'/manifest.webmanifest':('manifest.webmanifest','application/manifest+json'),
                       '/apple-touch-icon.png':('apple-touch-icon.png','image/png'),
                       '/icon-192.png':('icon-192.png','image/png'),'/icon-512.png':('icon-512.png','image/png'),
                       '/icon.svg':('icon.svg','image/svg+xml')}
        if self.path in public_assets:
            filename,mime=public_assets[self.path]; data=(ROOT/filename).read_bytes()
            self.send_response(200); self.send_header('Content-Type',mime)
            self.send_header('Cache-Control','no-cache'); self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Length',str(len(data))); self.end_headers(); self.wfile.write(data); return
        if self.path == '/':
            data = (ROOT/'dashboard.html').read_bytes()
            self.send_response(200)
            self.send_header('Content-Type','text/html; charset=utf-8')
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Frame-Options','DENY')
            self.end_headers()
            self.wfile.write(data)
            return
        if not self.authorized(): return self.respond({'error':'Enter the access key shown on the computer.'},401)
        if self.path == '/api/laptops': return self.respond(laptops.status())
        target=self.headers.get('X-HomeControl-Device','local')
        if target!='local':
            try:
                code,result=laptops.relay(target,self.path)
                return self.respond(result,502 if code==401 else code)
            except Exception as exc:return self.respond({'error':str(exc)},502)
        if self.path == '/api/metrics': return self.respond({**metrics.status(),'powerAction':power_actions.status(),'networkLimit':network_limit.status(),'tweakout':tweakout.status(),'gradualLag':gradual_lag.status()})
        if self.path == '/api/tweakout':return self.respond(tweakout.status())
        if self.path == '/api/lag':return self.respond(gradual_lag.status())
        if self.path == '/api/apps':return self.respond(launcher.status())
        if self.path == '/api/network': return self.respond(network_limit.status())
        if self.path == '/api/fps': return self.respond(fps.status())
        if self.path == '/api/devices': return self.respond(devices.status())
        if self.path == '/api/power/action': return self.respond(power_actions.status())
        if self.path == '/api/gpu/diagnostics': return self.respond(gpu_diagnostics())
        if self.path != '/api/status': return self.respond({'error':'Not found'},404)
        today = datetime.date.today()
        with connect() as db:
            rows = db.execute('SELECT app, SUM(CASE WHEN day=? THEN seconds ELSE 0 END), SUM(seconds) FROM usage WHERE day>=? GROUP BY app ORDER BY SUM(seconds) DESC', (today.isoformat(), (today-datetime.timedelta(days=6)).isoformat())).fetchall()
        try:
            _, caps = power_state()
            power_error = ''
        except Exception as exc: caps, power_error = [None,None], str(exc)
        self.respond({'version':VERSION,'active':active,'apps':[{'name':r[0],'today':r[1],'week':r[2]} for r in rows], 'ac':caps[0], 'battery':caps[1], 'error':error or power_error or limit_error, 'canRestore':BACKUP.exists(), **cap_cache,'limits':limits.status(),'terminalEnabled':terminal_is_enabled()})
    def do_POST(self):
        if not self.authorized(): return self.respond({'error':'Access denied'},401)
        # Custom header + JSON and no CORS prevent cross-site form control.
        if self.headers.get('Content-Type') != 'application/json': return self.respond({'error':'JSON required'},400)
        try:
            length = int(self.headers.get('Content-Length','0'))
            if not 0 < length <= 16384: raise ValueError('Invalid request size')
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict): raise ValueError('JSON object required')
            if self.path == '/api/laptops':return self.respond(laptops.add(body.get('name'),body.get('url'),body.get('key')))
            if self.path == '/api/laptops/remove':return self.respond(laptops.remove(body.get('id')))
            target=self.headers.get('X-HomeControl-Device','local')
            if target!='local':
                code,result=laptops.relay(target,self.path,body)
                return self.respond(result,502 if code==401 else code)
            exclusive={'/api/lag/start','/api/lag/cancel','/api/tweakout/start','/api/tweakout/cancel','/api/power','/api/restore','/api/gpu','/api/gpu/restore','/api/limits','/api/limits/remove','/api/power/action','/api/power/cancel'}
            with control_lock if self.path in exclusive else nullcontext():
                mode_route=self.path.startswith(('/api/tweakout/','/api/lag/'))
                if self.path in exclusive and not mode_route and (tweakout.blocked() or gradual_lag.blocked()):
                    raise RuntimeError('Cancel the active mode on this computer’s dashboard before changing power or app budgets.')
                if self.path.startswith('/api/tweakout/') and gradual_lag.active is not None:raise RuntimeError('Cancel gradual lag before using Tweakout.')
                if self.path == '/api/tweakout/start':return self.respond(tweakout.start(body.get('preview',False),body.get('confirmed',False)))
                elif self.path == '/api/tweakout/cancel':return self.respond(tweakout.cancel())
                elif self.path == '/api/lag/start':return self.respond(gradual_lag.start(body.get('floor',10),body.get('hold',30)))
                elif self.path == '/api/lag/cancel':return self.respond(gradual_lag.cancel())
                elif self.path == '/api/apps/refresh':return self.respond(launcher.refresh())
                elif self.path == '/api/apps/launch':return self.respond(launcher.launch(body.get('id')))
                elif self.path == '/api/power':
                    value = body.get('value')
                    if type(value) is not int or not 1 <= value <= 100: raise ValueError('Choose 1–100%')
                    if TIMER_BACKUP.exists(): raise RuntimeError('A laptop timer cap is active. Remove or raise its time budget before changing the CPU slider.')
                    set_power(value)
                elif self.path == '/api/restore': set_power(restore=True)
                elif self.path == '/api/gpu': set_gpu(body.get('value'), mode=body.get('mode','power'))
                elif self.path == '/api/gpu/restore': set_gpu(restore=True)
                elif self.path == '/api/fps/settings': return self.respond(fps.settings(body.get('enabled'),body.get('pid')))
                elif self.path == '/api/network':
                    if 'mbps' not in body:raise ValueError('Mbps is required; use null for Unlimited.')
                    return self.respond(network_limit.apply(body['mbps']))
                elif self.path == '/api/devices/refresh': devices.refresh(); return self.respond(devices.status())
                elif self.path == '/api/devices/selections': return self.respond(devices.select(body.get('selections')))
                elif self.path == '/api/devices/action': return self.respond(devices.perform(body.get('group'),body.get('action'),body.get('confirmed',False)))
                elif self.path == '/api/power/action': return self.respond(power_actions.request(body.get('action')))
                elif self.path == '/api/power/cancel': return self.respond(power_actions.cancel())
                elif self.path == '/api/limits': limits.save(body.get('app'),body.get('minutes'),body.get('percent'),body.get('scope','app')); limits.tick()
                elif self.path == '/api/limits/remove':
                    if not isinstance(body.get('app'),str): raise ValueError('App name required')
                    limits.remove(body['app'])
                    limits.tick()
                elif self.path == '/api/keyboard':return self.respond(send_keyboard(body))
                elif self.path == '/api/terminal':
                    if not terminal_is_enabled(): return self.respond({'error':'Run Enable-Terminal.cmd on the laptop to enable commands.'},403)
                    return self.respond(terminal.run(body.get('command'),body.get('cwd')))
                else: return self.respond({'error':'Not found'},404)
                if self.path.startswith('/api/gpu'): cap_refresh.set()
                self.respond({'ok':True})
        except Exception as exc: self.respond({'error':str(exc)},400)

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--restore', action='store_true')
    parser.add_argument('--background', action='store_true')
    args = parser.parse_args()
    if args.background:
        import sys
        sys.stdout = sys.stderr = open(DATA/'background.log', 'a', buffering=1, encoding='utf-8')
    if args.restore:
        failures = []
        for restore in [lambda:gradual_lag.close(),lambda:tweakout.close(),lambda:timer_system_cap(None),lambda:set_power(restore=True), lambda:set_gpu(restore=True)]:
            try: restore()
            except Exception as exc: failures.append(str(exc))
        if failures: raise RuntimeError('; '.join(failures))
        print('Original CPU and GPU settings restored.')
    else:
        # Bind before tracking to prevent duplicate launches from double-counting.
        server = ThreadingHTTPServer(('0.0.0.0',8765),Handler)
        tweakout.reconcile()
        metrics.start()
        fps.start()
        threading.Thread(target=track, daemon=True).start()
        threading.Thread(target=enforce_limits, daemon=True).start()
        threading.Thread(target=discover_caps, daemon=True).start()
        threading.Thread(target=supervise, daemon=True).start()
        threading.Thread(target=maintain_devices, daemon=True).start()
        threading.Thread(target=maintain_apps, daemon=True).start()
        print('HomeControl — keep this window open. Ctrl+C stops tracking.')
        print('Access key:', TOKEN)
        for ip in sorted(set(socket.gethostbyname_ex(socket.gethostname())[2])):
            if not ip.startswith('127.'): print('iPhone address: http://'+ip+':8765')
        print('Power changes persist until you select Restore original settings.')
        print('Runtime data:',str(DATA),'Terminal enabled:',terminal_is_enabled())
        try: server.serve_forever()
        except KeyboardInterrupt: stop.set()
        finally:
            stop.set(); gradual_lag.close(); tweakout.close(); power_actions.cancel(); network_limit.stop(); fps.close()
            limits.close(); server.server_close()
