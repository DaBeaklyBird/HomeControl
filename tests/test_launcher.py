import importlib
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import Mock,patch
import json
import urllib.request
import urllib.error

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app_launcher import AppLauncher

class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.rows=[{'name':'Calculator','kind':'app','target':'Windows.Calculator!App','source':'Start menu'},
                   {'name':'Spare game','kind':'shortcut','target':r'C:\Users\tester\Desktop\Spare.url','source':'Desktop game shortcut'}]
        self.inventory=Mock(return_value=self.rows);self.dispatch=Mock()
        self.launcher=AppLauncher(self.inventory,self.dispatch)
    def test_inventory_redacts_paths_stable_ids_and_launches_selected_app(self):
        result=self.launcher.refresh();self.assertTrue(result['ready']);self.assertEqual(len(result['apps']),2)
        self.assertNotIn('target',json.dumps(result));self.assertNotIn('Desktop\\',json.dumps(result))
        game=next(app for app in result['apps'] if app['name']=='Spare game')
        self.launcher.refresh();self.assertIn(game,self.launcher.status()['apps'])
        result=self.launcher.launch(game['id']);self.assertTrue(result['requested'])
        self.dispatch.assert_called_once_with(self.rows[1])
    def test_invalid_and_unknown_ids_never_dispatch(self):
        self.launcher.refresh()
        for uid in (None,True,'powershell.exe','a'*24,{'target':'cmd.exe'}):
            with self.assertRaises(ValueError):self.launcher.launch(uid)
        self.dispatch.assert_not_called()
    def test_removed_apps_and_native_rejection_are_reported(self):
        uid=self.launcher.refresh()['apps'][0]['id'];self.inventory.return_value=[];self.launcher.refresh()
        with self.assertRaises(ValueError):self.launcher.launch(uid)
        self.inventory.return_value=self.rows;uid=self.launcher.refresh()['apps'][0]['id']
        self.dispatch.side_effect=RuntimeError('App was uninstalled')
        with self.assertRaisesRegex(RuntimeError,'uninstalled'):self.launcher.launch(uid)
        self.dispatch.side_effect=None;self.assertTrue(self.launcher.launch(uid)['requested'])
    def test_discovery_failure_retains_cached_inventory_and_reports_error(self):
        previous=self.launcher.refresh()['apps'];self.inventory.side_effect=RuntimeError('Windows unavailable')
        state=self.launcher.refresh();self.assertEqual(state['apps'],previous);self.assertIn('unavailable',state['error'])
    def test_refresh_and_launch_serialize_without_blocking_cached_status(self):
        uid=self.launcher.refresh()['apps'][0]['id'];self.launcher.action_lock.acquire()
        try:
            self.assertEqual(len(self.launcher.status()['apps']),2)
            self.assertTrue(self.launcher.refresh()['ready'])
            with self.assertRaisesRegex(RuntimeError,'in progress'):self.launcher.launch(uid)
        finally:self.launcher.action_lock.release()
        self.assertTrue(self.launcher.launch(uid)['requested'])
    def test_malformed_and_duplicate_inventory_entries(self):
        self.inventory.return_value=self.rows+[self.rows[0],None,{'name':'injected','kind':'command','target':'cmd.exe','source':'bad'},
            {'name':'bad','kind':'app','target':'bad\ncommand','source':'Start menu'}]
        self.assertEqual(len(self.launcher.refresh()['apps']),2)
    def test_authenticated_launcher_and_relay_routes(self):
        app=importlib.import_module('test_controls').app
        server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        def request(path,body=None,key=app.TOKEN,target='local'):
            req=urllib.request.Request('http://127.0.0.1:'+str(server.server_port)+path,
                headers={'X-Access-Key':key,'X-HomeControl-Device':target,'Content-Type':'application/json'},data=json.dumps(body).encode() if body is not None else None)
            try:
                with urllib.request.urlopen(req) as response:return response.status,json.load(response)
            except urllib.error.HTTPError as error:return error.code,json.load(error)
        try:
            for path,body in [('/api/apps',None),('/api/apps/refresh',{}),('/api/apps/launch',{'id':'a'*24})]:
                self.assertEqual(request(path,body,key='wrong')[0],401)
            self.assertEqual(request('/api/apps/launch',{'target':'cmd.exe'})[0],400)
            with patch.object(app,'launcher',self.launcher):
                self.assertTrue(request('/api/apps/refresh',{})[1]['ready'])
                uid=request('/api/apps')[1]['apps'][0]['id']
                self.assertEqual(request('/api/apps/launch',{'id':uid})[0],200)
                self.dispatch.assert_called_once()
            with patch.object(app.laptops,'relay',return_value=(200,{'requested':True})) as relay:
                self.assertEqual(request('/api/apps/launch',{'id':'a'*24},target='desktop')[0],200)
                relay.assert_called_once_with('desktop','/api/apps/launch',{'id':'a'*24})
        finally:server.shutdown();server.server_close()

if __name__=='__main__':unittest.main(verbosity=2)
