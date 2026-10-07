import ctypes, datetime, json, os, secrets, socket, sqlite3, subprocess, threading, time, shutil, csv, io, math
from ctypes import wintypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).parent
DATA = Path(os.environ.get('LOCALAPPDATA', str(ROOT))) / 'HomeControl'
LOCATION = ROOT / 'data-location.txt'
if LOCATION.exists(): DATA = Path(LOCATION.read_text(encoding='utf-8-sig').strip())
DATA.mkdir(exist_ok=True)
TOKEN_FILE = DATA / 'key.txt'
if not TOKEN_FILE.exists(): TOKEN_FILE.write_text(secrets.token_urlsafe(24))
TOKEN = TOKEN_FILE.read_text().strip()
DB = DATA / 'usage.sqlite'
lock = threading.Lock()
power_lock = threading.Lock()
active = 'Starting'
error = ''
stop = threading.Event()

def connect():
    return sqlite3.connect(DB, timeout=10)

with connect() as db:
    db.execute('CREATE TABLE IF NOT EXISTS usage (day TEXT, app TEXT, seconds REAL, PRIMARY KEY(day, app))')

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
    # Windows Power APIs avoid parsing localized powercfg output.
    powr = ctypes.WinDLL('powrprof')
    class GUID(ctypes.Structure):
        _fields_ = [('a', wintypes.DWORD), ('b', wintypes.WORD), ('c', wintypes.WORD), ('d', ctypes.c_ubyte*8)]
    import uuid
    def guid(value): return GUID.from_buffer_copy(uuid.UUID(value).bytes_le)
    ptr = ctypes.POINTER(GUID)()
    if powr.PowerGetActiveScheme(None, ctypes.byref(ptr)): raise RuntimeError('Cannot read active power plan')
    try:
        scheme = str(uuid.UUID(bytes_le=bytes(ptr.contents)))
        sub = guid('54533251-82be-4824-96c1-47b60b740d00')
        setting = guid('bc5038f7-23e0-4960-96da-33abaf5935ec')
        values = []
        for name in ['PowerReadACValueIndex', 'PowerReadDCValueIndex']:
            value = wintypes.DWORD()
            if getattr(powr, name)(None, ptr, ctypes.byref(sub), ctypes.byref(setting), ctypes.byref(value)):
                raise RuntimeError('Maximum processor state is unavailable on this laptop')
            values.append(value.value)
        return scheme, values
    finally:
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree(ptr)

BACKUP = DATA / 'original-power.json'
GPU_BACKUP = DATA / 'original-gpu.json'
gpu_lock = threading.Lock()

def smi(*args):
    executable = shutil.which('nvidia-smi')
    if not executable:
        candidate = Path(os.environ.get('WINDIR', r'C:\Windows'))/'System32'/'nvidia-smi.exe'
        if candidate.exists(): executable = str(candidate)
    if not executable: raise RuntimeError('NVIDIA driver tool not found. Install the NVIDIA driver on this laptop.')
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
            return {'name':name,'available':False,'reason':'This GPU driver does not expose adjustable power limits. A GPU percentage cap is unavailable.'}
        return {'uuid':uid,'name':name,'available':available,'reason':'' if available else 'This laptop exposes no lower adjustable power range.', 'current':current,'default':default,'minimum':minimum,'maximum':maximum,'minPercent':low,'percent':round(current/default*100), 'utilization':row[6].strip(),'canRestore':GPU_BACKUP.exists()}
    except Exception as exc: return {'name':'NVIDIA GPU','available':False,'reason':str(exc),'canRestore':GPU_BACKUP.exists()}

def set_gpu(value=None, restore=False):
    with gpu_lock:
        if restore:
            if not GPU_BACKUP.exists(): return
            saved = json.loads(GPU_BACKUP.read_text())
            uid, watts = saved['uuid'], saved['watts']
        else:
            state = gpu_state()
            if not state['available']: raise RuntimeError(state['reason'])
            if type(value) is not int or not state['minPercent'] <= value <= 100:
                raise ValueError('GPU limit must be between '+str(state['minPercent'])+'% and 100%')
            uid = state['uuid']
            watts = max(state['minimum'], min(state['default'], round(state['default']*value/100, 2)))
            if GPU_BACKUP.exists() and json.loads(GPU_BACKUP.read_text())['uuid'] != uid:
                raise RuntimeError('GPU changed. Restore the saved GPU before changing another one.')
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
        if self.path == '/':
            data = (ROOT/'dashboard.html').read_bytes()
            self.send_response(200)
            self.send_header('Content-Type','text/html; charset=utf-8')
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Frame-Options','DENY')
            self.end_headers()
            self.wfile.write(data)
            return
        if not self.authorized(): return self.respond({'error':'Enter the access key shown on the laptop.'},401)
        if self.path != '/api/status': return self.respond({'error':'Not found'},404)
        today = datetime.date.today()
        with connect() as db:
            rows = db.execute('SELECT app, SUM(CASE WHEN day=? THEN seconds ELSE 0 END), SUM(seconds) FROM usage WHERE day>=? GROUP BY app ORDER BY SUM(seconds) DESC', (today.isoformat(), (today-datetime.timedelta(days=6)).isoformat())).fetchall()
        try:
            _, caps = power_state()
            power_error = ''
        except Exception as exc: caps, power_error = [None,None], str(exc)
        self.respond({'active':active,'apps':[{'name':r[0],'today':r[1],'week':r[2]} for r in rows], 'ac':caps[0], 'battery':caps[1], 'error':error or power_error, 'canRestore':BACKUP.exists(), 'gpu':gpu_state()})
    def do_POST(self):
        if not self.authorized(): return self.respond({'error':'Access denied'},401)
        # Custom header + JSON and no CORS prevent cross-site form control.
        if self.headers.get('Content-Type') != 'application/json': return self.respond({'error':'JSON required'},400)
        try:
            length = int(self.headers.get('Content-Length','0'))
            if not 0 < length <= 1024: raise ValueError('Invalid request size')
            body = json.loads(self.rfile.read(length))
            if self.path == '/api/power':
                value = body.get('value')
                if type(value) is not int or not 10 <= value <= 100: raise ValueError('Choose 10–100%')
                set_power(value)
            elif self.path == '/api/restore': set_power(restore=True)
            elif self.path == '/api/gpu': set_gpu(body.get('value'))
            elif self.path == '/api/gpu/restore': set_gpu(restore=True)
            else: return self.respond({'error':'Not found'},404)
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
        for restore in [lambda:set_power(restore=True), lambda:set_gpu(restore=True)]:
            try: restore()
            except Exception as exc: failures.append(str(exc))
        if failures: raise RuntimeError('; '.join(failures))
        print('Original CPU and GPU settings restored.')
    else:
        # Bind before tracking to prevent duplicate launches from double-counting.
        server = ThreadingHTTPServer(('0.0.0.0',8765),Handler)
        threading.Thread(target=track, daemon=True).start()
        print('HomeControl — keep this window open. Ctrl+C stops tracking.')
        print('Access key:', TOKEN)
        for ip in sorted(set(socket.gethostbyname_ex(socket.gethostname())[2])):
            if not ip.startswith('127.'): print('iPhone address: http://'+ip+':8765')
        print('Power changes persist until you select Restore original settings.')
        try: server.serve_forever()
        except KeyboardInterrupt: stop.set()
