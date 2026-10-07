"""A local HomeControl dashboard can relay authenticated controls to saved LAN laptops."""
import ipaddress
import json
from pathlib import Path
import secrets
import threading
from urllib.error import HTTPError,URLError
from urllib.parse import urlsplit
from urllib.request import Request,build_opener,ProxyHandler,HTTPRedirectHandler
from win_support import atomic_json

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

def laptop_url(value):
    if not isinstance(value,str) or len(value)>200:raise ValueError('Enter the other laptop’s home-network address, for example http://192.168.4.71:8765/')
    try:
        parsed=urlsplit(value if '://' in value else 'http://'+value)
        ip=ipaddress.IPv4Address(parsed.hostname)
        private=any(ip in ipaddress.ip_network(n) for n in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16'))
        if not (private and parsed.scheme=='http' and parsed.port==8765 and not parsed.username
                and not parsed.password and not parsed.query and not parsed.fragment and parsed.path in ('','/')):raise ValueError()
        return 'http://'+str(ip)+':8765'
    except (ValueError,TypeError):raise ValueError('Use a home-network IPv4 address on port 8765, without a key in the URL.') from None

def request_target(target,path,body=None):
    # Ignore system proxies and redirects so credentials reach only the configured LAN laptop.
    opener=build_opener(ProxyHandler({}),NoRedirect())
    request=Request(target['url']+path,data=json.dumps(body).encode() if body is not None else None,
                    headers={'X-Access-Key':target['key'],**({'Content-Type':'application/json'} if body is not None else {})})
    try:
        with opener.open(request,timeout=35) as response:
            raw=response.read(2_000_001)
            if len(raw)>2_000_000:raise ValueError('The other laptop returned too much data.')
            return response.status,json.loads(raw)
    except HTTPError as exc:
        if exc.code in (301,302,303,307,308):raise ValueError('Laptop redirects are refused; check its address.') from None
        if exc.code==401:return 401,{'error':'The saved key for this laptop was rejected. Remove it and add it again with its current key.'}
        try:return exc.code,json.loads(exc.read(65536))
        except (ValueError,TypeError):return 502,{'error':'The other laptop returned an invalid response.'}
    except (URLError,TimeoutError,OSError):raise ValueError('Cannot reach the other laptop. Keep it awake with HomeControl running on the same home network.') from None

class Laptops:
    def __init__(self,data,hostname,request=request_target):
        self.path=Path(data)/'laptops.json';self.hostname=hostname;self.request=request;self.lock=threading.RLock()
        try:self.targets=json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError,ValueError):self.targets={}
    def status(self):
        with self.lock:return {'laptops':[{'id':'local','name':self.hostname+' · this laptop','url':None}]+
            [{'id':uid,'name':t['name'],'url':t['url']} for uid,t in self.targets.items()]}
    def add(self,name,url,key):
        if not isinstance(name,str) or not 1<=len(name.strip())<=60:raise ValueError('Enter a laptop name, up to 60 characters.')
        if not isinstance(key,str) or not 12<=len(key.strip())<=200:raise ValueError('Enter the HomeControl access key shown on the other laptop.')
        target={'name':name.strip(),'url':laptop_url(url),'key':key.strip()}
        code,response=self.request(target,'/api/status')
        if code!=200:raise ValueError(response.get('error','The other laptop rejected this connection.'))
        if not isinstance(response,dict) or 'apps' not in response or 'active' not in response:raise ValueError('This address is not a HomeControl laptop.')
        with self.lock:
            if any(t['url']==target['url'] for t in self.targets.values()):raise ValueError('This address is already saved. Remove it to change its key.')
            if len(self.targets)>=15:raise ValueError('Up to 16 laptops can be saved.')
            uid=secrets.token_hex(8);self.targets[uid]=target
            try:atomic_json(self.path,self.targets,private=True)
            except Exception:self.targets.pop(uid);raise
            return self.status()
    def remove(self,uid):
        with self.lock:
            if uid not in self.targets:raise ValueError('Select a saved laptop to remove.')
            target=self.targets.pop(uid)
            try:atomic_json(self.path,self.targets,private=True)
            except Exception:self.targets[uid]=target;raise
            return self.status()
    def relay(self,uid,path,body=None):
        with self.lock:
            if uid not in self.targets:raise ValueError('Unknown laptop. Choose a saved laptop from the list.')
            target=dict(self.targets[uid])
        target['url']=laptop_url(target['url'])
        if not path.startswith('/api/') or '?' in path or '#' in path:raise ValueError('Invalid laptop control endpoint.')
        return self.request(target,path,body)
