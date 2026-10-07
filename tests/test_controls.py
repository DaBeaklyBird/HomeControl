import ctypes
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.request
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
temporary = tempfile.TemporaryDirectory()
os.environ['LOCALAPPDATA'] = temporary.name
os.environ['HOMECONTROL_DATA'] = str(Path(temporary.name)/'HomeControl')
app = importlib.import_module('server')

class Controls(unittest.TestCase):
    def setUp(self):
        for path in [app.BACKUP,app.GPU_BACKUP,app.TIMER_BACKUP]: path.unlink(missing_ok=True)
        with app.connect() as db:
            db.execute('DELETE FROM usage')
            db.execute('INSERT INTO usage VALUES(?,?,?)',(app.datetime.date.today().isoformat(),'sample.exe',3600))
        self.calls=[]
        self.power=patch.object(app,'power_state',return_value=('test-plan',[80,70]))
        self.cmd=patch.object(app,'command',side_effect=lambda *args:self.calls.append(args))
        self.power.start();self.cmd.start()
    def tearDown(self):
        self.cmd.stop();self.power.stop()
    def test_cpu_one_percent_and_restoration(self):
        app.set_power(1)
        self.assertEqual(self.calls[0][-1],'1')
        app.set_power(restore=True)
        self.assertEqual(self.calls[-3][-1],'80')
        self.assertEqual(self.calls[-2][-1],'70')
    def test_gpu_modes_and_hardware_floor(self):
        def smi(*args):
            if '--query-supported-clocks=gr' in args:return '210\n2100\n'
            if args[0].startswith('--query-gpu'):return 'GPU-test, RTX 3050 Laptop, 60, 60, 30, 80, 20\n'
            self.calls.append(args);return ''
        with patch.object(app,'smi',side_effect=smi):
            with self.assertRaises(ValueError):app.set_gpu(1)
            app.set_gpu(50)
            self.assertEqual(self.calls[-1][-1],'30.0')
            app.set_gpu(restore=True)
            app.set_gpu(10,mode='clock')
            self.assertEqual(self.calls[-1][-1],'0,210')
            app.set_gpu(restore=True)
            self.assertEqual(self.calls[-1][-1],'-rgc')
    def test_unsupported_gpu(self):
        with patch.object(app,'smi',return_value='GPU-test, RTX 3050 Laptop, N/A, N/A, N/A, N/A, 0\n'):
            self.assertFalse(app.gpu_state()['available'])
    def test_daily_budget_scopes_and_reset(self):
        caps=[]
        limits=app.Limits(app.DATA,app.connect,caps.append)
        limits.file=app.DATA/'test-limits.json'
        limits.rules={}
        with patch('app_limits.CpuJob') as factory,patch('app_limits.processes',return_value=[(123,'sample.exe')]):
            limits.save('sample.exe',30,3,'app');limits.tick()
            factory.return_value.cap.assert_called_with(3)
            factory.return_value.add.assert_called_with(123)
            limits.save('sample.exe',30,2,'laptop');limits.tick()
            self.assertEqual(caps[-1],2)
            self.assertTrue(limits.status()[0]['expired'])
            with app.connect() as db:db.execute('UPDATE usage SET seconds=0')
            limits.tick()
            self.assertIsNone(caps[-1])
            self.assertFalse(limits.status()[0]['expired'])
            limits.remove('sample.exe');self.assertEqual(limits.status(),[])
            with self.assertRaises(ValueError):limits.save('unknown.exe',1,1)
    def test_laptop_timer_restores_prior_values(self):
        app.timer_system_cap(2)
        self.assertEqual(self.calls[0][-1],'2')
        app.timer_system_cap(None)
        self.assertEqual(self.calls[-3][-1],'80')
        self.assertEqual(self.calls[-2][-1],'70')
    def test_http_auth_terminal_gate_and_minimum(self):
        server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        def request(path,body,key=app.TOKEN):
            req=urllib.request.Request('http://127.0.0.1:'+str(server.server_port)+path,headers={'X-Access-Key':key,'Content-Type':'application/json'},data=json.dumps(body).encode())
            try:
                with urllib.request.urlopen(req) as r:return r.status,json.load(r)
            except urllib.error.HTTPError as exc:return exc.code,json.load(exc)
        try:
            self.assertEqual(request('/api/power',{'value':1},'wrong')[0],401)
            self.assertEqual(request('/api/power',{'value':0})[0],400)
            self.assertEqual(request('/api/power',{'value':1})[0],200)
            with patch.object(app,'terminal_enabled',False):self.assertEqual(request('/api/terminal',{'command':'whoami'})[0],403)
            with patch.object(app,'terminal_enabled',True),patch.object(app.terminal,'run',return_value={'output':'ok'}) as run:
                self.assertEqual(request('/api/terminal',{'command':'whoami'})[1]['output'],'ok')
                run.assert_called_once_with('whoami',None)
        finally:server.shutdown();server.server_close()
    def test_native_job_on_disposable_child(self):
        from app_limits import CpuJob,Rate,k
        child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(10)'],creationflags=subprocess.CREATE_NO_WINDOW)
        job=CpuJob()
        try:
            job.cap(1);job.add(child.pid)
            query=k.QueryInformationJobObject
            query.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_void_p,ctypes.c_uint32,ctypes.c_void_p]
            rate=Rate()
            self.assertTrue(query(job.handle,15,ctypes.byref(rate),ctypes.sizeof(rate),None))
            self.assertEqual(rate.rate,100)
            self.assertEqual(rate.flags,5)
        finally:
            job.close();child.terminate();child.wait(timeout=5)
    def test_native_pending_budget_job_can_close(self):
        from app_limits import CpuJob
        CpuJob().close()
    def test_terminal_real_readonly_command(self):
        result=app.terminal.run("Write-Output 'terminal-ok'")
        self.assertIn('terminal-ok',result['output'])
        self.assertEqual(result['exitCode'],0)
    def test_terminal_deadline_and_output_bound(self):
        short = app.Terminal(ROOT,timeout=0.5)
        result=short.run('Start-Sleep -Seconds 10')
        self.assertTrue(result['timedOut'])
        result=app.terminal.run("Write-Output ('a' * 70000)")
        self.assertTrue(result['truncated'])
        self.assertLessEqual(len(result['output']),65536)
    def test_gpu_rejection_is_reported_with_recovery_backup(self):
        def smi(*args):
            if args[0].startswith('--query-gpu'):return 'GPU-test, RTX 3050 Laptop, 60, 60, 30, 80, 0\n'
            raise RuntimeError('Changing power management limit is not supported')
        with patch.object(app,'smi',side_effect=smi):
            with self.assertRaisesRegex(RuntimeError,'not supported'):app.set_gpu(50)
            self.assertTrue(app.GPU_BACKUP.exists())

    def test_webapp_assets_are_public_and_runtime_files_stay_private(self):
        import struct
        server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            base='http://127.0.0.1:'+str(server.server_port)
            with urllib.request.urlopen(base+'/manifest.webmanifest') as response:
                self.assertEqual(response.headers['Content-Type'],'application/manifest+json')
                manifest=json.load(response)
            self.assertEqual(manifest['display'],'standalone'); self.assertEqual(manifest['start_url'],'/')
            self.assertNotIn(app.TOKEN,json.dumps(manifest))
            for path,size in [('apple-touch-icon.png',180),('icon-192.png',192),('icon-512.png',512)]:
                with urllib.request.urlopen(base+'/'+path) as response:
                    png=response.read(); self.assertEqual(response.headers['Content-Type'],'image/png')
                self.assertEqual(png[:8],b'\x89PNG\r\n\x1a\n'); self.assertEqual(struct.unpack('>II',png[16:24]),(size,size))
            for path in ['/key.txt','/device-recovery.json','/../key.txt','/api/metrics']:
                with self.assertRaises(urllib.error.HTTPError) as error: urllib.request.urlopen(base+path)
                self.assertEqual(error.exception.code,401)
        finally: server.shutdown(); server.server_close()

    def test_new_endpoints_authenticate_and_do_not_block_on_cap_discovery(self):
        server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        def request(path,body=None,key=app.TOKEN):
            req=urllib.request.Request('http://127.0.0.1:'+str(server.server_port)+path,
                headers={'X-Access-Key':key,'Content-Type':'application/json'},data=json.dumps(body).encode() if body is not None else None)
            try:
                with urllib.request.urlopen(req) as r:return r.status,json.load(r)
            except urllib.error.HTTPError as exc:return exc.code,json.load(exc)
        try:
            for path in ['/api/metrics','/api/fps','/api/devices','/api/gpu/load','/api/power/action']:
                self.assertEqual(request(path,key='wrong')[0],401)
                self.assertEqual(request(path)[0],200)
            for path in ['/api/fps/settings','/api/gpu/load/start','/api/gpu/load/duty','/api/gpu/load/stop',
                         '/api/devices/refresh','/api/devices/selections','/api/devices/action','/api/power/action','/api/power/cancel']:
                self.assertEqual(request(path,{},key='wrong')[0],401)
            with patch.object(app,'smi',side_effect=AssertionError('Slow discovery must not run here')):
                self.assertEqual(request('/api/status')[0],200)
                self.assertEqual(request('/api/metrics')[0],200)
            with patch.object(app.power_actions,'request',return_value={'pending':None}) as call:
                self.assertEqual(request('/api/power/action',{'action':'lock'})[0],200)
                call.assert_called_once_with('lock')
            with patch.object(app.devices,'perform',return_value={'results':[]}) as call:
                self.assertEqual(request('/api/devices/action',{'group':'both','action':'restart'})[0],200)
                call.assert_called_once_with('both','restart')
        finally:server.shutdown();server.server_close()

if __name__=='__main__':unittest.main(verbosity=2)
