"""Build an update ZIP from a source-only allowlist; never include user data."""
import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED
from fps_monitor import CHECKSUM
from network_native import verify_vendor
from version import VERSION

ROOT=Path(__file__).resolve().parent
FILES=['.gitignore','.gitattributes','README.md','VALIDATION.md','server.py','dashboard.html','app_limits.py',
       'remote_terminal.py','win_support.py','fps_monitor.py','telemetry.py','gpu_native.py',
       'power_controls.py','device_controls.py','package.py','Start.cmd','Restore.cmd','Startup.ps1',
       'Install-Startup.cmd','Disable-Startup.cmd','Connection-Info.cmd','Connection-Info.ps1','Enable-Terminal.cmd',
       'Disable-Terminal.cmd','Terminal-Settings.ps1','tests/test_controls.py','tests/test_live_features.py','tests/render_fixture.py',
       'vendor/presentmon/PresentMon-2.6.0-x64.exe','vendor/presentmon/manifest.json',
       'vendor/presentmon/LICENSE.txt','vendor/presentmon/THIRD_PARTY.txt']
FILES+=['manifest.webmanifest','apple-touch-icon.png','icon-192.png','icon-512.png','icon.svg','tests/test_webapp.js']
FILES+=['network_native.py','network_worker.py','network_limit.py','tests/test_network.py','tests/network_fixture.py',
        'vendor/windivert/WinDivert.dll','vendor/windivert/WinDivert64.sys','vendor/windivert/LICENSE',
        'vendor/windivert/WINDIVERT.h','vendor/windivert/manifest.json','vendor/windivert/WinDivert-2.2.2-source.zip']
FILES+=['laptop_controls.py','tests/test_laptops.py']
FILES+=['tweakout.py','tweakout_worker.py','tests/test_tweakout.py']
FILES+=['app_launcher.py','tests/test_launcher.py']
FILES+=['remote_keyboard.py','tests/test_keyboard.py']
FILES+=['gradual_lag.py','tests/test_gradual_lag.py','tests/test_effects.py']
FILES+=['version.py','Update.cmd','Update.ps1','Update-Core.ps1','INSTALL.md','CHANGELOG.md','tests/test_updater.ps1']

def manifest():
    entries=[]
    text_extensions={'.py','.ps1','.cmd','.md','.html','.js','.json','.txt','.webmanifest','.svg'}
    for filename in FILES:
        payload=(ROOT/filename).read_bytes()
        mode='binary'
        if Path(filename).suffix in text_extensions or filename in {'.gitignore','.gitattributes'}:
            payload=(payload.decode('utf-8-sig').replace('\r\n','\n').rstrip('\n')+'\n').encode('utf-8')
            mode='text-lf'
        entries.append({'path':filename,'mode':mode,'sha256':hashlib.sha256(payload).hexdigest()})
    result={'format':1,'version':VERSION,'files':entries}
    (ROOT/'update-manifest.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    return result

def build(destination):
    verify_vendor(ROOT)
    exe=ROOT/'vendor/presentmon/PresentMon-2.6.0-x64.exe'
    if hashlib.sha256(exe.read_bytes()).hexdigest()!=CHECKSUM: raise RuntimeError('PresentMon checksum mismatch')
    destination.parent.mkdir(parents=True,exist_ok=True)
    manifest()
    with ZipFile(destination,'w',ZIP_DEFLATED) as archive:
        for filename in FILES: archive.write(ROOT/filename,'HomeControl/'+filename)
        archive.write(ROOT/'update-manifest.json','HomeControl/update-manifest.json')
    with ZipFile(destination) as archive:
        assert len(archive.namelist())==len(FILES)+1
        assert archive.testzip() is None
        assert hashlib.sha256(archive.read('HomeControl/vendor/presentmon/PresentMon-2.6.0-x64.exe')).hexdigest()==CHECKSUM
    print('Packaged',len(FILES)+1,'source, setup, test and licensed helper files:',destination)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=ROOT/'dist'/f'HomeControl-v{VERSION}.zip')
    build(parser.parse_args().output)
