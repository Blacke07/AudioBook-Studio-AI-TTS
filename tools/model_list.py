"""Print the exact filenames, URLs and hashes needed for manual model import.

Usage: python tools/model_list.py [standard|compact]"""
import json
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[1]
manifest = json.loads((root / 'manifest.json').read_text())
name = sys.argv[1] if len(sys.argv) > 1 else manifest['default_profile']
profile = manifest['profiles'][name]
print(f'Model set: {profile["label"]}\n')
files = dict.fromkeys(profile[key] for key in ('voice_design', 'custom_voice', 'base', 'codec'))
for item in manifest['models']:
    if item['name'] in files:
        print('Local Models/' + item['name'])
        print(item['url'])
        print('SHA-256: ' + item['sha256'] + '\n')
repository = profile['gemma'].split(':')[0]
for item in manifest['gemma_models'][profile['gemma']]['blobs']:
    print('Local Models/ollama/blobs/' + item['digest'].replace(':', '-'))
    print(f'https://registry.ollama.ai/v2/library/{repository}/blobs/' + item['digest'])
    print('SHA-256: ' + item['digest'].split(':')[1] + '\n')
