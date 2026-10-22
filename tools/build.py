"""Build the self-contained public Windows setup from audited English sources."""
import hashlib
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import zipfile
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'installer'))
sys.path.insert(0, str(ROOT / 'app'))
from layout import PROGRAM, USER, LAYOUT_VERSION
from state import check_initial
from audit_public import audit, public_file
from webview2 import restore as restore_webview2

SETUP_NAME = 'AudioBookStudio-Setup.exe'


def sha256(file):
    digest = hashlib.sha256()
    with file.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def build_launcher(compiler, build):
    assets = ROOT / 'assets'
    icon_builder = build / 'IconBuilder.exe'
    subprocess.run([str(compiler), '/nologo', '/target:exe', '/reference:System.Drawing.dll',
                    '/out:' + str(icon_builder), str(ROOT / 'tools/IconBuilder.cs')], check=True)
    subprocess.run([str(icon_builder), str(assets)], check=True)
    icon = assets / 'audiobook.ico'
    output = build / 'AudioBook Studio.exe'
    sdk = restore_webview2(ROOT)
    sources = [ROOT / 'installer' / name for name in
               ('DesktopEntry.cs', 'InstallationPaths.cs', 'AppLauncher.cs', 'WindowsJob.cs', 'DesktopPolicy.cs', 'DesktopRuntime.cs', 'StudioWebView.cs')]
    inputs = sources + [icon, Path(__file__), ROOT / 'installer/windows.manifest', ROOT / 'installer/webview2.json']
    fingerprint = {file.name: sha256(file) for file in inputs}
    stamp = build / 'launcher-build.json'
    cached = json.loads(stamp.read_text()) if stamp.exists() else {}
    if not output.exists() or cached.get('inputs') != fingerprint or cached.get('output') != sha256(output):
        subprocess.run([str(compiler), '/nologo', '/target:winexe', '/platform:x64', '/codepage:65001', '/main:DesktopEntry',
                        '/reference:System.Windows.Forms.dll', '/reference:System.Drawing.dll',
                        '/reference:System.Web.Extensions.dll',
                        '/reference:' + str(sdk / 'Microsoft.Web.WebView2.Core.dll'),
                        '/reference:' + str(sdk / 'Microsoft.Web.WebView2.WinForms.dll'),
                        '/win32manifest:' + str(ROOT / 'installer/windows.manifest'),
                        '/win32icon:' + str(icon), '/resource:' + str(icon) + ',app.ico',
                        '/out:' + str(output), *map(str, sources)], check=True)
        stamp.write_text(json.dumps({'inputs': fingerprint, 'output': sha256(output)}, indent=2))
    for file in sdk.glob('*.dll'):
        shutil.copyfile(file, build / file.name)
    subprocess.run([str(output), '--check-resources'], check=True)
    return output, icon


def build_uninstaller(compiler, build, icon):
    output = build / 'Uninstall AudioBook Studio.exe'
    subprocess.run([str(compiler), '/nologo', '/target:winexe', '/platform:x64', '/codepage:65001',
                    '/reference:System.Windows.Forms.dll', '/reference:System.Web.Extensions.dll',
                    '/win32manifest:' + str(ROOT / 'installer/windows.manifest'), '/win32icon:' + str(icon),
                    '/out:' + str(output), str(ROOT / 'installer/Uninstall.cs'), str(ROOT / 'installer/InstallationPaths.cs')], check=True)
    subprocess.run([str(output), '--check'], check=True)
    return output


def main(reuse_payload=False):
    audit(ROOT)
    build, dist = ROOT / 'build', ROOT / 'dist'
    build.mkdir(exist_ok=True)
    dist.mkdir(exist_ok=True)
    compiler = Path(r'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe')
    launcher_exe, icon = build_launcher(compiler, build)
    manifest = json.loads((ROOT / 'manifest.json').read_text(encoding='utf-8'))
    state = json.loads((ROOT / 'release-state.json').read_text(encoding='utf-8'))
    check_initial(ROOT / 'app', state['files'])
    source_initial = {item['path'] for item in state['files']} | {'volumes.json'}
    initial_names = {USER+'/'+name for name in source_initial}
    manifest['layout_version'] = LAYOUT_VERSION
    files = {}
    files['AudioBook Studio.exe'] = launcher_exe
    for name in ('Microsoft.Web.WebView2.Core.dll', 'Microsoft.Web.WebView2.WinForms.dll', 'WebView2Loader.dll'):
        files[PROGRAM+'/'+name] = build / name
    files['Uninstall AudioBook Studio.exe'] = build_uninstaller(compiler, build, icon)
    files[PROGRAM+'/assets/audiobook.ico'] = icon
    for base in [ROOT / 'app', ROOT / 'build/native']:
        for file in base.rglob('*'):
            if file.is_file() and '__pycache__' not in file.parts and not file.suffix == '.pyc' and not file.name.startswith('test_'):
                if base == ROOT / 'app' and not public_file(file.relative_to(ROOT)):
                    continue
                relative = file.relative_to(base).as_posix()
                relative = (USER if base == ROOT/'app' and relative in source_initial else PROGRAM)+'/'+relative
                if relative in files:
                    raise RuntimeError('Duplicate file in payload: ' + relative)
                files[relative] = file
    for file in (ROOT / 'licenses').rglob('*'):
        if file.is_file():
            files[PROGRAM+'/licenses/' + file.relative_to(ROOT / 'licenses').as_posix()] = file
    for file in (ROOT / 'docs').rglob('*'):
        if file.is_file() and public_file(file.relative_to(ROOT)):
            files[PROGRAM+'/docs/' + file.relative_to(ROOT / 'docs').as_posix()] = file
    for source, target in [('installer/launcher.py','launcher.py'), ('installer/verify.py','verify_installation.py'),
                           ('installer/state.py','state.py'),
                           ('installer/migration.py','migration.py'), ('installer/publication.py','publication.py'),
                           ('installer/restore_data.py','restore_data.py'),
                           ('requirements.lock','requirements.lock'), ('README.md','README.md'),
                           ('LICENSE','LICENSE'), ('THIRD_PARTY_NOTICES.md','THIRD_PARTY_NOTICES.md'),
                           ('PRIVACY.md','PRIVACY.md'), ('VERIFICATION.md','VERIFICATION.md'),
                           ('demo-provenance.json','demo-provenance.json')]:
        files[PROGRAM+'/'+target] = ROOT / source
    internal_readme=build/'Data-README.txt'
    internal_readme.write_text('Internal application files. Use the folders next to this one for your audiobooks and backups.\n',encoding='utf-8')
    files['Data/README.txt']=internal_readme
    for target, text in {
        'Verify Installation.cmd': '@echo off\r\nsetlocal\r\nset "PYTHONUTF8=1"\r\ncd /d "%~dp0"\r\n"%~dp0.venv\\Scripts\\python.exe" "%~dp0verify_installation.py"\r\npause\r\n',
    }.items():
        path = build / target
        path.write_bytes(text.encode('ascii'))
        files[PROGRAM+'/'+target] = path
    payload = build / 'payload.zip'
    records = []
    if reuse_payload:
        cached=json.loads((build/'manifest.json').read_text(encoding='utf-8'))
        if sha256(payload) != cached['payload']['sha256']:
            raise RuntimeError('The cached payload changed. Build again without --reuse-payload.')
        expected={item['path']:item['sha256'] for item in cached['payload_files']}
        if set(expected) != set(files)-initial_names:
            raise RuntimeError('The file list changed. Rebuild the payload.')
        for target,digest in expected.items():
            if sha256(files[target]) != digest:
                raise RuntimeError('Changed file; rebuild the payload: '+target)
        with zipfile.ZipFile(payload) as archive:
            for target in initial_names:
                if archive.read(target) != files[target].read_bytes():
                    raise RuntimeError('Initial configuration changed; rebuild the payload.')
        manifest['payload']=cached['payload']
        manifest['payload_files']=cached['payload_files']
        print('Verified the existing payload; reusing it.',flush=True)
    else:
        print('Packaging the application and native runtime...', flush=True)
        with zipfile.ZipFile(payload, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for target, file in sorted(files.items()):
                archive.write(file, target)
                if target not in initial_names:
                    records.append({'path':target, 'sha256':sha256(file)})
        manifest['payload'] = {'name':'payload.zip','size':payload.stat().st_size,'sha256':sha256(payload)}
        manifest['payload_files'] = records
    manifest['initial_state_files'] = [{'path': name, 'sha256': sha256(files[name])}
                                       for name in sorted(initial_names)]
    final_manifest = build / 'manifest.json'
    final_manifest.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    # Use a BOM for consistent UTF-8 handling in Windows PowerShell 5.1.
    bootstrap = build / 'bootstrap.ps1'
    bootstrap.write_text((ROOT / 'installer/bootstrap.ps1').read_text(encoding='utf-8'), encoding='utf-8-sig')
    output = dist / SETUP_NAME
    arguments = [str(compiler), '/nologo', '/target:winexe', '/platform:x64', '/codepage:65001',
                 '/reference:System.Windows.Forms.dll', '/reference:System.Drawing.dll',
                 '/reference:System.Web.Extensions.dll',
                 '/win32icon:' + str(icon), '/resource:' + str(icon) + ',app.ico',
                 '/win32manifest:' + str(ROOT / 'installer/windows.manifest'), '/out:' + str(output)]
    for file, name in [(bootstrap,'bootstrap.ps1'), (ROOT / 'installer/install.py','install.py'),
                       (ROOT/'app/layout.py','layout.py'), (ROOT/'installer/migration.py','migration.py'),
                       (ROOT/'installer/publication.py','publication.py'), (ROOT/'installer/state.py','state.py'),
                       (final_manifest,'manifest.json'), (payload,'payload.zip'), (ROOT / 'README.md','README.md')]:
        arguments.append('/resource:' + str(file) + ',' + name)
    arguments.extend(str(ROOT / 'installer' / name) for name in ('Setup.cs', 'DesktopRuntime.cs', 'InstallationPaths.cs'))
    subprocess.run(arguments, check=True)
    subprocess.run([str(output), '--check-resources'], check=True)
    checksum = sha256(output)
    print('Created:', output, flush=True)
    print('Size:', output.stat().st_size, 'bytes; SHA-256:', checksum, flush=True)


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--reuse-payload',action='store_true')
    args=parser.parse_args()
    main(args.reuse_payload)

