"""Versioned, bounded project archives. Reading a package never writes or extracts anything."""
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
import math
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile

import numpy as np
import soundfile as sf
import fixed_voices
import glossary
import project
from video import VideoSettings
from voices import MODEL_NAMES, describe, voice_parameters

FORMAT = 'audiobook-studio-project'
PARTS = ('settings', 'cast', 'volumes')
MAX_ENTRIES = 10000
MAX_TOTAL = 1024**3
MAX_JSON = 32*1024**2
MAX_WAV = 64*1024**2
RESERVED = re.compile(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)', re.I)


def encoded(value):
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8')


def component(value, limit=90):
    if (not isinstance(value, str) or value != project.safe_name(value, limit) or RESERVED.match(value)
            or len(value.encode('utf-16-le'))//2>limit or any(ord(char) == 127 for char in value)):
        raise ValueError(f'Invalid project name: {value!r}')
    return value


def json_data(content):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON key: '+key)
            result[key] = value
        return result
    try:
        return json.loads(content.decode('utf-8-sig'), object_pairs_hook=pairs,
                          parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Invalid JSON number')))
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise ValueError('Invalid project JSON: '+str(error)) from error


def clean_settings(data):
    if not isinstance(data, dict) or not isinstance(data.get('narrator', {}), dict):
        raise ValueError('Invalid project settings.')
    result = {key: data.get(key, default) for key, default in project.DEFAULT_SETTINGS.items()}
    narrator = {key: data.get('narrator', {}).get(key, default)
                for key, default in project.DEFAULT_SETTINGS['narrator'].items()}
    for key in ('mode', 'speaker', 'profile', 'description', 'instructions'):
        if not isinstance(narrator[key], str) or len(narrator[key]) > 20000:
            raise ValueError('Invalid narrator '+key)
    if (type(narrator['seed']) is not int or not 0 <= narrator['seed'] <= 2147483647
            or type(narrator['temperature']) not in (float, int)
            or not math.isfinite(narrator['temperature']) or not 0 < narrator['temperature'] <= 2):
        raise ValueError('Invalid narrator seed or temperature.')
    if narrator['mode'] not in MODEL_NAMES:
        raise ValueError('Unknown narrator model.')
    voice_parameters(MODEL_NAMES[narrator['mode']], narrator['speaker'],
                     narrator['description'] or describe(narrator['profile']), narrator['instructions'])
    result['narrator'] = narrator
    for key in ('multi_voice', 'announce_titles'):
        if type(result[key]) is not bool:
            raise ValueError('Invalid switch: '+key)
    for key, allowed in [('speech_tags', ('omit_fixed', 'all')), ('unclear_policy', ('wait', 'narrator')),
                          ('export_format', ('mp3','m4a','ogg','opus','flac','wav')),
                          ('volume_format', ('m4b','mp3','m4a','ogg','opus','flac')),
                          ('export_quality', ('standard','high'))]:
        if result[key] not in allowed:
            raise ValueError('Invalid setting: '+key)
    pause = result['dialogue_pause']
    if type(pause) not in (int,float) or not math.isfinite(pause) or not 0 <= pause <= 10:
        raise ValueError('Invalid dialogue pause.')
    if not isinstance(result['author'], str) or len(result['author']) > 1000:
        raise ValueError('Invalid author metadata.')
    raw_video = data.get('video', {})
    if not isinstance(raw_video, dict):
        raise ValueError('Invalid video settings.')
    result['video'] = asdict(VideoSettings.from_dict({k:v for k,v in raw_video.items()
                                                   if k in VideoSettings.__dataclass_fields__}))
    return result


def cast_rows(data):
    if not isinstance(data, dict) or not isinstance(data.get('characters'), list):
        raise ValueError('Invalid character glossary.')
    rows = []
    for entry in data['characters']:
        if not isinstance(entry, dict) or entry.get('gender') not in glossary.GENDERS:
            raise ValueError('Invalid character record or gender.')
        aliases = entry.get('aliases', [])
        if not isinstance(aliases, list) or any(not isinstance(alias, str) for alias in aliases):
            raise ValueError('Invalid character aliases.')
        rows.append([glossary.speaker_name(entry.get('name')), ', '.join(aliases), entry['gender'], entry.get('note',''),
                     entry.get('model',glossary.SAME_AS_NARRATOR), entry.get('custom_voice',''),
                     entry.get('voice_design',''), entry.get('seed',0)])
    result = glossary.normalize(rows)
    return result


def clean_script(data):
    if (not isinstance(data, dict) or not re.fullmatch('[0-9a-f]{16}', str(data.get('source_hash','')))
            or not isinstance(data.get('rows'), list)):
        raise ValueError('Invalid speaker assignments or source hash.')
    for row in data['rows']:
        if (not isinstance(row, list) or len(row) not in (3,4) or not isinstance(row[1], str)
                or type(row[2]) is not bool or (len(row)==4 and (type(row[3]) is not int or row[3]<0))):
            raise ValueError('Invalid speaker assignment row.')
        glossary.speaker_name(row[0], allow_reserved=True)
    # Keep row text byte-for-byte at the string level; only known metadata is accepted.
    return {key:value for key,value in data.items() if key in
            ('source_hash','rows','report','speakers','added','ai','analyzed')}


def check_voice(entry, content):
    if not isinstance(entry, dict) or not isinstance(entry.get('text'), str) or len(entry['text']) < 20:
        raise ValueError('Invalid fixed voice text.')
    digest = hashlib.sha1(content+entry['text'].encode('utf-8')).hexdigest()[:10]
    if entry.get('id') != 'fix-'+digest:
        raise ValueError('Fixed voice ID does not match its WAV and text.')
    try:
        with sf.SoundFile(BytesIO(content)) as audio:
            if (audio.format not in ('WAV','WAVEX') or audio.channels not in (1,2)
                    or not 8000 <= audio.samplerate <= 48000 or not fixed_voices.MIN_SECONDS <= audio.frames/audio.samplerate <= 300):
                raise ValueError('Fixed voice must be a readable 4–300 second mono/stereo WAV.')
            seconds = audio.frames/audio.samplerate
            frames = 0
            for block in audio.blocks(blocksize=65536, dtype='float32', always_2d=True):
                if not np.isfinite(block).all():
                    raise ValueError('Fixed voice contains invalid samples.')
                frames += len(block)
            if frames != audio.frames:
                raise ValueError('Fixed voice WAV is truncated.')
    except (sf.LibsndfileError, RuntimeError) as error:
        raise ValueError('Unreadable fixed voice WAV: '+str(error)) from error
    return {**{key:value for key,value in entry.items() if key in ('id','file','text','origin','date')},
            'seconds': round(seconds,2)}


@dataclass
class Package:
    meta: dict
    files: dict
    settings: dict | None
    characters: list
    registry: dict
    samples: dict
    volumes: list
    scripts: dict
    ignored: list


def read_package(path):
    files, ignored, seen = {}, [], set()
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries)>MAX_ENTRIES or sum(item.file_size for item in entries)>MAX_TOTAL:
                raise ValueError('Project archive exceeds the entry or expanded-size limit.')
            for item in entries:
                name = item.filename
                parts = PurePosixPath(name).parts
                if (not parts or name.startswith('/') or '\\' in name or ':' in name
                        or any(part in ('.','..','') for part in name.rstrip('/').split('/'))
                        or stat.S_ISLNK(item.external_attr>>16) or item.flag_bits&1):
                    raise ValueError('Unsafe project archive entry: '+name)
                for part in parts:
                    component(part,255)
                key = name.rstrip('/').casefold()
                if key in seen:
                    raise ValueError('Duplicate project archive entry: '+name)
                seen.add(key)
                limit = MAX_WAV if name.endswith('.wav') else MAX_JSON
                if item.file_size>limit:
                    raise ValueError('Project archive file is too large: '+name)
                allowed = (name in ('project.json','settings.json','characters.json','volumes.json',
                                     'voices/registry.json','voices/samples.json')
                           or len(parts)==2 and parts[0]=='voices' and name.endswith('.wav')
                           or len(parts)==4 and parts[0]=='scripts' and parts[-1]=='script.json')
                if not allowed or item.is_dir():
                    ignored.append(name)
                    continue
                with archive.open(item) as stream:
                    content = stream.read(limit+1)
                if len(content)>limit or len(content)!=item.file_size:
                    raise ValueError('Project archive expanded-size mismatch: '+name)
                files[name] = content
    except (zipfile.BadZipFile, NotImplementedError, EOFError) as error:
        raise ValueError('Invalid project archive: '+str(error)) from error
    return parse_files(files, ignored)


def parse_files(files, ignored=()):
    ignored = list(ignored)
    if len(files)>MAX_ENTRIES or sum(map(len,files.values()))>MAX_TOTAL:
        raise ValueError('Project exceeds the entry or expanded-size limit.')
    if any(len(value)>(MAX_WAV if name.endswith('.wav') else MAX_JSON) for name,value in files.items()):
        raise ValueError('Project file exceeds the size limit.')
    meta = json_data(files.get('project.json', b'{}'))
    if not isinstance(meta, dict) or meta.get('format')!=FORMAT or type(meta.get('version')) is not int or meta['version']!=1:
        raise ValueError('Unsupported project format/version. This application supports version 1.')
    parts = meta.get('parts')
    if not isinstance(parts,list) or not parts or any(part not in PARTS for part in parts) or len(set(parts))!=len(parts):
        raise ValueError('Invalid project parts.')

    def get(name):
        if name not in files:
            raise ValueError('Missing project file: '+name)
        return json_data(files[name])

    settings = clean_settings(get('settings.json')) if 'settings' in parts else None
    characters, registry, samples = [], {}, {}
    if 'cast' in parts:
        characters = cast_rows(get('characters.json'))
        raw_registry, samples = get('voices/registry.json'), get('voices/samples.json')
        if not isinstance(raw_registry,dict) or not isinstance(samples,dict):
            raise ValueError('Invalid fixed voice registry or samples.')
        roles = {row[0] for row in characters}|{'Narrator'}
        for role, entry in raw_registry.items():
            glossary.speaker_name(role, allow_reserved=True)
            if role not in roles or not isinstance(entry,dict):
                raise ValueError('Fixed voice role is absent from the cast: '+role)
            filename = component(entry.get('file'),255)
            if not filename.endswith('.wav') or 'voices/'+filename not in files:
                raise ValueError('Missing fixed voice WAV: '+filename)
            registry[role] = check_voice(entry, files['voices/'+filename])
        for role, value in samples.items():
            glossary.speaker_name(role, allow_reserved=True)
            if not isinstance(value,dict):
                raise ValueError('Invalid voice sample role.')
            if role not in roles:
                ignored.append('Unused voice sample role: '+role)
                continue
            if any(key in value and not isinstance(value[key],str) for key in ('sample','serious')):
                raise ValueError('Invalid voice sample text.')
            if 'real' in value and (not isinstance(value['real'],list) or any(not isinstance(v,str) for v in value['real'])):
                raise ValueError('Invalid voice sample lines.')
        samples = {role:{k:v for k,v in value.items() if k in ('sample','serious','real')}
                   for role,value in samples.items() if role in roles}
    volumes, scripts = [], {}
    if 'volumes' in parts:
        raw_volumes = get('volumes.json')
        if not isinstance(raw_volumes,list):
            raise ValueError('Invalid volumes list.')
        for volume in raw_volumes:
            if not isinstance(volume,dict) or not isinstance(volume.get('source'),str) or '\x00' in volume['source']:
                raise ValueError('Invalid volume source.')
            volumes.append({'name':component(volume.get('name')), 'source':volume['source']})
        names = {v['name'] for v in volumes}
        if len({n.casefold() for n in names})!=len(volumes):
            raise ValueError('Duplicate volume name.')
        for name, content in files.items():
            pieces = name.split('/')
            if pieces[0]=='scripts':
                component(pieces[2])
                if pieces[1] not in names:
                    raise ValueError('Script volume is absent from the package.')
                scripts[(pieces[1],pieces[2])] = clean_script(json_data(content))
    return Package(meta, files, settings, characters, registry, samples, volumes, scripts, ignored)


def collect(parts, snapshot=False):
    if not isinstance(parts,(tuple,list)) or not parts or any(part not in PARTS for part in parts):
        raise ValueError('Choose at least one project part.')
    files = {'project.json':encoded({'format':FORMAT,'version':1,'app_version':'V1.3',
             'created':datetime.now(timezone.utc).isoformat(), 'parts':list(parts),'note':''})}
    if 'settings' in parts:
        files['settings.json'] = encoded(clean_settings(project.load_settings()))
    if 'cast' in parts:
        files['characters.json'] = encoded(glossary.to_data(glossary.load()))
        registry = fixed_voices.load()
        files['voices/registry.json'] = encoded(registry)
        samples = fixed_voices.samples()
        if not snapshot:
            samples = {role:{key:value for key,value in entry.items() if key in ('sample','serious')}
                       for role,entry in samples.items()}
        files['voices/samples.json'] = encoded(samples)
        for entry in registry.values():
            filename = component(entry['file'],255)
            files['voices/'+filename] = (fixed_voices.FOLDER/filename).read_bytes()
    if 'volumes' in parts:
        volumes = project.volumes()
        files['volumes.json'] = encoded(volumes)
        for volume in volumes:
            folder = project.WORK/component(volume['name'])
            for script in folder.glob('*/script.json'):
                stem = component(script.parent.name)
                files[f'scripts/{volume["name"]}/{stem}/script.json'] = script.read_bytes()
    return files


def write_package(path, files):
    """Write to a staging path supplied by the caller, never directly over a user's archive."""
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(files.items()):
            archive.writestr(name, content)
    return read_package(path)


def summary(package):
    return {'parts':package.meta['parts'],'characters':len(package.characters),'voices':len(package.registry),
            'volumes':len(package.volumes),'scripts':len(package.scripts),
            'bytes':sum(map(len,package.files.values())), 'ignored':package.ignored,
            'contains_book_text':bool(package.scripts or any(entry.get('real') for entry in package.samples.values()))}
