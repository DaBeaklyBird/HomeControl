"""Build an update ZIP from a source-only allowlist; never include user data."""
import argparse
import hashlib
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED
from fps_monitor import CHECKSUM
from network_native import verify_vendor

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

def build(destination):
    verify_vendor(ROOT)
    exe=ROOT/'vendor/presentmon/PresentMon-2.6.0-x64.exe'
    if hashlib.sha256(exe.read_bytes()).hexdigest()!=CHECKSUM: raise RuntimeError('PresentMon checksum mismatch')
    destination.parent.mkdir(parents=True,exist_ok=True)
    with ZipFile(destination,'w',ZIP_DEFLATED) as archive:
        for filename in FILES: archive.write(ROOT/filename,'HomeControl/'+filename)
    with ZipFile(destination) as archive:
        assert len(archive.namelist())==len(FILES)
        assert archive.testzip() is None
        assert hashlib.sha256(archive.read('HomeControl/vendor/presentmon/PresentMon-2.6.0-x64.exe')).hexdigest()==CHECKSUM
    print('Packaged',len(FILES),'source, setup, test and licensed helper files:',destination)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=ROOT/'dist'/'HomeControl-v3.3.zip')
    build(parser.parse_args().output)
