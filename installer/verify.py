"""Read-only installation verification; no synthesis, no change of voices or settings."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from state import collect, check_initial
from layout import Layout


def digest(file):
    result = hashlib.sha256()
    with file.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def verify(root, models=True, initial=False):
    root = Path(root).resolve()
    layout = Layout(root)
    manifest = json.loads(layout.manifest.read_text(encoding='utf-8'))
    if initial:
        check_initial(root, manifest['initial_state_files'])
    else:
        collect(layout.user)
    for item in manifest['payload_files']:
        file = root / item['path']
        if not file.is_file() or digest(file) != item['sha256']:
            raise RuntimeError('Missing or changed file: ' + item['path'])
    if models:
        for item in manifest['models']:
            file = root / 'models' / item['name']
            if not file.is_file() or file.stat().st_size != item['size'] or digest(file) != item['sha256']:
                raise RuntimeError('Missing or invalid model: ' + item['name'])
        ollama = root / 'models/ollama'
        for item in manifest['gemma']['blobs']:
            file = ollama / 'blobs' / item['digest'].replace(':', '-')
            if not file.is_file() or file.stat().st_size != item['size'] or digest(file) != item['digest'].split(':')[1]:
                raise RuntimeError('Missing or invalid Gemma component: ' + item['digest'])
        repository, _, version = manifest['gemma'].get('tag', 'gemma4:12b').partition(':')
        file = ollama / 'manifests/registry.ollama.ai/library' / repository / version
        if not file.is_file() or digest(file) != manifest['gemma']['sha256']:
            raise RuntimeError('The Gemma manifest does not match the pinned release.')
    for command in ([str(layout.program / 'tools/ffmpeg/ffmpeg.exe'), '-version'],
                    [str(root / 'AudioBook Studio.exe'), '--check-resources'],
                    [str(root / 'AudioBook Studio.exe'), '--check-installation'],
                    [str(root / 'Uninstall AudioBook Studio.exe'), '--check']):
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:
            raise RuntimeError('Component failed to start: ' + Path(command[0]).name + ': ' + result.stdout.decode('utf-8', 'replace')[-500:])
    native_env = os.environ.copy()
    native_env['PATH'] = str(layout.program / 'engine/build') + os.pathsep + str(layout.program / 'engine/cuda') + os.pathsep + native_env['PATH']
    for name in ('tts-server.exe', 'spk-batch.exe'):
        result = subprocess.run([str(layout.program / 'engine/build' / name), '--help'], env=native_env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        # Both CLIs return 1 for help; distinguish usage from a missing-DLL exit.
        if result.returncode != 1 or b'Usage:' not in result.stdout:
            raise RuntimeError('The native engine could not be loaded: ' + name)
    modules = ['fastapi', 'uvicorn', 'numpy', 'soundfile', 'librosa', 'psutil', 'tkinter', 'app', 'voice_check']
    for name in modules:
        __import__(name)
    print('Application files, Python dependencies, Tk and FFmpeg: OK', flush=True)
    print('Voice references and settings: ' + ('match the initial release state' if initial else 'valid references'), flush=True)
    if models:
        print('Qwen and Gemma models: SHA-256 OK', flush=True)


if __name__ == '__main__':
    verify(Layout.for_program(Path(__file__).resolve().parent).root, '--runtime-only' not in sys.argv, '--initial-state' in sys.argv)

