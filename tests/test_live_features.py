import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock,patch

ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from fps_monitor import Frames,FpsMonitor,CHECKSUM
from gpu_load import GpuLoad
from power_controls import PowerActions
from device_controls import Devices,Journal,safe_inventory,INSTANCE

def row(uid,name='Spare',kind='HIDClass',parent='',problem=0,service=''):
    return {'id':uid,'name':name,'class':kind,'parent':parent,'problem':problem,'service':service}
SPARE=r'USB\VID_1234&PID_5678\SPARE'
KEYBOARD=r'HID\VID_1234&PID_5678\KEYS'
NET=r'USB\VID_9999&PID_0001\WIFI'
HUB=r'USB\ROOT_HUB30\ROOT'

class FpsTests(unittest.TestCase):
    def test_rolling_rate_and_most_active_swap_chain(self):
        frames=Frames()
        for n in range(181):
            frames.add('game',n/60,n/60)
            if n%2==0: frames.add('menu',n/60,n/60)
        result=frames.reading(3)
        self.assertEqual(result['fps'],60)
        self.assertEqual(result['swapChain'],'game')
        self.assertLessEqual(result['frameCount'],121)
    def test_no_frames_warmup_and_stale(self):
        f=Frames(); self.assertEqual(f.reading(0)['state'],'no_frames')
        f.add('a',0,0); self.assertEqual(f.reading(0)['state'],'warming_up')
        f.add('a',1,1); self.assertEqual(f.reading(3.1)['state'],'no_frames')
        self.assertIsNone(f.reading(6)['fps']); self.assertFalse(f.chains)
    def test_duplicate_invalid_and_memory_bound(self):
        f=Frames(); f.add('a',0,0); f.add('a',0,0); f.add('a',float('nan'),0)
        self.assertEqual(len(f.chains['a']),1)
        for n in range(9000): f.add('a',n/10000,n/10000)
        self.assertLessEqual(len(f.chains['a']),8192)
    def test_focus_switch_pin_and_exit_clear_history(self):
        with tempfile.TemporaryDirectory() as folder:
            monitor=FpsMonitor(ROOT,Path(folder)); apps=[{'pid':1,'name':'a.exe'},{'pid':2,'name':'b.exe'}]
            monitor.update_target(apps,1)
            monitor.feed({'ProcessID':'1','SwapChainAddress':'a','TimeInSeconds':'0'})
            monitor.update_target(apps,2); self.assertFalse(monitor.frames.chains)
            monitor.pin=1; monitor.update_target(apps,2); self.assertEqual(monitor.target,1)
            monitor.update_target(apps[1:],2); self.assertIsNone(monitor.target)
            self.assertEqual(monitor.status()['application'],'Pinned app exited')
    def test_checksum_and_permissions_and_helper_exit(self):
        import hashlib
        self.assertEqual(hashlib.sha256((ROOT/'vendor/presentmon/PresentMon-2.6.0-x64.exe').read_bytes()).hexdigest(),CHECKSUM)
        with tempfile.TemporaryDirectory() as folder:
            monitor=FpsMonitor(ROOT,Path(folder))
            proc=Mock(); proc.stdout=io.StringIO('Application,ProcessID,SwapChainAddress,TimeInSeconds\n')
            proc.stderr=io.StringIO('Access denied: administrator privileges required\n'); proc.returncode=5
            with patch('fps_monitor.subprocess.Popen',return_value=proc),patch('fps_monitor.CommandJob'):
                monitor._launch()
                for _ in range(30):
                    if monitor.error_state: break
                    time.sleep(.01)
                self.assertEqual(monitor.status()['state'],'insufficient_permissions')
    def test_session_is_dedicated_and_disabled_settings_persist(self):
        with tempfile.TemporaryDirectory() as folder:
            monitor=FpsMonitor(ROOT,Path(folder))
            self.assertTrue(monitor.session.startswith('HomeControlFPS-'))
            with patch('fps_monitor.subprocess.run') as call,patch('fps_monitor.running_apps',return_value=[]):
                monitor.settings(False,None)
                self.assertIn(monitor.session,call.call_args.args[0])
                self.assertIn('--terminate_existing_session',call.call_args.args[0])
            self.assertFalse(FpsMonitor(ROOT,Path(folder)).enabled)
            self.assertIsNone(FpsMonitor(ROOT,Path(folder)).pin)
    def test_corrupt_helper_reports_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            monitor=FpsMonitor(ROOT,Path(folder)); monitor.exe=Path(folder)/'wrong.exe'; monitor.exe.write_bytes(b'bad')
            monitor._launch(); self.assertEqual(monitor.status()['state'],'helper_error')
            self.assertIn('checksum',monitor.status()['error'])

class PowerTests(unittest.TestCase):
    def test_cancel_and_non_forcing_dispatch(self):
        clock=[0]; run=Mock(return_value=Mock(returncode=0)); lock=Mock(return_value=True)
        power=PowerActions(clock=lambda:clock[0],runner=run,locker=lock)
        power.request('restart'); clock[0]=9; power.tick(); run.assert_not_called()
        power.cancel(); clock[0]=11; power.tick(); run.assert_not_called()
        power.request('shutdown'); clock[0]=21; power.tick()
        self.assertEqual(run.call_args.args[0],['shutdown.exe','/s','/t','0'])
        power.request('lock'); lock.assert_called_once()
    def test_invalid_duplicate_and_dispatch_failure(self):
        p=PowerActions(clock=lambda:0,runner=Mock(),locker=Mock(return_value=True))
        with self.assertRaises(ValueError): p.request('sleep')
        p.request('restart')
        with self.assertRaises(RuntimeError): p.request('shutdown')
        p.clock=lambda:11; p.runner=Mock(side_effect=RuntimeError('denied')); p.tick()
        self.assertIn('denied',p.status()['error']); self.assertIsNone(p.status()['pending'])

class GpuLoadTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory(); self.load=GpuLoad(ROOT,Path(self.folder.name))
    def tearDown(self): self.folder.cleanup()
    def test_validation_defaults_and_no_resume(self):
        with patch('gpu_load.adapters',return_value=[{'id':'gpu'}]):
            for duty in (-1,91,False):
                with self.assertRaises(ValueError): self.load.start('gpu',duty)
            with self.assertRaises(ValueError): self.load.start('gpu',25,2)
            with self.assertRaises(ValueError): self.load.start('gone')
            proc=Mock(); proc.poll.return_value=None
            with patch('gpu_load.subprocess.Popen',return_value=proc),patch('gpu_load.CommandJob'):
                self.load.start('gpu'); self.assertEqual(self.load.config['duty'],25)
                self.assertEqual(self.load.config['seconds'],60)
                self.load.update(0); self.load.update(90)
                fresh=GpuLoad(ROOT,Path(self.folder.name)); self.assertFalse(fresh.status()['running'])
                self.load.stop(); self.assertTrue(proc.wait.called)
    def activate(self):
        self.load.process=Mock(); self.load.process.poll.return_value=None; self.load.job=Mock()
        self.load.config={'adapter':'gpu','duty':25}; self.load.end=time.monotonic()+60
    def test_thermal_stop_adapter_loss_timer_and_worker_failure(self):
        for cause in ('heat','loss','timer','failure'):
            self.activate(); gpus=[{'id':'gpu','temperatureC':None}]
            if cause=='heat': gpus[0]['temperatureC']=85
            if cause=='loss': gpus=[]
            if cause=='timer': self.load.end=0
            if cause=='failure': self.load.process.poll.return_value=1
            job=self.load.job; self.load.tick(gpus)
            self.assertFalse(self.load.status()['running']); job.close.assert_called_once()
    def test_start_failure_closes_job(self):
        with patch('gpu_load.adapters',return_value=[{'id':'gpu'}]),patch('gpu_load.CommandJob') as factory,patch('gpu_load.subprocess.Popen',side_effect=OSError('failed')):
            with self.assertRaises(OSError): self.load.start('gpu')
            factory.return_value.close.assert_called_once()
            self.assertFalse(self.load.status()['running'])

class DeviceTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory(); self.data=Path(self.folder.name); self.now=0
        self.rows=[row(SPARE,parent=HUB),row(KEYBOARD,kind='Keyboard',parent=SPARE),row(HUB,kind='USB',service='USBHUB3')]
        self.calls=[]; self.register=Mock()
        def action(verb,uid):
            self.calls.append((verb,uid))
            if verb=='disable':
                self.assertTrue(self.devices.journal.read()[uid]['wasEnabled']); self.register.assert_called()
            for r in self.rows:
                if r['id']==uid: r['problem']=22 if verb=='disable' else 0
            return 'success'
        self.action=action
        self.devices=Devices(self.data,inventory=lambda:self.rows,action=action,register=self.register,clock=lambda:self.now)
    def tearDown(self): self.folder.cleanup()
    def test_protected_devices_network_and_storage_ancestors(self):
        storage=r'USB\DISK\BOOT'; parent=r'USB\COMPOSITE\PARENT'
        rows=self.rows+[row(NET,kind='Net',parent=parent),row(parent,kind='USB'),row(storage,kind='DiskDrive',parent=SPARE)]
        protected={d['id'] for d in safe_inventory(rows) if d['protected']}
        self.assertTrue({NET,parent,storage,SPARE,HUB}.issubset(protected))
        with self.assertRaises(ValueError): self.devices.select({'usb':[HUB],'keyboard':[]})
        self.assertFalse(INSTANCE.fullmatch('USB\\device;shutdown'))
    def test_combined_deduplication_and_recovery_after_sixty_seconds(self):
        self.devices.select({'usb':[KEYBOARD],'keyboard':[KEYBOARD]})
        result=self.devices.perform('both','disable')
        self.assertEqual(len(result['results']),1); self.assertEqual(self.calls,[('disable',KEYBOARD)])
        self.now=59; self.devices.reconcile(); self.assertEqual(len(self.calls),1)
        # A fresh journal represents the independent process after app termination.
        self.now=60; Journal(self.data,lambda:self.now).recover(self.action,lambda:self.rows)
        self.assertEqual(self.calls[-1],('enable',KEYBOARD)); self.assertEqual(self.devices.journal.read(),{})
    def test_task_arm_failure_prevents_disable(self):
        self.devices.select({'usb':[SPARE],'keyboard':[]}); self.register.side_effect=RuntimeError('task registration failed')
        result=self.devices.perform('usb','disable')
        self.assertFalse(result['results'][0]['ok']); self.assertFalse(self.calls); self.assertEqual(self.devices.journal.read(),{})
    def test_partial_failures_and_disconnected_recovery_retains_records(self):
        self.devices.select({'usb':[SPARE],'keyboard':[KEYBOARD]})
        def partial(action,uid):
            if uid==SPARE:
                self.rows[0]['problem']=22  # A partially completed disable before failure.
                raise RuntimeError('unplugged')
            return self.action(action,uid)
        self.devices.action=partial; result=self.devices.perform('both','disable')
        self.assertEqual([r['ok'] for r in result['results']],[False,True])
        self.now=61; self.rows=[r for r in self.rows if r['id']!=KEYBOARD]
        self.devices.reconcile(); records=self.devices.journal.read()
        self.assertIn(SPARE,records); self.assertIn(KEYBOARD,records)
        self.assertIn('disconnected',records[KEYBOARD]['error'].lower())
        self.rows.append(row(KEYBOARD,kind='Keyboard',parent=SPARE,problem=22))
        self.devices.action=self.action; self.devices.reconcile(); self.assertEqual(self.devices.journal.read(),{})
    def test_already_disabled_not_added_to_recovery_and_stale_selection_rejected(self):
        self.rows[0]['problem']=22; self.devices.select({'usb':[SPARE],'keyboard':[]})
        self.devices.perform('usb','disable'); self.assertFalse(self.calls); self.assertEqual(self.devices.journal.read(),{})
        self.rows[0]['class']='Net'; result=self.devices.perform('usb','restart')
        self.assertFalse(result['results'][0]['ok']); self.assertFalse(self.calls)
    def test_empty_selections_and_unvalidated_ids(self):
        self.assertEqual(self.devices.selections,{'usb':[],'keyboard':[]})
        with self.assertRaises(ValueError): self.devices.perform('both','disable')
        with self.assertRaises(ValueError): self.devices.select({'usb':['made-up'],'keyboard':[]})

if __name__=='__main__': unittest.main(verbosity=2)
