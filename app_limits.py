"""Daily foreground-time budgets, enforced with Windows CPU-rate job objects."""
import ctypes
from ctypes import wintypes as W
import datetime
import json
import os
from pathlib import Path
import threading
import hashlib

k = ctypes.WinDLL('kernel32', use_last_error=True)
k.CreateJobObjectW.argtypes = [ctypes.c_void_p, W.LPCWSTR]
k.CreateJobObjectW.restype = W.HANDLE
k.SetInformationJobObject.argtypes = [W.HANDLE, ctypes.c_int, ctypes.c_void_p, W.DWORD]
k.AssignProcessToJobObject.argtypes = [W.HANDLE, W.HANDLE]
k.IsProcessInJob.argtypes = [W.HANDLE, W.HANDLE, ctypes.POINTER(W.BOOL)]
k.QueryInformationJobObject.argtypes = [W.HANDLE, ctypes.c_int, ctypes.c_void_p, W.DWORD, ctypes.c_void_p]
k.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
k.OpenProcess.restype = W.HANDLE
k.CloseHandle.argtypes = [W.HANDLE]
k.CreateToolhelp32Snapshot.argtypes = [W.DWORD, W.DWORD]
k.CreateToolhelp32Snapshot.restype = W.HANDLE
k.QueryFullProcessImageNameW.argtypes = [W.HANDLE, W.DWORD, W.LPWSTR, ctypes.POINTER(W.DWORD)]

class Entry(ctypes.Structure):
    _fields_ = [('dwSize', W.DWORD), ('cntUsage', W.DWORD), ('pid', W.DWORD),
                ('heap', ctypes.c_size_t), ('module', W.DWORD), ('threads', W.DWORD),
                ('parent', W.DWORD), ('priority', W.LONG), ('flags', W.DWORD), ('name', W.WCHAR*260)]

k.Process32FirstW.argtypes = [W.HANDLE, ctypes.POINTER(Entry)]
k.Process32NextW.argtypes = [W.HANDLE, ctypes.POINTER(Entry)]

class Rate(ctypes.Structure):
    _fields_ = [('flags', W.DWORD), ('rate', W.DWORD)]

def processes():
    handle = k.CreateToolhelp32Snapshot(2, 0)
    if handle == ctypes.c_void_p(-1).value: raise ctypes.WinError(ctypes.get_last_error())
    entry = Entry()
    entry.dwSize = ctypes.sizeof(entry)
    try:
        ok = k.Process32FirstW(handle, ctypes.byref(entry))
        while ok:
            yield entry.pid, entry.name
            ok = k.Process32NextW(handle, ctypes.byref(entry))
    finally: k.CloseHandle(handle)

class CpuJob:
    def __init__(self, name=None):
        self.handle = k.CreateJobObjectW(None, name)
        if not self.handle: raise ctypes.WinError(ctypes.get_last_error())
    def cap(self, percent):
        if percent is None:
            current = Rate()
            if not k.QueryInformationJobObject(self.handle,15,ctypes.byref(current),ctypes.sizeof(current),None):
                raise ctypes.WinError(ctypes.get_last_error())
            if not current.flags: return
        value = Rate(5 if percent is not None else 0, (percent or 0)*100)
        if not k.SetInformationJobObject(self.handle, 15, ctypes.byref(value), ctypes.sizeof(value)):
            raise ctypes.WinError(ctypes.get_last_error())
    def add(self, pid):
        if pid == os.getpid(): raise ValueError('Cannot throttle HomeControl itself')
        handle = k.OpenProcess(0x100 | 0x1 | 0x1000, False, pid)
        if not handle: raise ctypes.WinError(ctypes.get_last_error())
        try:
            buf = ctypes.create_unicode_buffer(32768)
            size = W.DWORD(len(buf))
            if not k.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                raise ctypes.WinError(ctypes.get_last_error())
            path = Path(buf.value).resolve()
            windows = Path(os.environ.get('WINDIR', r'C:\Windows')).resolve()
            if path.is_relative_to(windows): raise ValueError('Windows system processes cannot be throttled')
            member = W.BOOL()
            if not k.IsProcessInJob(handle, self.handle, ctypes.byref(member)):
                raise ctypes.WinError(ctypes.get_last_error())
            if not member.value and not k.AssignProcessToJobObject(self.handle, handle):
                raise ctypes.WinError(ctypes.get_last_error())
        finally: k.CloseHandle(handle)
    def close(self):
        self.cap(None)
        k.CloseHandle(self.handle)

class Limits:
    def __init__(self, data, connect, system_cap=None):
        self.file = data/'app-limits.json'
        self.connect = connect
        self.system_cap = system_cap
        self.prefix = 'Local\\HomeControl-'+hashlib.sha256(str(data).encode()).hexdigest()[:16]+'-'
        self.lock = threading.RLock()
        self.jobs = {}
        self.results = {}
        self.rules = json.loads(self.file.read_text()) if self.file.exists() else {}
    def save(self, app, minutes, percent, scope='app'):
        if not isinstance(app, str) or Path(app).name != app or not app.lower().endswith('.exe'):
            raise ValueError('Choose an executable from recorded apps')
        if type(minutes) is not int or not 1 <= minutes <= 1440: raise ValueError('Minutes must be 1–1440')
        if type(percent) is not int or not 1 <= percent <= 100: raise ValueError('CPU cap must be 1–100%')
        if scope not in ['app','laptop']: raise ValueError('Choose app or laptop scope')
        with self.connect() as db:
            if not db.execute('SELECT 1 FROM usage WHERE lower(app)=lower(?) LIMIT 1', (app,)).fetchone():
                raise ValueError('Use an app that has recorded foreground time')
        with self.lock:
            self.rules[app.lower()] = {'app':app, 'minutes':minutes, 'percent':percent,'scope':scope}
            self.persist()
    def persist(self):
        temp = self.file.with_suffix('.tmp')
        temp.write_text(json.dumps(self.rules))
        temp.replace(self.file)
    def remove(self, app):
        with self.lock:
            name = app.lower()
            if name in self.jobs:
                self.jobs[name].close()
                del self.jobs[name]
            self.rules.pop(name, None)
            self.results.pop(name, None)
            self.persist()
    def totals(self):
        with self.connect() as db:
            return dict(db.execute('SELECT lower(app), SUM(seconds) FROM usage WHERE day=? GROUP BY lower(app)', (datetime.date.today().isoformat(),)))
    def tick(self):
        with self.lock:
            totals = self.totals()
            running = list(processes()) if self.rules else []
            system_caps = []
            for name, rule in self.rules.items():
                expired = totals.get(name, 0) >= rule['minutes']*60
                failures, applied = [], 0
                if expired and rule.get('scope','app') == 'laptop': system_caps.append(rule['percent'])
                if rule.get('scope','app') == 'app':
                    if name not in self.jobs:
                        job_name = self.prefix+hashlib.sha256(name.encode()).hexdigest()[:16]
                        self.jobs[name] = CpuJob(job_name)
                if expired and rule.get('scope','app') == 'app':
                    try:
                        job = self.jobs[name]
                        job.cap(rule['percent'])
                        for pid, exe in running:
                            if exe.lower() != name: continue
                            try: job.add(pid); applied += 1
                            except Exception as exc: failures.append(str(exc))
                    except Exception as exc: failures.append(str(exc))
                elif name in self.jobs:
                    try:
                        self.jobs[name].close()
                        del self.jobs[name]
                    except Exception as exc: failures.append(str(exc))
                self.results[name] = {'expired':expired,'processes':applied,'error':'; '.join(failures)}
            if self.system_cap: self.system_cap(min(system_caps) if system_caps else None)
    def status(self):
        with self.lock:
            totals = self.totals()
            return [{**rule, 'usedSeconds':totals.get(name, 0), **self.results.get(name, {})} for name,rule in self.rules.items()]
    def close(self):
        with self.lock:
            for job in self.jobs.values(): job.close()
            self.jobs.clear()
