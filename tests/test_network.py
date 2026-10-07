import ctypes as C
import ipaddress
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch,Mock
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from network_native import Pace,validate_rate,packet_filter,Divert,Address
from network_limit import NetworkLimit
from network_worker import Shaper

class NetworkTests(unittest.TestCase):
    def test_rate_units_boundaries_and_invalid_values(self):
        self.assertIsNone(validate_rate(None))
        for value in [.1,1,20.5,1000]:self.assertEqual(validate_rate(value),value)
        for value in [True,False,0,-1,1001,.11,float('nan'),float('inf'),'1']:
            with self.assertRaises(ValueError):validate_rate(value)
        now=[0.0];pace=Pace(1,lambda:now[0])
        self.assertEqual(pace.delay(125000),1)
        now[0]=.5;self.assertEqual(pace.delay(125000),1.5)
        now[0]=10;self.assertAlmostEqual(pace.delay(125000),.99)  # Idle credit is bounded to 10 ms.
        pace.set_rate(.1);self.assertAlmostEqual(pace.delay(1250),.1)
    def test_native_filters_exclude_home_network_and_dashboard(self):
        api=Divert(ROOT)
        for direction in ('inbound','outbound'):api.check_filter(packet_filter(direction))
        def packet(source,destination,source_port=50000,destination_port=443,udp=False):
            src=ipaddress.ip_address(source);dst=ipaddress.ip_address(destination)
            tcp=struct.pack('!HHLLBBHHH',source_port,destination_port,0,0,80,24,4096,0,0)+b'payload'
            if udp:tcp=struct.pack('!HHHH',source_port,destination_port,15,0)+b'payload'
            if src.version==4:
                return struct.pack('!BBHHHBBH4s4s',69,0,20+len(tcp),0,0,64,17 if udp else 6,0,src.packed,dst.packed)+tcp
            return struct.pack('!IHBB16s16s',6<<28,len(tcp),17 if udp else 6,64,src.packed,dst.packed)+tcp
        def matches(data,outbound=True):
            address=Address();address.flags=(1<<17 if outbound else 0)|(1<<20 if data[0]>>4==6 else 0)
            return bool(api.api.WinDivertHelperEvalFilter(packet_filter('outbound' if outbound else 'inbound').encode(),data,len(data),C.byref(address)))
        self.assertTrue(matches(packet('192.168.4.34','8.8.8.8')))
        self.assertFalse(matches(packet('192.168.4.34','192.168.4.20')))
        self.assertFalse(matches(packet('192.168.4.34','10.0.0.1')))
        self.assertFalse(matches(packet('192.168.4.34','100.90.10.20')))
        self.assertTrue(matches(packet('192.168.4.34','8.8.8.8',41641,50000,True)))
        self.assertTrue(matches(packet('192.168.4.34','8.8.8.8',50000,443,True)))
        self.assertFalse(matches(packet('192.168.4.34','8.8.8.8',8765)))
        self.assertTrue(matches(packet('8.8.8.8','192.168.4.34'),False))
        self.assertFalse(matches(packet('192.168.4.20','192.168.4.34'),False))
        self.assertTrue(matches(packet('2001:4860::1','2606:4700::1111')))
        self.assertFalse(matches(packet('2001:4860::1','fe80::1')))
        self.assertFalse(matches(packet('2001:4860::1','fd00::1')))
    def test_worker_handles_are_closed_on_partial_start_failure(self):
        divert=Mock();divert.open.side_effect=[123,RuntimeError('blocked')]
        with self.assertRaisesRegex(RuntimeError,'blocked'):Shaper(ROOT,1,divert=divert)
        divert.shutdown.assert_called_once_with(123);divert.close.assert_called_once_with(123)
    def test_default_unlimited_existing_files_do_not_resume(self):
        with tempfile.TemporaryDirectory() as folder:
            data=Path(folder);(data/'network-limit-control.json').write_text('{"mbps":1}')
            control=NetworkLimit(ROOT,data)
            self.assertIsNone(control.status()['mbps']);self.assertFalse(control.status()['running'])
            self.assertEqual(control.apply(None)['reason'],'Unlimited')
            with self.assertRaises(ValueError):control.apply(0)
    def test_crash_stall_and_unlimited_cleanup(self):
        with tempfile.TemporaryDirectory() as folder:
            control=NetworkLimit(ROOT,Path(folder));process=Mock();job=Mock()
            control.process=process;control.job=job;control.config={'mbps':1,'session':'abc'}
            process.poll.return_value=None
            control.result.write_text(json.dumps({'session':'abc','running':True,'heartbeat':0.1,'error':'worker stalled'}))
            control.tick();self.assertFalse(control.status()['running']);job.close.assert_called_once()
            self.assertIn('stalled',control.status()['error'])
            control.process=process;control.job=Mock();control.config={'mbps':10,'session':'new'}
            process.poll.return_value=1;control.tick();self.assertIsNone(control.status()['mbps'])
    def test_failed_start_restores_unlimited_and_closes_job_once(self):
        with tempfile.TemporaryDirectory() as folder:
            control=NetworkLimit(ROOT,Path(folder));process=Mock();process.poll.return_value=1;job=Mock()
            with patch('network_limit.CommandJob',return_value=job),patch('network_limit.subprocess.Popen',return_value=process):
                with self.assertRaisesRegex(RuntimeError,'did not become ready'):control.apply(1)
            job.close.assert_called_once();self.assertFalse(control.status()['running'])
            self.assertIsNone(control.status()['mbps'])

if __name__=='__main__':unittest.main(verbosity=2)
