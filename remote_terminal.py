"""Authenticated one-command PowerShell runner; terminal child trees have a deadline."""
import ctypes
from ctypes import wintypes as W
from pathlib import Path
import subprocess
import threading
from app_limits import k

class Basic(ctypes.Structure):
    _fields_=[('processTime',ctypes.c_int64),('jobTime',ctypes.c_int64),('flags',W.DWORD),
              ('minWorking',ctypes.c_size_t),('maxWorking',ctypes.c_size_t),('active',W.DWORD),
              ('affinity',ctypes.c_size_t),('priority',W.DWORD),('scheduling',W.DWORD)]
class IO(ctypes.Structure):
    _fields_=[(name,ctypes.c_uint64) for name in ['readOps','writeOps','otherOps','readBytes','writeBytes','otherBytes']]
class Extended(ctypes.Structure):
    _fields_=[('basic',Basic),('io',IO),('processMemory',ctypes.c_size_t),('jobMemory',ctypes.c_size_t),('peakProcess',ctypes.c_size_t),('peakJob',ctypes.c_size_t)]

class CommandJob:
    def __init__(self):
        self.handle=k.CreateJobObjectW(None,None)
        if not self.handle:raise ctypes.WinError(ctypes.get_last_error())
        config=Extended();config.basic.flags=0x2000
        if not k.SetInformationJobObject(self.handle,9,ctypes.byref(config),ctypes.sizeof(config)):
            k.CloseHandle(self.handle)
            raise ctypes.WinError(ctypes.get_last_error())
    def add(self,pid):
        handle=k.OpenProcess(0x101,False,pid)
        if not handle:raise ctypes.WinError(ctypes.get_last_error())
        try:
            if not k.AssignProcessToJobObject(self.handle,handle):raise ctypes.WinError(ctypes.get_last_error())
        finally:k.CloseHandle(handle)
    def close(self):k.CloseHandle(self.handle)

class Terminal:
    def __init__(self, root, timeout=30):
        self.root = root
        self.timeout = timeout
        self.lock = threading.Lock()
    def run(self, command, cwd=None):
        if not isinstance(command, str) or not command.strip() or len(command) > 8192:
            raise ValueError('Enter a PowerShell command, up to 8192 characters')
        folder = Path(cwd or self.root).expanduser().resolve()
        if not folder.is_dir(): raise ValueError('Working directory does not exist')
        if not self.lock.acquire(blocking=False): raise RuntimeError('Another terminal command is running')
        try:
            prefix = "$ProgressPreference='SilentlyContinue'; [Console]::OutputEncoding=[System.Text.UTF8Encoding]::new(); "
            job = CommandJob()
            process = None
            try:
                process = subprocess.Popen(['powershell.exe','-NoProfile','-NonInteractive','-Command',prefix+command],
                    cwd=folder, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    creationflags=subprocess.CREATE_NO_WINDOW)
                job.add(process.pid)
            except Exception:
                job.close()
                if process:
                    process.kill();process.wait()
                    process.stdout.close()
                raise
            output = bytearray()
            truncated = [False]
            def read():
                while True:
                    chunk = process.stdout.read(4096)
                    if not chunk: break
                    space = max(0, 65536-len(output))
                    output.extend(chunk[:space])
                    if len(chunk) > space: truncated[0] = True
            reader = threading.Thread(target=read, daemon=True)
            reader.start()
            timeout = False
            try:
                try: process.wait(timeout=self.timeout)
                except subprocess.TimeoutExpired: timeout = True
            finally: job.close()
            process.wait(timeout=5)
            reader.join(timeout=3)
            process.stdout.close()
            return {'output':output.decode('utf-8', errors='replace'),'exitCode':process.returncode,'timedOut':timeout,'truncated':truncated[0],'cwd':str(folder)}
        finally: self.lock.release()
