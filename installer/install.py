"""Provision a new installation only. Downloaded and imported models must match pinned hashes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.request import Request, urlopen
import zipfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'app'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from layout import Layout, MARKER, LAYOUT_VERSION, safe_destination
import migration
import publication


def sha256(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def matches(path, item):
    path = Path(path)
    return path.is_file() and (not item.get('size') or path.stat().st_size == item['size']) and sha256(path) == item['sha256']


def download(item, cache):
    """Resume owned downloads and verify their pinned bytes."""
    target = Path(cache) / item['name']
    if target.exists():
        if matches(target, item):
            return target
        raise RuntimeError('Invalid cached file. Remove that file and try again: ' + str(target))
    partial = target.with_name(target.name + '.part')
    offset = partial.stat().st_size if partial.exists() else 0
    headers = {'User-Agent': 'AudioBookStudio-Installer/1.0'}
    if offset:
        headers['Range'] = f'bytes={offset}-'
    if not item.get('size') or offset != item['size']:
        print('Downloading: ' + item['name'], flush=True)
        with urlopen(Request(item['url'], headers=headers), timeout=120) as response:
            append = offset and response.status == 206
            if append and not response.headers.get('Content-Range', '').startswith(f'bytes {offset}-'):
                raise RuntimeError('The server returned an invalid download range.')
            received = offset if append else 0
            last_report = received
            with partial.open('ab' if append else 'wb') as output:
                while block := response.read(4 * 1024 * 1024):
                    output.write(block)
                    received += len(block)
                    if received - last_report >= 64 * 1024 * 1024:
                        total = item.get('size', 0)
                        print(f'  {received / 1024**2:.0f} / {total / 1024**2:.0f} MB', flush=True)
                        last_report = received
    print('Checking SHA-256: ' + item['name'], flush=True)
    if not matches(partial, item):
        partial.unlink()
        raise RuntimeError('Incorrect SHA-256 or file size: ' + item['name'] + '. Download the file again.')
    partial.replace(target)
    return target


def safe_extract(archive, destination):
    destination = Path(destination).resolve()
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            target = (destination / member.filename).resolve()
            if not target.is_relative_to(destination) or ':' in member.filename or '\\' in member.filename:
                raise RuntimeError('Archive contains an invalid path: ' + member.filename)
            if (member.external_attr >> 16) & 0o170000 == 0o120000:
                raise RuntimeError('Symbolic links are not allowed in the archive.')
        bundle.extractall(destination)


def run(arguments, **kwargs):
    print('Running: ' + Path(str(arguments[0])).name + ' ' + ' '.join(map(str, arguments[1:3])), flush=True)
    with subprocess.Popen(list(map(str, arguments)), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, encoding='utf-8', errors='replace',
                          creationflags=subprocess.CREATE_NO_WINDOW, **kwargs) as process:
        for line in process.stdout:
            print(line, end='', flush=True)
        if process.wait():
            raise subprocess.CalledProcessError(process.returncode, arguments)


PROFILE_FILES = ('voice_design', 'custom_voice', 'base', 'codec')


def ollama_location(tag):
    """'gemma4:e4b-it-qat' -> ('gemma4', 'e4b-it-qat'): the registry repository and the local manifest name."""
    repository, separator, version = tag.partition(':')
    if not separator or not repository or not version or any(part in ('.', '..') or '/' in part or '\\' in part
                                                              for part in (repository, version)):
        raise RuntimeError('Invalid dialogue model name in the manifest: ' + tag)
    return repository, version


def resolve(manifest, name):
    """The manifest of one installation: only the chosen profile's Qwen files and Gemma model."""
    profiles = manifest['profiles']
    if name not in profiles:
        raise RuntimeError('Unknown model set: ' + str(name) + '. Choose one of: ' + ', '.join(profiles))
    profile = profiles[name]
    wanted = [profile[key] for key in PROFILE_FILES]
    by_name = {item['name']: item for item in manifest['models']}
    missing = [file for file in wanted if file not in by_name]
    if missing:
        raise RuntimeError('The manifest does not pin these model files: ' + ', '.join(missing))
    ollama_location(profile['gemma'])
    resolved = {key: value for key, value in manifest.items() if key not in ('models', 'gemma_models', 'profiles')}
    resolved['models'] = [by_name[file] for file in dict.fromkeys(wanted)]
    resolved['gemma'] = {'tag': profile['gemma'], **manifest['gemma_models'][profile['gemma']]}
    resolved['profile'] = name
    resolved['model_profile'] = {'name': name, 'label': profile['label'], 'gemma': profile['gemma'],
                                 'render_factor': profile['render_factor'],
                                 **{key: profile[key] for key in PROFILE_FILES}}
    return resolved


def hardware(profile, policy):
    smi = shutil.which('nvidia-smi') or str(Path(os.environ['SystemRoot']) / 'System32/nvidia-smi.exe')
    try:
        result = subprocess.run([smi, '--query-gpu=name,compute_cap,memory.total,driver_version',
                                 '--format=csv,noheader,nounits'], check=True, capture_output=True, text=True,
                                creationflags=subprocess.CREATE_NO_WINDOW)
    except (OSError, subprocess.CalledProcessError) as error:
        raise RuntimeError('An NVIDIA GPU and driver are required. Install the driver from nvidia.com.') from error
    first = result.stdout.splitlines()[0].split(',')
    name, capability, memory, driver = [part.strip() for part in first]
    check_hardware(profile, name, capability, memory, driver, policy)
    print('GPU: ' + name + '; driver ' + driver, flush=True)


def check_hardware(profile, name, capability, memory, driver, policy):
    supported = [architecture / 10 for architecture in policy['cuda_architectures']]
    if float(capability) not in supported:
        choices = ', '.join(f'{value:.1f}' for value in supported)
        raise RuntimeError(f'{name}: unsupported CUDA compute capability {capability}. '
                           f'This engine is built for {choices}.')
    if int(float(memory)) < profile['min_vram_mb']:
        gigabytes = round(profile['min_vram_mb'] / 1000)
        raise RuntimeError(f'{name}: the {profile["label"]} model set requires at least {gigabytes} GB of VRAM.')
    if tuple(map(int, driver.split('.')[:2])) < tuple(map(int, policy['min_driver'].split('.'))):
        raise RuntimeError('Update the NVIDIA driver to version ' + policy['min_driver'] + ' or later for CUDA 12.8.')


def model_matches(target, item):
    target = Path(target).absolute()
    if target.resolve() != target:
        raise RuntimeError('The models destination must not use links: ' + str(target))
    return matches(target, item)


def import_model(source, target, item):
    """Use files already at their final path; preserve explicitly supplied external libraries."""
    source, target = Path(source), Path(target)
    if target.exists():
        if not model_matches(target, item):
            raise RuntimeError('A different file already exists at the destination: ' + str(target))
        return
    if not matches(source, item):
        raise RuntimeError('Selected file does not match the pinned model: ' + str(source))
    model_matches(target, item)  # Refuse linked destinations even before the file exists.
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + '.install-part')
    shutil.copyfile(source, temporary)
    if not matches(temporary, item):
        temporary.unlink()
        raise RuntimeError('Copied file failed verification: ' + str(target))
    temporary.replace(target)


def install(args):
    root = args.target.resolve()
    layout = Layout(root)
    marker = root / MARKER
    if not marker.is_file() or marker.read_text(encoding='ascii').strip() != 'AudioBookStudio-Installer-1':
        raise RuntimeError('This folder was not prepared by the installer. Existing applications will not be overwritten.')
    source = json.loads(args.manifest.read_text(encoding='utf-8-sig'))
    profile_name = args.profile or source['default_profile']
    manifest = resolve(source, profile_name)
    profile = source['profiles'][profile_name]
    print('Model set: ' + profile['label'], flush=True)
    hardware(profile, manifest['hardware'])
    if shutil.disk_usage(root).free < profile['min_free_gib'] * 1024**3:
        raise RuntimeError(f'At least {profile["min_free_gib"]} GiB of free space is required for installation, '
                           'caches and models.')
    if not matches(args.bundle, manifest['payload']):
        raise RuntimeError('The application bundle failed SHA-256 verification.')
    layout.prepare()
    if migration.migrate(root):
        print('Legacy data migrated and verified; models stayed in place.', flush=True)
    print('Extracting the application...', flush=True)
    staging = safe_destination(root,layout.state / 'install')
    safe_extract(args.bundle, staging/'payload')
    if any(layout.user.iterdir()) and not publication.journal(root).exists():
        from state import collect
        collect(layout.user)  # Invalid/partial author data must never be replaced with defaults.
    initial = publication.publish(root, staging/'payload', manifest)
    manifest['layout_version'] = LAYOUT_VERSION
    migration.write_json(layout.manifest, manifest)
    python = layout.program / 'runtime/python/python.exe'
    venv = layout.program / '.venv'
    if not (venv / 'Scripts/python.exe').exists():
        run([python, '-m', 'venv', '--copies', venv])
    vpython = venv / 'Scripts/python.exe'
    run([vpython, '-m', 'pip', 'install', '--disable-pip-version-check', '--require-hashes',
         '--only-binary=:all:', '-r', layout.program / 'requirements.lock'])
    staging.mkdir(exist_ok=True)
    args.cache.mkdir(parents=True, exist_ok=True)
    print('Installing portable FFmpeg...', flush=True)
    ffmpeg_archive = download(manifest['ffmpeg'], args.cache)
    safe_extract(ffmpeg_archive, staging / 'ffmpeg')
    candidates = list((staging / 'ffmpeg').glob('*/bin/ffmpeg.exe'))
    if len(candidates) != 1:
        raise RuntimeError('The FFmpeg archive has an unexpected layout.')
    destination = layout.program / 'tools/ffmpeg'
    destination.mkdir(parents=True, exist_ok=True)
    for filename in ('ffmpeg.exe', 'ffprobe.exe'):
        shutil.copyfile(candidates[0].with_name(filename), destination / filename)
    ffmpeg_notices = layout.program / 'licenses/ffmpeg'
    ffmpeg_notices.mkdir(parents=True, exist_ok=True)
    for file in candidates[0].parent.parent.iterdir():
        if file.is_file():
            shutil.copyfile(file, ffmpeg_notices / file.name)
    print('Installing portable Ollama without a global service...', flush=True)
    safe_extract(download(manifest['ollama'], args.cache), layout.program / 'tools/ollama')
    if not (layout.program / 'tools/ollama/ollama.exe').is_file():
        raise RuntimeError('The Ollama archive has an unexpected layout.')
    for item in manifest['models']:
        target = root / 'models' / item['name']
        print('Checking local model: ' + item['name'], flush=True)
        if model_matches(target, item):
            continue
        if args.manual_models is not None:
            source = args.manual_models / item['name']
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            download(item, target.parent)
            continue
        import_model(source, target, item)
    print('Preparing the pinned Gemma dialogue model...', flush=True)
    ollama_models = root / 'models/ollama'
    repository, version = ollama_location(manifest['gemma']['tag'])
    for item in manifest['gemma']['blobs']:
        digest = item['digest'].split(':')[1]
        filename = item['digest'].replace(':', '-')
        record = {'name': filename, 'size': item['size'], 'sha256': digest,
                  'url': f'https://registry.ollama.ai/v2/library/{repository}/blobs/' + item['digest']}
        target = ollama_models / 'blobs' / filename
        print('Checking local model: ' + filename, flush=True)
        if model_matches(target, record):
            continue
        if args.manual_models is None:
            target.parent.mkdir(parents=True, exist_ok=True)
            download(record, target.parent)
        else:
            import_model(args.manual_models / 'ollama/blobs' / filename, target, record)
    gemma_manifest = ollama_models / 'manifests/registry.ollama.ai/library' / repository / version
    gemma_manifest.parent.mkdir(parents=True, exist_ok=True)
    gemma_manifest.write_bytes(bytes.fromhex(manifest['gemma']['content_hex']))
    env = os.environ.copy()
    env['PATH'] = str(destination) + os.pathsep + env['PATH']
    print('Verifying the installation without generating audio...', flush=True)
    run([vpython, '-B', layout.program / 'verify_installation.py', *(['--initial-state'] if initial else [])],
        cwd=layout.program, env=env)
    migration.finish(root)
    publication.finish(root)
    marker.unlink()
    print('FINAL VERIFICATION PASSED. Models, Python and the application are ready.', flush=True)


def main(args):
    marker = args.target / MARKER
    if not marker.is_file() or marker.read_text(encoding='ascii').strip() != 'AudioBookStudio-Installer-1':
        print('ERROR: folder not prepared by the installer; existing applications will not be overwritten.', file=sys.stderr)
        return 1
    class Tee:
        def __init__(self, output, log): self.output, self.log = output, log
        def write(self, text): self.output.write(text); self.log.write(text); self.log.flush()
        def flush(self): self.output.flush(); self.log.flush()
    log_path = Layout(args.target).state/'logs/install.log'
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open('a', encoding='utf-8') as log:
        original_out, original_error = sys.stdout, sys.stderr
        sys.stdout = Tee(original_out, log)
        sys.stderr = Tee(original_error, log)
        try:
            install(args)
        except Exception as error:
            print('ERROR: ' + str(error), file=sys.stderr, flush=True)
            return 1
        finally:
            sys.stdout, sys.stderr = original_out, original_error
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--target', type=Path, required=True)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--manual-models', type=Path)
    parser.add_argument('--profile')
    raise SystemExit(main(parser.parse_args()))
