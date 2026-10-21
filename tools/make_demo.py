"""Generate a new synthetic public narrator and speaker calibration, never reading private voices.

Developer tool only. Uses installed NumPy/SoundFile and a separately provided pinned model directory.
Starts only its own engine on an unused port, and always stops that process before exiting.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import Request, urlopen

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
from voices import AUTHOR_DELIVERY, CHARACTER_PROFILES, PROFILES
from conversion import CHARACTER_SAMPLE as CALIBRATION_SAMPLE, PREVIEW_TEXT as SAMPLE


def generate(models, port):
    staging = ROOT / 'build/demo'
    staging.mkdir(parents=True, exist_ok=True)
    native = ROOT / 'build/native/engine'
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', port))
    env = os.environ.copy()
    env['PATH'] = str(native / 'build') + os.pathsep + str(native / 'cuda') + os.pathsep + env['PATH']
    binary = native / 'build/tts-server.exe'
    model = models / 'qwen-talker-1.7b-voicedesign-F32.gguf'
    codec = models / 'qwen-tokenizer-12hz-F32.gguf'
    for file in (binary, model, codec):
        if not file.is_file():
            raise FileNotFoundError(file)
    profiles = [('Public narrator', json.loads((ROOT / 'app/settings.json').read_text())['narrator']['description'])]
    profiles += [(name, description) for name, description in PROFILES.items()]
    profiles += [(name, description) for group in CHARACTER_PROFILES.values() for name, description in group.items()]
    corpus = []
    url = f'http://127.0.0.1:{port}'
    with (staging / 'engine.log').open('w', encoding='utf-8') as log:
        process = subprocess.Popen([str(binary), '--model', str(model), '--codec', str(codec),
                                    '--device', 'CUDA0', '--host', '127.0.0.1', '--port', str(port),
                                    '--lang', 'English', '--max-batch', '1'], cwd=binary.parent, env=env,
                                   stdout=log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            deadline = time.monotonic() + 120
            while True:
                if process.poll() is not None:
                    raise RuntimeError('Owned demo engine exited. See build/demo/engine.log.')
                try:
                    with urlopen(url + '/health', timeout=1):
                        break
                except URLError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError('Demo engine startup timed out.')
                    time.sleep(.5)
            for index, (name, description) in enumerate(profiles):
                target = staging / f'{index:02}.wav'
                text = SAMPLE if index == 0 else CALIBRATION_SAMPLE
                if not target.exists():
                    body = {'input': text, 'language': 'English', 'max_new_tokens': 2048, 'response_format': 'wav', 'seed': 42 + index * 7919,
                            'temperature': 0.55, 'instructions': description + '\nDelivery: ' + AUTHOR_DELIVERY}
                    print(f'Generating public sample {index + 1}/{len(profiles)}: {name}', flush=True)
                    request = Request(url + '/v1/audio/speech', data=json.dumps(body).encode(),
                                      headers={'Content-Type': 'application/json'})
                    with urlopen(request, timeout=180) as response:
                        content = response.read()
                    audio, rate = sf.read(io.BytesIO(content), dtype='float32')
                    if rate != 24000 or len(audio) / rate < 4:
                        raise RuntimeError('Generated demo sample is too short or has an unexpected rate.')
                    target.write_bytes(content)
                corpus.append(target)
        finally:
            process.terminate()
            process.wait(15)
    # Speaker encoder uses CPU; it never competes for VRAM with the stopped TTS server.
    encoder = subprocess.Popen([str(native / 'build/spk-batch.exe'), '--talker',
                                str(models / 'qwen-talker-1.7b-base-Q8_0.gguf'), '--device', 'CPU'],
                               cwd=native / 'build', env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        if not encoder.stdout.readline().startswith(b'READY'):
            raise RuntimeError('Speaker encoder did not become ready.')
        vectors = []
        for file in corpus:
            encoder.stdin.write((str(file) + '\n').encode('utf-8')); encoder.stdin.flush()
            parts = encoder.stdout.readline().decode().split()
            if not parts or parts[0] != 'OK':
                raise RuntimeError('Speaker encoder rejected ' + file.name)
            vector = np.array(list(map(float, parts[2:])), dtype=np.float32)
            vectors.append(vector / np.linalg.norm(vector))
    finally:
        encoder.stdin.close()
        try:
            encoder.wait(10)
        except subprocess.TimeoutExpired:
            encoder.terminate(); encoder.wait(5)
    assets = ROOT / 'app/assets'; assets.mkdir(exist_ok=True)
    mean = np.mean(vectors, axis=0).astype(np.float32)
    if not np.isfinite(mean).all():
        raise RuntimeError('Invalid public calibration vector.')
    np.save(assets / 'voice_mean.npy', mean, allow_pickle=False)
    voice_dir = ROOT / 'app/voices'
    content = corpus[0].read_bytes()
    voice_id = hashlib.sha1(content + SAMPLE.encode()).hexdigest()[:10]
    filename = 'narrator-' + voice_id + '.wav'
    (voice_dir / filename).write_bytes(content)
    registry = {'Narrator': {'id': 'fix-' + voice_id, 'file': filename, 'text': SAMPLE,
                            'seconds': round(sf.info(corpus[0]).duration, 2),
                            'origin': {'source': 'New synthetic public demo; no private voice recordings',
                                       'seed': 42, 'temperature': .55, 'model_sha256':
                                       'b32c8571977f47c95313a32fe08d0fe5681f6c1fffac53d2b9c73a4cd7f6ee90'},
                            'date': '2026-10-21'}}
    (voice_dir / 'registry.json').write_text(json.dumps(registry, indent=2), encoding='utf-8')
    (voice_dir / 'samples.json').write_text(json.dumps({'Narrator': {'sample': SAMPLE}}, indent=2), encoding='utf-8')
    records = {'synthetic_demo': True, 'calibration_samples': len(corpus), 'embedding_dimensions': int(mean.size),
               'narrator': {'file': filename, 'text': SAMPLE, 'sha256': hashlib.sha256(content).hexdigest()},
               'calibration_sha256': hashlib.sha256((assets / 'voice_mean.npy').read_bytes()).hexdigest()}
    (ROOT / 'demo-provenance.json').write_text(json.dumps(records, indent=2), encoding='utf-8')
    print('Public synthetic narrator and calibration generated. No private voice files were read.', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--models-dir', type=Path, required=True)
    parser.add_argument('--port', type=int, default=18764)
    args = parser.parse_args()
    generate(args.models_dir.resolve(), args.port)
