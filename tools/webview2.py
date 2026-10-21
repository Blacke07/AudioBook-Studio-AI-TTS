"""Restore only the three pinned x64 WebView2 SDK redistributables used by the launcher."""
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def restore(root=ROOT):
    root = Path(root)
    spec = json.loads((root / 'installer/webview2.json').read_text(encoding='utf-8'))
    if hashlib.sha256((root / 'licenses/WebView2.txt').read_bytes()).hexdigest() != spec['license_sha256']:
        raise RuntimeError('The distributed WebView2 license does not match the pinned package.')
    cache = root / 'downloads' / spec['name']
    cache.parent.mkdir(exist_ok=True)
    if not cache.exists():
        with urlopen(spec['url'], timeout=120) as response:
            content = response.read()
        if hashlib.sha256(content).hexdigest() != spec['sha256']:
            raise RuntimeError('WebView2 SDK download does not match its pinned SHA-256.')
        cache.write_bytes(content)
    if hashlib.sha256(cache.read_bytes()).hexdigest() != spec['sha256']:
        raise RuntimeError('WebView2 SDK cache does not match its pinned SHA-256.')
    target = root / 'build/webview2'
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(cache) as archive:
        for name, item in spec['files'].items():
            content = archive.read(item['path'])
            if hashlib.sha256(content).hexdigest() != item['sha256']:
                raise RuntimeError('WebView2 SDK component does not match: ' + name)
            file = target / name
            if not file.exists() or file.read_bytes() != content:
                file.write_bytes(content)
        if hashlib.sha256(archive.read('LICENSE.txt')).hexdigest() != spec['license_sha256']:
            raise RuntimeError('WebView2 SDK license differs from the pinned package.')
    return target


if __name__ == '__main__':
    print(restore())
