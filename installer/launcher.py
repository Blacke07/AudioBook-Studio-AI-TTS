"""Start the installed application with its own tools; never stop a pre-existing Ollama service."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent


def ollama_ready():
    try:
        with urlopen('http://127.0.0.1:11434/api/tags', timeout=2) as response:
            return json.load(response)
    except (URLError, TimeoutError):
        return None


def require_model(tags, expected_tag, expected_digest):
    if not tags or not any(item.get('name') == expected_tag and item.get('digest') == expected_digest
                           for item in tags.get('models', [])):
        raise RuntimeError(f'The Ollama service on port 11434 does not have the pinned Gemma model ({expected_tag}). '
                           'Close that service to use the model installed with this application.')


def main():
    manifest = json.loads((ROOT / 'installation-manifest.json').read_text(encoding='utf-8'))
    env = os.environ.copy()
    env['PATH'] = str(ROOT / 'tools/ffmpeg') + os.pathsep + env['PATH']
    env['PYTHONUTF8'] = '1'
    env['PYTHONIOENCODING'] = 'utf-8'
    owned = None
    try:
        if ollama_ready() is None:
            env['OLLAMA_HOST'] = '127.0.0.1:11434'
            env['OLLAMA_MODELS'] = str(ROOT / 'models/ollama')
            env['OLLAMA_NO_CLOUD'] = 'true'
            owned = subprocess.Popen([str(ROOT / 'tools/ollama/ollama.exe'), 'serve'], env=env,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     creationflags=subprocess.CREATE_NO_WINDOW)
            deadline = time.monotonic() + 45
            while ollama_ready() is None:
                if owned.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError('Ollama did not start. Check the installation and port 11434.')
                time.sleep(.5)
        require_model(ollama_ready(), manifest['gemma'].get('tag', 'gemma4:12b'), manifest['gemma']['sha256'])
        return subprocess.call([sys.executable, str(ROOT / 'app.py'), *sys.argv[1:]], cwd=ROOT, env=env)
    finally:
        if owned is not None and owned.poll() is None:
            owned.terminate()
            try:
                owned.wait(10)
            except subprocess.TimeoutExpired:
                owned.kill()
                owned.wait()


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)

