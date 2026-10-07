"""Optional elevated acceptance check. Shapes disposable localhost transfers only."""
import http.client
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import sys
import threading
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from network_worker import Shaper

def main():
    payload=b'\0'*(2*1024*1024)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            self.send_response(200);self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
        def do_POST(self):
            left=int(self.headers['Content-Length'])
            while left:
                part=self.rfile.read(min(left,65536))
                if not part:break
                left-=len(part)
            self.send_response(200);self.send_header('Content-Length','0');self.end_headers()
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);port=server.server_port
    threading.Thread(target=server.serve_forever,daemon=True).start();shaper=None
    try:
        # These test-only filters never appear in the authenticated API or normal worker config.
        shaper=Shaper(Path(__file__).resolve().parents[1],4,filters=[f'loopback and tcp and tcp.SrcPort == {port}',f'loopback and tcp and tcp.DstPort == {port}'])
        for method in ('GET','POST'):
            connection=http.client.HTTPConnection('127.0.0.1',port,timeout=20);start=time.monotonic()
            connection.request(method,'/',body=payload if method=='POST' else None)
            response=connection.getresponse();response.read();connection.close()
            speed=len(payload)*8/(time.monotonic()-start)/1_000_000
            print(f'{method}: {speed:.2f} Mbps with a 4 Mbps cap',flush=True)
            assert 2.8<=speed<=4.4,(method,speed,shaper.error)
        assert not shaper.error,shaper.error
        shaper.close();shaper=None
        connection=http.client.HTTPConnection('127.0.0.1',port,timeout=10);start=time.monotonic()
        connection.request('GET','/');connection.getresponse().read();connection.close()
        print(f'After Unlimited: {len(payload)*8/(time.monotonic()-start)/1_000_000:.2f} Mbps',flush=True)
        print('Native network acceptance passed; no internet or HomeControl traffic was shaped.',flush=True)
    finally:
        if shaper:shaper.close()
        server.shutdown();server.server_close()

if __name__=='__main__':main()
