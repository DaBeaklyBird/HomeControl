"""Launch registered Windows apps and local desktop shortcuts through Explorer."""
import hashlib
import json
import threading
from win_support import powershell,ps_config

INVENTORY=r'''
$items=@(Get-StartApps | ForEach-Object {
    if($_.Name -and $_.AppID){[pscustomobject]@{name=$_.Name;kind='app';target=$_.AppID;source='Start menu'}}
})
$folders=@([Environment]::GetFolderPath('DesktopDirectory'),[Environment]::GetFolderPath('CommonDesktopDirectory')) | Select-Object -Unique
foreach($folder in $folders){
    if($folder -and (Test-Path -LiteralPath $folder)){
        foreach($file in @(Get-ChildItem -LiteralPath $folder -File)){
            if(($file.Attributes -band 0x1000) -or ($file.Attributes -band 0x400000)){continue}
            if($file.Extension -eq '.lnk'){
                $items += [pscustomobject]@{name=$file.BaseName;kind='shortcut';target=$file.FullName;source='Desktop shortcut'}
            }elseif($file.Extension -eq '.url'){
                try{$url=Get-Content -LiteralPath $file.FullName | Where-Object {$_ -match '^URL='} | Select-Object -First 1}catch{continue}
                if($url -and $url.Substring(4) -match '^(steam://rungameid/[0-9]+|com\.epicgames\.launcher://apps/[^\s]+)$'){
                    $items += [pscustomobject]@{name=$file.BaseName;kind='shortcut';target=$file.FullName;source='Desktop game shortcut'}
                }
            }
        }
    }
}
'''

def discover():
    result=json.loads(powershell(INVENTORY+"ConvertTo-Json -InputObject @($items) -Compress",timeout=20) or '[]')
    if not isinstance(result,list):raise RuntimeError('Windows returned an invalid application list.')
    return result

def launch_native(app):
    # Re-enumerate at dispatch time; a stale browser ID cannot inject paths or arguments.
    script=ps_config(app)+INVENTORY+r'''
    $found=@($items | Where-Object {$_.kind -eq $cfg.kind -and $_.target -ceq $cfg.target})
    if($found.Count -eq 0){throw 'This app or shortcut is no longer installed. Refresh the app list.'}
    $shell=New-Object -ComObject Shell.Application
    $hwnd=0
    $desktop=$shell.Windows().FindWindowSW(0,0,8,[ref]$hwnd,1)
    if(-not $desktop){throw 'Sign in to the Windows desktop before launching apps.'}
    $target=if($cfg.kind -eq 'app'){'shell:AppsFolder\'+$cfg.target}else{$cfg.target}
    # Use the desktop shell's automation object so apps run in Explorer's ordinary user context.
    $desktop.Document.Application.ShellExecute($target,'','','open',1)
    Write-Output 'Launch requested'
    '''
    powershell(script,timeout=20)

class AppLauncher:
    def __init__(self,inventory=discover,launch=launch_native):
        self.inventory=inventory;self.dispatch=launch;self.lock=threading.RLock();self.action_lock=threading.Lock()
        self.apps={};self.error='';self.ready=False
    def refresh(self):
        if not self.action_lock.acquire(blocking=False):return self.status()
        try:
            try:
                items={}
                for app in self.inventory()[:2000]:
                    if not isinstance(app,dict) or app.get('kind') not in ('app','shortcut'):continue
                    if any(not isinstance(app.get(key),str) or not app[key] or len(app[key])>4096 for key in ('name','target','source')):continue
                    if any(char in app['target'] for char in ('\0','\r','\n')):continue
                    uid=hashlib.sha256((app['kind']+'\0'+app['target']).encode()).hexdigest()[:24]
                    items[uid]={key:app[key] for key in ('name','kind','target','source')}
                with self.lock:self.apps=items;self.ready=True;self.error=''
            except Exception as exc:
                with self.lock:self.error='Cannot read installed apps: '+str(exc)
        finally:self.action_lock.release()
        return self.status()
    def status(self):
        with self.lock:return {'apps':sorted([{'id':uid,'name':app['name'],'source':app['source']} for uid,app in self.apps.items()],key=lambda app:(app['name'].casefold(),app['id'])),
            'ready':self.ready,'error':self.error}
    def launch(self,uid):
        if not isinstance(uid,str) or len(uid)!=24:raise ValueError('Choose an app from this computer’s installed app list.')
        if not self.action_lock.acquire(blocking=False):raise RuntimeError('An app refresh or launch is already in progress.')
        try:
            with self.lock:
                if uid not in self.apps:raise ValueError('App not found. Refresh installed apps on the selected computer.')
                app=dict(self.apps[uid])
            self.dispatch(app)
            return {'requested':True,'name':app['name']}
        finally:self.action_lock.release()
