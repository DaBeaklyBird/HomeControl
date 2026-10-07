import json
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from laptop_controls import Laptops,laptop_url,request_target

class LaptopTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.request=Mock(return_value=(200,{'apps':[],'active':'Test app'}))
        self.laptops=Laptops(self.folder.name,'Development',self.request)
    def tearDown(self):self.folder.cleanup()
    def test_lan_addresses_only_no_embedded_credentials_or_redirects(self):
        self.assertEqual(laptop_url('192.168.4.71:8765/'),'http://192.168.4.71:8765')
        for url in ['http://8.8.8.8:8765','http://127.0.0.1:8765','http://169.254.1.1:8765',
                    'https://192.168.1.1:8765','http://host:8765','http://192.168.1.1:80',
                    'http://user:key@192.168.1.1:8765','http://192.168.1.1:8765/#key=secret','file:///test']:
            with self.assertRaises(ValueError):laptop_url(url)
    def test_saved_targets_survive_restart_without_exposing_keys(self):
        result=self.laptops.add('Gaming','192.168.4.71:8765','private-target-key')
        uid=result['laptops'][1]['id'];self.assertNotIn('private-target-key',json.dumps(result))
        restored=Laptops(self.folder.name,'Development',self.request)
        self.assertEqual(restored.status(),result)
        restored.relay(uid,'/api/power',{'value':15})
        self.assertEqual(self.request.call_args.args,({'name':'Gaming','url':'http://192.168.4.71:8765','key':'private-target-key'},'/api/power',{'value':15}))
        restored.remove(uid);self.assertEqual(len(restored.status()['laptops']),1)
        with self.assertRaises(ValueError):restored.relay(uid,'/api/status')
    def test_rejected_key_invalid_service_and_duplicate_not_saved(self):
        for response in [(401,{'error':'Wrong key'}),(200,{'hello':'other service'})]:
            self.request.return_value=response
            with self.assertRaises(ValueError):self.laptops.add('Gaming','192.168.4.71:8765','private-target-key')
            self.assertEqual(len(self.laptops.status()['laptops']),1)
        self.request.return_value=(200,{'apps':[],'active':'app'})
        self.laptops.add('Gaming','192.168.4.71:8765','private-target-key')
        with self.assertRaises(ValueError):self.laptops.add('Duplicate','192.168.4.71:8765','private-target-key')
    def test_relay_does_not_follow_redirect_or_send_credentials_to_redirect_target(self):
        seen=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                seen.append((self.path,self.headers.get('X-Access-Key')))
                self.send_response(302);self.send_header('Location','/stolen');self.end_headers()
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        try:
            with self.assertRaisesRegex(ValueError,'redirect'):
                request_target({'url':'http://127.0.0.1:'+str(server.server_port),'key':'test-target-key'},'/api/status')
            self.assertEqual(seen,[('/api/status','test-target-key')])
        finally:server.shutdown();server.server_close()
    def test_relay_controls_belong_to_chosen_laptop_and_hub_remains_authenticated(self):
        import server as app
        hub=ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        threading.Thread(target=hub.serve_forever,daemon=True).start()
        import urllib.request,urllib.error
        def request(path,key=app.TOKEN,body=None):
            req=urllib.request.Request('http://127.0.0.1:'+str(hub.server_port)+path,
                data=json.dumps(body).encode() if body is not None else None,
                headers={'X-Access-Key':key,'X-HomeControl-Device':'gaming','Content-Type':'application/json'})
            try:
                with urllib.request.urlopen(req) as response:return response.status,json.load(response)
            except urllib.error.HTTPError as exc:return exc.code,json.load(exc)
        try:
            with patch.object(app.laptops,'relay',return_value=(200,{'source':'gaming'})) as relay:
                self.assertEqual(request('/api/metrics',key='wrong')[0],401);relay.assert_not_called()
                self.assertEqual(request('/api/metrics')[1],{'source':'gaming'})
                relay.assert_called_with('gaming','/api/metrics')
                self.assertEqual(request('/api/terminal',body={'command':'Write-Output test'})[0],200)
                relay.assert_called_with('gaming','/api/terminal',{'command':'Write-Output test'})
                self.assertEqual(request('/api/laptops')[1]['laptops'][0]['id'],'local')
                relay.return_value=(401,{'error':'Target key rejected'})
                self.assertEqual(request('/api/metrics')[0],502)
        finally:hub.shutdown();hub.server_close()

if __name__=='__main__':unittest.main()
