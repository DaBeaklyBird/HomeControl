"""Use disposable data and mock every laptop CPU write and shutdown."""
import importlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
import urllib.error
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tweakout import CpuRecovery, Effects, Tweakout
from power_controls import PowerActions

SCHEME='381b4222-f694-41f0-9685-ff5bb260df2e'

class ModeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.data=Path(self.tmp.name);self.now=100.;self.events=[]
        self.cpu=CpuRecovery(self.data,read=lambda:(SCHEME,[80,70]),
            command=lambda *args:self.events.append(('cpu',args)),
            register=lambda *args:self.events.append(('armed',args)),clock=lambda:1000.)
        self.effects=Mock();self.effects.reading.return_value={};self.effects.healthy.return_value=True;self.effects.stale.return_value=False
        self.shutdown=Mock(side_effect=lambda:self.events.append(('shutdown',)))
        self.mode=Tweakout(ROOT,self.data,self.shutdown,cpu=self.cpu,effects=self.effects,clock=lambda:self.now)
    def test_confirmation_and_boolean_validation(self):
        for args in ({},{'preview':'false'},{'confirmed':1}):
            with self.assertRaises(ValueError):self.mode.start(**args)
        self.effects.launch.assert_not_called();self.assertEqual(self.events,[])
    def test_preview_has_no_cpu_writes_or_shutdown(self):
        state=self.mode.start(preview=True)
        self.assertEqual(state['seconds'],12);self.assertTrue(state['preview'])
        self.now+=12;self.mode.tick()
        self.assertEqual(self.mode.status()['state'],'preview_finished');self.assertEqual(self.events,[])
        self.shutdown.assert_not_called();self.effects.close.assert_called_once()
    def test_cancel_restores_exact_prior_values_and_closes_effects(self):
        state=self.mode.start(confirmed=True)
        self.assertEqual(state['seconds'],20);self.assertTrue(self.cpu.file.exists())
        self.assertEqual(self.events[0][0],'armed');self.assertEqual(self.events[1][1][-1],'1')
        self.mode.cancel();self.now+=25;self.mode.tick()
        self.assertEqual([entry[1][-1] for entry in self.events[-3:-1]],['80','70'])
        self.shutdown.assert_not_called();self.effects.close.assert_called_once();self.assertFalse(self.cpu.file.exists())
    def test_expiry_restores_before_nonforcing_shutdown_once(self):
        self.mode.start(confirmed=True);self.now+=19;self.mode.tick();self.shutdown.assert_not_called()
        self.now+=1;self.mode.tick();self.mode.tick()
        self.assertEqual(self.events[-1],('shutdown',));self.assertEqual(self.events[-2][1][0],'/setactive')
        self.assertFalse(self.cpu.file.exists());self.shutdown.assert_called_once()
    def test_worker_exit_or_resume_stall_cancels_shutdown(self):
        for stale in (False,True):
            self.effects.reset_mock();self.effects.healthy.return_value=True;self.effects.stale.return_value=False
            self.mode.start(confirmed=True)
            if stale:self.effects.stale.return_value=True;self.now+=30
            else:self.effects.healthy.return_value=False
            self.mode.tick();self.assertEqual(self.mode.status()['state'],'failed')
            self.assertFalse(self.cpu.file.exists());self.shutdown.assert_not_called()
    def test_failed_effect_start_does_not_apply_cpu(self):
        self.effects.launch.side_effect=RuntimeError('helper failure')
        with self.assertRaisesRegex(RuntimeError,'helper failure'):self.mode.start(confirmed=True)
        self.assertEqual(self.events,[]);self.shutdown.assert_not_called();self.effects.close.assert_called_once()
    def test_failed_recovery_arm_never_writes_one_percent(self):
        self.cpu.register=Mock(side_effect=RuntimeError('not elevated'))
        with self.assertRaisesRegex(RuntimeError,'not elevated'):self.mode.start(confirmed=True)
        self.assertEqual([entry[1][-1] for entry in self.events[:-1]],['80','70'])
        self.assertFalse(self.cpu.file.exists());self.shutdown.assert_not_called()
    def test_partial_cpu_write_failure_recovers(self):
        def command(*args):
            self.events.append(('cpu',args))
            if args[0]=='/setdcvalueindex' and args[-1]=='1':raise RuntimeError('partial failure')
        self.cpu.command=command
        with self.assertRaisesRegex(RuntimeError,'partial failure'):self.mode.start(confirmed=True)
        self.assertEqual([entry[1][-1] for entry in self.events[-3:-1]],['80','70'])
        self.assertFalse(self.cpu.file.exists());self.shutdown.assert_not_called()
    def test_failed_restore_retains_record_and_prevents_shutdown_until_retry(self):
        self.mode.start(confirmed=True)
        original=self.cpu.command;self.cpu.command=Mock(side_effect=RuntimeError('restore rejected'))
        self.now+=20;self.mode.tick()
        self.assertEqual(self.mode.status()['state'],'recovery_needed');self.assertTrue(self.cpu.file.exists())
        self.shutdown.assert_not_called();self.cpu.command=original
        self.mode.cancel();self.assertFalse(self.cpu.file.exists());self.assertFalse(self.mode.blocked())
    def test_independent_recovery_deadline_and_startup_reconciliation(self):
        self.mode.start(confirmed=True);self.cpu.restore();self.assertTrue(self.cpu.file.exists())
        recovered=CpuRecovery(self.data,command=lambda *args:self.events.append(('recovered',args)),clock=lambda:1060.)
        recovered.restore();self.assertFalse(self.cpu.file.exists())
        self.mode.active=None;self.cpu.apply();self.mode.reconcile();self.assertFalse(self.cpu.file.exists())
    def test_shutdown_rejection_still_leaves_cpu_restored(self):
        self.shutdown.side_effect=RuntimeError('Windows rejected shutdown')
        self.mode.start(confirmed=True);self.now+=20;self.mode.tick()
        self.assertEqual(self.mode.status()['state'],'failed');self.assertFalse(self.cpu.file.exists())
        self.assertIn('rejected shutdown',self.mode.status()['error'])
    def test_duplicate_power_action_and_close_do_not_shutdown(self):
        self.mode.power_pending=lambda:True
        with self.assertRaisesRegex(RuntimeError,'pending power'):self.mode.start(preview=True)
        self.effects.launch.assert_not_called();self.mode.power_pending=lambda:False
        self.mode.start(confirmed=True)
        with self.assertRaises(RuntimeError):self.mode.start(preview=True)
        self.mode.close();self.now+=25;self.mode.tick();self.shutdown.assert_not_called()
        self.assertFalse(self.cpu.file.exists())
    def test_corrupt_recovery_record_is_retained(self):
        self.cpu.file.write_text(json.dumps({'scheme':SCHEME,'values':[80,True],'deadline':0}))
        self.mode.reconcile();self.assertEqual(self.mode.status()['state'],'recovery_needed')
        self.assertTrue(self.cpu.file.exists());self.assertEqual(self.events,[])

class IntegrationTests(unittest.TestCase):
    def test_helper_ignores_another_session_and_detects_stall(self):
        with tempfile.TemporaryDirectory() as data:
            effects=Effects(ROOT,data);effects.mode_id='current';effects.process=Mock();effects.process.poll.return_value=None
            effects.result.write_text(json.dumps({'id':'old','ready':True,'heartbeat':100.}))
            self.assertEqual(effects.reading(),{})
            effects.result.write_text(json.dumps({'id':'current','ready':True,'heartbeat':100.}))
            with patch('tweakout.time.time',return_value=104.):self.assertTrue(effects.healthy());self.assertFalse(effects.stale())
            with patch('tweakout.time.time',return_value=106.):self.assertFalse(effects.healthy());self.assertTrue(effects.stale())
    def test_direct_shutdown_uses_zero_timeout_and_no_force(self):
        runner=Mock(return_value=subprocess.CompletedProcess([],0,b'',b''))
        power=PowerActions(runner=runner,locker=lambda:True);power.execute('shutdown')
        self.assertEqual(runner.call_args.args[0],['shutdown.exe','/s','/t','0'])
        power.request('restart')
        with self.assertRaises(RuntimeError):power.execute('shutdown')
        self.assertEqual(runner.call_count,1)
    def test_routes_require_key_confirm_and_block_conflicting_controls(self):
        # test_controls initializes the server against disposable runtime data.
        app=importlib.import_module('test_controls').app
        server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        def request(path,body=None,key=app.TOKEN):
            req=urllib.request.Request('http://127.0.0.1:'+str(server.server_port)+path,
                headers={'X-Access-Key':key,'Content-Type':'application/json'},data=json.dumps(body).encode() if body is not None else None)
            try:
                with urllib.request.urlopen(req) as response:return response.status,json.load(response)
            except urllib.error.HTTPError as error:return error.code,json.load(error)
        try:
            for path,body in [('/api/tweakout',None),('/api/tweakout/start',{}),('/api/tweakout/cancel',{})]:
                self.assertEqual(request(path,body,key='wrong')[0],401)
            self.assertEqual(request('/api/tweakout/start',{})[0],400)
            with patch.object(app.tweakout,'start',return_value={'active':True}) as start:
                self.assertEqual(request('/api/tweakout/start',{'confirmed':True})[0],200)
                start.assert_called_once_with(False,True)
            with patch.object(app.tweakout,'blocked',return_value=True),patch.object(app,'set_power') as cpu,patch.object(app.tweakout,'cancel',return_value={'active':False}) as cancel:
                self.assertEqual(request('/api/power',{'value':100})[0],400)
                self.assertEqual(request('/api/limits/remove',{'app':'sample.exe'})[0],400)
                self.assertEqual(request('/api/power/action',{'action':'shutdown'})[0],400)
                self.assertEqual(request('/api/tweakout/cancel',{})[0],200)
                cpu.assert_not_called();cancel.assert_called_once()
            with patch.object(app.laptops,'relay',return_value=(200,{'active':True})) as relay:
                req=urllib.request.Request('http://127.0.0.1:'+str(server.server_port)+'/api/tweakout/start',
                    headers={'X-Access-Key':app.TOKEN,'X-HomeControl-Device':'other','Content-Type':'application/json'},data=b'{"preview":true}')
                with urllib.request.urlopen(req) as response:self.assertTrue(json.load(response)['active'])
                relay.assert_called_once_with('other','/api/tweakout/start',{'preview':True})
        finally:server.shutdown();server.server_close()

if __name__=='__main__':unittest.main(verbosity=2)
