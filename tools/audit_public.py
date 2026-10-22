"""Fail a public release on personal paths, unexpected media or non-demo initial state."""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FOLDERS = ('app', 'installer', 'tools', 'tests', 'licenses', 'assets', 'native', 'docs', '.github')
FILES = ('.gitignore', 'README.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'PRIVACY.md',
         'VERIFICATION.md', 'requirements.txt', 'requirements.lock', 'manifest.json',
         'release-state.json', 'demo-provenance.json')
PUBLIC_MARKDOWN = frozenset(name.casefold() for name in (
    'README.md', 'PRIVACY.md', 'THIRD_PARTY_NOTICES.md', 'VERIFICATION.md', 'docs/BUILD.md', 'docs/PROJECT_FORMAT.md',
    'app/web/guides/Voice Personality Guide.md', 'app/web/guides/Voice Sheet Example.md',
))


def public_file(relative):
    """Keep product documentation; exclude local notes and assistant configuration from all packages."""
    path = Path(relative)
    parts = [part.casefold() for part in path.parts]
    if (parts and parts[0]=='app' and len(parts)>1 and parts[1] in
            {'work','export','models','engine','tools','projects-state','projects-backup','.desktop'}):
        return False
    if path.suffix.casefold() in ('.abstudio','.tmp','.project-tmp'):
        return False
    if any(part in {'.claude', '.codex', '.cursor', '.agents', '.ai', '.gemini', '.aider', '.continue',
                    '.vscode', '.idea', 'internal', 'private', 'maintainer',
                    '__pycache__', '.git'} for part in parts):
        return False
    stem = path.stem.casefold()
    for prefix in ('agents', 'claude', 'codex', 'handoff', 'predare', 'checkpoint', 'copilot-instructions'):
        if stem == prefix or any(stem.startswith(prefix + separator) for separator in ('-', '_', ' ', '.')):
            return False
    name = path.as_posix().casefold()
    if path.suffix.casefold() in ('.md', '.markdown'):
        return name in PUBLIC_MARKDOWN
    if parts and parts[0] == 'docs':
        return len(parts) == 3 and parts[1] == 'screenshots' and path.suffix.casefold() in ('.png', '.jpg')
    return path.suffix.casefold() not in ('.pyc', '.log', '.docx', '.pdf')


def source_files(root):
    for name in FILES:
        file = root / name
        if not file.is_file():
            raise FileNotFoundError('Missing public source: ' + name)
        yield file
    for name in FOLDERS:
        for file in sorted((root / name).rglob('*')):
            if file.is_file() and public_file(file.relative_to(root)):
                yield file


def check_content(name, content):
    private_markers = (str(Path.home()), str(Path.home()).replace('\\', '/'),
                       '!' + 'Downloads', '!' + 'Shitz')
    lowered = content.lower()
    for marker in private_markers:
        for encoding in ('utf-8', 'utf-16-le'):
            if marker.lower().encode(encoding) in lowered:
                raise ValueError('Personal path found in public file: ' + name)


def audit(root=ROOT, native=True):
    root = Path(root)
    demo = json.loads((root / 'demo-provenance.json').read_text())
    if demo['synthetic_demo'] is not True or demo['calibration_samples'] < 2:
        raise ValueError('Public demo provenance is incomplete.')
    allowed = {'app/voices/' + demo['narrator']['file']: demo['narrator']['sha256'],
               'app/assets/voice_mean.npy': demo['calibration_sha256']}
    # Voice presets: synthetic reference takes, each pinned by hash in demo-provenance.json and listed in the catalog.
    for preset in demo.get('presets', []):
        allowed['app/presets/' + preset['file']] = preset['sha256']
    catalog = root / 'app/presets/presets.json'
    if catalog.exists():
        listed = {item['file']: item['sha256'] for item in json.loads(catalog.read_text(encoding='utf-8'))}
        if listed != {item['file']: item['sha256'] for item in demo.get('presets', [])}:
            raise ValueError('Voice presets differ from demo-provenance.json.')
    for relative, expected in allowed.items():
        if hashlib.sha256((root / relative).read_bytes()).hexdigest() != expected:
            raise ValueError('Synthetic public asset changed: ' + relative)
    app = root / 'app'
    if json.loads((app / 'volumes.json').read_text()) != []:
        raise ValueError('Public release must have no volume paths.')
    if json.loads((app / 'characters.json').read_text())['characters'] != []:
        raise ValueError('Public release must have an empty cast.')
    settings = json.loads((app / 'settings.json').read_text())
    if settings.get('author'):
        raise ValueError('Public release must have no personal author name.')
    registry = json.loads((app / 'voices/registry.json').read_text())
    if set(registry) != {'Narrator'} or registry['Narrator']['file'] != demo['narrator']['file']:
        raise ValueError('Only the synthetic demo narrator may ship.')
    for file in source_files(root):
        relative = file.relative_to(root).as_posix()
        if file.suffix.lower() in ('.gguf', '.wav', '.mp3', '.mp4', '.exe', '.dll', '.npy') and relative not in allowed:
            raise ValueError('Unexpected binary/model/media in public sources: ' + relative)
        check_content(relative, file.read_bytes())
    if native:
        engine = root / 'build/native/engine'
        required = [engine / 'build' / name for name in (
            'tts-server.exe', 'spk-batch.exe', 'ggml.dll', 'ggml-base.dll', 'ggml-cpu.dll', 'ggml-cuda.dll',
            'msvcp140.dll', 'vcruntime140.dll', 'vcruntime140_1.dll', 'vcomp140.dll')]
        required += [engine / 'cuda' / name for name in ('cudart64_12.dll', 'cublas64_12.dll', 'cublasLt64_12.dll')]
        for file in required:
            if not file.is_file():
                raise FileNotFoundError('Missing native runtime: ' + file.name)
        for file in (root / 'build/native').rglob('*'):
            if file.is_file():
                check_content(file.name, file.read_bytes())
        with zipfile.ZipFile(root / 'build/native-source.zip') as archive:
            for name in archive.namelist():
                check_content('native source: ' + name, archive.read(name))
    print('Public configuration, media allowlist and local-path audit: OK')


if __name__ == '__main__':
    audit()
