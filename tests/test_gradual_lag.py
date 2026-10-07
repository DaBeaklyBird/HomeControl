"""Every machine-wide CPU write is mocked, including recovery and HTTP actions."""
import importlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock,patch
import urllib.request
import urllib.error
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from gradual_lag import GradualLag
from tweakout import CpuRecovery
SCHEME='381b4222-f694-41f0-9685-ff5bb260df2e'

class LagTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.now=100.;self.events=[]
        self.cpu=CpuRecovery(tmp.name,read=lambda:(SCHEME,[80,70]),command=lambda *a:self.events.append(a),register=Mock(),clock=lambda:1000+self.now-100)
        self.mode=GradualLag(self.cpu,clock=lambda:self.now)
    def advance(self,seconds):
        for _ in range(seconds):self.now+=1;self.mode.tick()
    def test_one_point_each_second_independent_ac_dc_and_floor(self):
        self.mode.start(68,10);self.assertEqual(self.events,[]);self.cpu.register.assert_called_once()
        self.advance(1);self.assertEqual(self.mode.status()['ac'],79);self.assertEqual(self.mode.status()['battery'],69)
        self.advance(11);self.assertEqual(self.mode.status()['state'],'holding');self.assertEqual(self.mode.status()['ac'],68)
        self.assertEqual(self.mode.status()['battery'],68)
        self.advance(10);self.assertEqual(self.mode.status()['state'],'finished');self.assertFalse(self.cpu.file.exists())
        self.assertEqual([a[-1] for a in self.events[-3:-1]],['80','70'])
    def test_cancel_restores_without_increasing_low_original_cap(self):
        self.cpu.read=lambda:(SCHEME,[80,5]);self.mode.start(10,0);self.advance(2)
        self.assertEqual(self.mode.status()['battery'],5);self.mode.cancel();self.advance(100)
        self.assertEqual(self.mode.status()['state'],'cancelled');self.assertFalse(self.cpu.file.exists())
        self.assertEqual([a[-1] for a in self.events[-3:-1]],['80','5'])
    def test_strict_inputs_and_conflicting_modes(self):
        for floor,hold in [(0,30),(100,30),(True,30),(10,-1),(10,61),(10,False)]:
            with self.assertRaises(ValueError):self.mode.start(floor,hold)
        self.assertEqual(self.events,[])
        self.mode.other_active=lambda:True
        with self.assertRaises(RuntimeError):self.mode.start()
        with self.assertRaises(RuntimeError):self.mode.cancel()
        self.mode.other_active=lambda:False;self.mode.power_pending=lambda:True
        with self.assertRaises(RuntimeError):self.mode.start()
    def test_arm_failure_never_lowers_cpu_and_partial_write_restores(self):
        self.cpu.register.side_effect=RuntimeError('task arm rejected')
        with self.assertRaisesRegex(RuntimeError,'task arm'):self.mode.start()
        self.assertEqual([a[-1] for a in self.events[:-1]],['80','70'])
        self.cpu.register.side_effect=None;self.events.clear();self.mode.start()
        command=self.cpu.command
        def failing(*a):
            if a[0]=='/setdcvalueindex' and a[-1]=='69':raise RuntimeError('write rejected')
            command(*a)
        self.cpu.command=failing;self.advance(1)
        self.assertEqual(self.mode.status()['state'],'failed');self.assertFalse(self.cpu.file.exists())
        self.assertEqual([a[-1] for a in self.events[-3:-1]],['80','70'])
    def test_resume_and_close_restore_and_do_not_restart(self):
        self.mode.start();self.now+=9;self.mode.tick();self.assertFalse(self.mode.status()['active'])
        self.assertIn('resumed',self.mode.status()['error']);self.mode.start();self.advance(2);self.mode.close()
        self.assertFalse(self.cpu.file.exists());self.advance(1);self.assertFalse(self.mode.status()['active'])
    def test_recovery_failure_retained_until_retry(self):
        self.mode.start();command=self.cpu.command;self.cpu.command=Mock(side_effect=RuntimeError('recovery failed'))
        self.mode.cancel();self.assertTrue(self.mode.status()['recoveryPending']);self.assertEqual(self.mode.state,'recovery_needed')
        self.cpu.command=command;self.mode.cancel();self.assertFalse(self.cpu.file.exists())
    def test_independent_deadline_and_missing_record_stop_writes(self):
        self.mode.start(1,60);saved=json.loads(self.cpu.file.read_text());self.assertEqual(saved['deadline'],1174.)
        self.cpu.file.unlink();self.advance(1);self.assertEqual(self.mode.state,'failed');self.assertEqual(self.events,[])
    def test_duplicate_start_and_floor_above_current_rejected(self):
        with self.assertRaises(RuntimeError):self.mode.start(90,30)
        self.assertFalse(self.cpu.file.exists());self.mode.start()
        with self.assertRaises(RuntimeError):self.mode.start()
        self.mode.cancel()

class RouteTests(unittest.TestCase):
    def test_auth_target_relay_and_conflicts(self):
        app=importlib.import_module('test_controls').app
        server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
        def request(path,body=None,key=app.TOKEN,target='local'):
            req=urllib.request.Request('http://127.0.0.1:'+str(server.server_port)+path,headers={'X-Access-Key':key,'X-HomeControl-Device':target,'Content-Type':'application/json'},data=json.dumps(body).encode() if body is not None else None)
            try:
                with urllib.request.urlopen(req) as r:return r.status,json.load(r)
            except urllib.error.HTTPError as e:return e.code,json.load(e)
        try:
            for path,body in [('/api/lag',None),('/api/lag/start',{}),('/api/lag/cancel',{})]:self.assertEqual(request(path,body,key='wrong')[0],401)
            with patch.object(app.gradual_lag,'start',return_value={'active':True}) as start:
                self.assertEqual(request('/api/lag/start',{'floor':15,'hold':20})[0],200);start.assert_called_once_with(15,20)
            with patch.object(app.gradual_lag,'blocked',return_value=True),patch.object(app,'set_power') as power:
                self.assertEqual(request('/api/power',{'value':100})[0],400);power.assert_not_called()
            with patch.object(app.gradual_lag,'active',{'end':100}),patch.object(app.tweakout,'cancel') as cancel:
                self.assertEqual(request('/api/tweakout/cancel',{})[0],400);cancel.assert_not_called()
            with patch.object(app.laptops,'relay',return_value=(200,{'active':True})) as relay:
                self.assertEqual(request('/api/lag/start',{'floor':10,'hold':30},target='other')[0],200)
                relay.assert_called_once_with('other','/api/lag/start',{'floor':10,'hold':30})
        finally:server.shutdown();server.server_close()

if __name__=='__main__':unittest.main()
