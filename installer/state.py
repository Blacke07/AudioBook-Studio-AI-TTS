"""Validate the public initial configuration and referenced voices without changing data."""
import hashlib
import json
from pathlib import Path


def collect(root):
    root = Path(root).resolve()
    names = ['settings.json', 'characters.json', 'volumes.json', 'voices/registry.json', 'voices/samples.json']
    registry = json.loads((root / 'voices/registry.json').read_text(encoding='utf-8'))
    for role, entry in registry.items():
        name = entry['file']
        if Path(name).name != name or '/' in name or '\\' in name or ':' in name or not name.endswith('.wav'):
            raise ValueError('Invalid voice reference path: ' + role)
        if not entry['id'].startswith('fix-') or not entry['text'].strip():
            raise ValueError('Incomplete fixed voice: ' + role)
        names.append('voices/' + name)
    contents = {name: (root / name).read_bytes() for name in sorted(set(names))}
    for name, content in contents.items():
        if not content:
            raise ValueError('Empty configuration file: ' + name)
        if name.endswith('.json'):
            json.loads(content)
    return contents


def records(contents):
    return [{'path': name, 'sha256': hashlib.sha256(content).hexdigest()}
            for name, content in sorted(contents.items())]


def check_initial(root, expected):
    root = Path(root).resolve()
    for item in expected:
        name = item['path']
        file = (root / name).resolve()
        if not file.is_relative_to(root) or not file.is_file():
            raise ValueError('Missing or invalid initial configuration file: ' + name)
        if hashlib.sha256(file.read_bytes()).hexdigest() != item['sha256']:
            raise ValueError('Initial configuration differs from the release: ' + name)
    collect(root/'Data/User' if any(item['path'].startswith('Data/User/') for item in expected) else root)
