import ctypes as C
import unittest
from unittest.mock import Mock,patch
import remote_keyboard as keyboard

class KeyboardTests(unittest.TestCase):
    def test_unicode_and_key_pairs(self):
        api=Mock();captured=[]
        def send(count,events,size):
            captured.extend((e.keyboard.vk,e.keyboard.scan,e.keyboard.flags) for e in events)
            self.assertEqual(size,C.sizeof(keyboard.Input));return count
        api.SendInput.side_effect=send
        with patch('remote_keyboard.C.WinDLL',return_value=api):
            self.assertEqual(keyboard.send({'kind':'text','text':'A😀'})['sent'],3)
            self.assertEqual([x[2] for x in captured],[4,6,4,6,4,6])
            keyboard.send({'kind':'key','key':'Enter'})
            self.assertEqual(captured[-2:],[(13,0,0),(13,0,2)])
    def test_rejects_invalid_and_reports_blocked_input(self):
        for body in ({},{'kind':'text','text':''},{'kind':'text','text':'x'*1001},{'kind':'key','key':'anything'}):
            with self.assertRaises(ValueError):keyboard.send(body)
        api=Mock();api.SendInput.return_value=0
        with patch('remote_keyboard.C.WinDLL',return_value=api):
            with self.assertRaises(RuntimeError):keyboard.send({'kind':'key','key':'Tab'})
