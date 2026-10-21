"""Preview/merge and journalled project transactions. No old application code is executed."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import uuid

import fixed_voices
import glossary
import project
import project_package as package
from dialogue import segment

CONFIG = ('settings.json','characters.json','volumes.json','voices/registry.json','voices/samples.json')
TX_FORMAT = 'audiobook-project-transaction-v1'


def native_name(name):
    if name.startswith('scripts/'):
        return 'work/'+name[len('scripts/'):]
    return name


def target(name):
    """Only application-owned configuration, references, scripts and transaction metadata."""
    parts = name.split('/')
    allowed = (name in CONFIG or len(parts)==2 and parts[0]=='voices' and name.endswith('.wav')
               or len(parts)==4 and parts[0]=='work' and parts[-1]=='script.json'
               or name=='projects-state/last-import.json'
               or len(parts)==3 and parts[:2]==['projects-state','reports'] and name.endswith('.json'))
    if not allowed:
        raise ValueError('Invalid project transaction path: '+name)
    for index,part in enumerate(parts):
        package.component(part,255 if index==len(parts)-1 else 90)
    result = project.ROOT.joinpath(*parts)
    if not result.resolve().is_relative_to(project.ROOT.resolve()):
        raise ValueError('Project path follows a link outside the application.')
    return result


def capture():
    result = {}
    for name in CONFIG:
        file = target(name)
        if file.is_file():
            result[name] = file.read_bytes()
    for entry in fixed_voices.load().values():
        name = 'voices/'+package.component(entry['file'],255)
        result[name] = target(name).read_bytes()
    for volume in project.volumes():
        folder = project.WORK/package.component(volume['name'])
        for file in folder.glob('*/script.json'):
            name = f'work/{volume["name"]}/{package.component(file.parent.name)}/script.json'
            result[name] = target(name).read_bytes()
    return result


def state_hash():
    digest = hashlib.sha256()
    for name, content in sorted(capture().items()):
        digest.update(package.encoded([name,hashlib.sha256(content).hexdigest()]))
    last = project.ROOT/'projects-state/last-import.json'
    if last.exists():
        digest.update(last.read_bytes())
    return digest.hexdigest()


def _atomic_bytes(file, content):
    file.parent.mkdir(parents=True, exist_ok=True)
    temporary = file.with_name(file.name+'.project-tmp')
    try:
        temporary.write_bytes(content)
        temporary.replace(file)
    finally:
        temporary.unlink(missing_ok=True)


def recover():
    """Roll back a crash before serving requests. A committed transaction needs only cleanup."""
    folder = project.ROOT/'projects-state/transaction'
    if not folder.exists():
        return False
    owner = project._read_json(folder/'owner.json', {})
    if owner.get('format')!=TX_FORMAT:
        raise RuntimeError('Unknown project transaction folder. Recovery requires manual review.')
    journal = project._read_json(folder/'journal.json', None)
    if journal and journal['status']!='committed':
        for entry in journal['files']:
            file = target(entry['name'])
            if entry['existed']:
                _atomic_bytes(file, (folder/'before'/entry['name']).read_bytes())
            else:
                file.unlink(missing_ok=True)
            file.with_name(file.name+'.project-tmp').unlink(missing_ok=True)
    shutil.rmtree(folder)
    return True


def transact(writes):
    """Stage every byte and every preimage before changing the first destination file."""
    recover()
    folder = project.ROOT/'projects-state/transaction'
    folder.mkdir(parents=True)
    project.write_json(folder/'owner.json', {'format':TX_FORMAT})
    entries = []
    try:
        for name, content in writes.items():
            file = target(name)
            entries.append({'name':name,'existed':file.exists()})
            if file.exists():
                before = folder/'before'/name
                before.parent.mkdir(parents=True, exist_ok=True)
                before.write_bytes(file.read_bytes())
            if content is not None:
                staged = folder/'after'/name
                staged.parent.mkdir(parents=True, exist_ok=True)
                staged.write_bytes(content)
        journal = {'status':'applying','files':entries}
        project.write_json(folder/'journal.json', journal)
        for name, content in writes.items():
            file = target(name)
            if content is None:
                file.unlink(missing_ok=True)
            else:
                file.parent.mkdir(parents=True, exist_ok=True)
                (folder/'after'/name).replace(file)
        journal['status'] = 'committed'
        project.write_json(folder/'journal.json', journal)
    except BaseException:
        recover()
        raise
    recover()


def backup():
    files = package.collect(package.PARTS, snapshot=True)
    current = capture()
    existing = []
    for name, content in current.items():
        archive_name = 'scripts/'+name[len('work/'):] if name.startswith('work/') else name
        files[archive_name] = content
        existing.append(archive_name)
    meta = package.json_data(files['project.json'])
    meta['_snapshot_existing'] = existing
    files['project.json'] = package.encoded(meta)
    folder = project.ROOT/'projects-backup'
    folder.mkdir(exist_ok=True)
    path = folder/f'{datetime.now():%Y-%m-%d-%H%M%S}-{uuid.uuid4().hex[:8]}.abstudio'
    temporary = path.with_suffix('.tmp')
    try:
        package.write_package(temporary, files)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def _choices(values, parts):
    if not isinstance(values,dict):
        raise ValueError('Invalid import choices.')
    selected = values.get('parts', [part for part in parts if part!='settings'])
    if not isinstance(selected,list) or any(part not in parts for part in selected):
        raise ValueError('Invalid selected project parts.')
    for key in ('characters','voices','scripts'):
        if key in values and (not isinstance(values[key],list) or any(not isinstance(v,str) for v in values[key])):
            raise ValueError('Invalid conflict choices.')
    if not isinstance(values.get('locations',{}),dict):
        raise ValueError('Invalid folder locations.')
    return set(selected)


def _local_folder(source):
    return project.is_local_source(source) and Path(source).is_dir()


def plan(incoming, choices):
    selected = _choices(choices, incoming.meta['parts'])
    writes, report = {}, []

    def row(kind, name, action, reason='', **extra):
        report.append({'kind':kind,'name':name,'action':action,'reason':reason,**extra})

    if incoming.settings is not None:
        current = project.load_settings()
        changes = {key:{'current':current.get(key),'imported':value}
                   for key,value in incoming.settings.items() if current.get(key)!=value}
        apply = 'settings' in selected
        row('settings','Settings','update' if apply and changes else 'skip',
            'Selected explicitly' if apply else 'Not selected', changes=changes)
        if apply and changes:
            writes['settings.json'] = package.encoded(incoming.settings)

    rows = glossary.load()
    by_name = {r[0]:r for r in rows}
    registry, samples = fixed_voices.load(), fixed_voices.samples()
    if 'cast' in selected:
        changed_roles = set()
        for item in incoming.characters:
            name = item[0]
            if any(name.casefold()==old.casefold() and name!=old for old in by_name):
                raise ValueError('Character name differs only in letter case: '+name)
            if name in by_name and name not in choices.get('characters',[]):
                row('character',name,'skip','Keep mine', conflict=True)
                continue
            row('character',name,'update' if name in by_name else 'add', conflict=name in by_name)
            by_name[name] = item
            changed_roles.add(name)
        merged = list(by_name.values())
        if merged!=rows:
            writes['characters.json'] = package.encoded(glossary.to_data(merged))
        for role, entry in incoming.registry.items():
            if role in registry and role not in choices.get('voices',[]):
                row('voice',role,'skip','Keep mine',conflict=True)
                continue
            filename = 'voices/'+entry['file']
            content = incoming.files[filename]
            file = target(filename)
            if file.exists() and file.read_bytes()!=content:
                raise ValueError('A different reference WAV already uses this filename: '+entry['file'])
            if not file.exists():
                writes[filename] = content
            row('voice',role,'update' if role in registry else 'add',conflict=role in registry)
            registry[role] = entry
            changed_roles.add(role)
        for role, entry in incoming.samples.items():
            if role not in samples or role in changed_roles:
                samples[role] = entry
        if registry!=fixed_voices.load():
            writes['voices/registry.json'] = package.encoded(registry)
        if samples!=fixed_voices.samples():
            writes['voices/samples.json'] = package.encoded(samples)

    current_volumes = project.volumes()
    volumes = {item['name']:item for item in current_volumes}
    if 'volumes' in selected:
        for item in incoming.volumes:
            name = item['name']
            if any(name.casefold()==old.casefold() and name!=old for old in volumes):
                raise ValueError('Volume name differs only in letter case: '+name)
            new = name not in volumes
            entry = dict(volumes.get(name,item))
            if name in choices.get('locations',{}):
                source = choices['locations'][name]
                if not isinstance(source,str) or not _local_folder(source):
                    raise ValueError('Located folder is not available: '+name)
                entry['source'] = source
            if not project.is_local_source(entry['source']):
                row('volume',name,'skip','Non-local source refused; locate a local chapter folder',
                    source=entry['source'], missing=True)
                continue
            missing = not _local_folder(entry['source'])
            row('volume',name,'add' if new else 'update' if entry!=volumes[name] else 'skip',
                'Folder not found' if missing else 'Keep current folder' if not new else '',
                source=entry['source'], missing=missing)
            volumes[name] = entry
        if list(volumes.values())!=current_volumes:
            writes['volumes.json'] = package.encoded(list(volumes.values()))
        roles = set(by_name)|{'Narrator','Unassigned','Scene break'}
        for (volume, stem), script in incoming.scripts.items():
            key = volume+'/'+stem
            name = f'work/{volume}/{stem}/script.json'
            conflict = target(name).exists()
            if conflict and key not in choices.get('scripts',[]):
                row('script',key,'skip','Keep mine',conflict=True)
                continue
            if volume not in volumes:
                row('script',key,'skip','Locate a local chapter folder first',conflict=conflict)
                continue
            source = Path(volumes[volume]['source'])
            try:
                if not _local_folder(volumes[volume]['source']):
                    raise ValueError('Locate a local chapter folder first')
                matches = [file for file in project.chapter_files(source) if file.stem==stem]
                if len(matches)!=1:
                    raise ValueError('Chapter file missing or ambiguous')
                text = project.read_text_file(matches[0])
            except (OSError, ValueError) as error:
                row('script',key,'skip',str(error),conflict=conflict)
                continue
            if project.text_hash(text)!=script['source_hash']:
                row('script',key,'skip','Text has changed, will need a new analysis',conflict=conflict)
                continue
            original = ' '.join(' '.join(item.text.split()) for item in segment(text))
            imported = ' '.join(' '.join(item[1].split()) for item in script['rows'])
            if imported!=original:
                row('script',key,'skip','Script text differs from the local chapter; assignments refused',
                    conflict=conflict)
                continue
            if any(item[0] not in roles for item in script['rows']):
                row('script',key,'skip','A speaker is missing from the current cast',conflict=conflict)
                continue
            writes[name] = package.encoded(script)
            row('script',key,'update' if conflict else 'add',conflict=conflict)
    return writes, {'items':report,'ignored':incoming.ignored,'changes':len(writes),
                    'contains_book_text':bool(incoming.scripts)}


def apply(incoming, choices, expected_state, expected_plan):
    if state_hash()!=expected_state:
        raise ValueError('The project changed after preview. Preview the import again.')
    writes, report = plan(incoming, choices)
    if report!=expected_plan:
        raise ValueError('The source folders changed after preview. Preview the import again.')
    if not writes:
        return {**report,'backup':None,'message':'Nothing changed.'}
    path = backup()
    identifier = uuid.uuid4().hex
    last = {'backup':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'created':[name for name in writes if not target(name).exists()],
            'date':datetime.now(timezone.utc).isoformat(),'report':identifier+'.json'}
    report = {**report,'backup':path.name,'message':'Project import completed.'}
    writes['projects-state/last-import.json'] = package.encoded(last)
    writes['projects-state/reports/'+identifier+'.json'] = package.encoded(report)
    transact(writes)
    return report


def undo():
    last = project._read_json(project.ROOT/'projects-state/last-import.json', None)
    if not last:
        raise ValueError('There is no import to undo.')
    file = project.ROOT/'projects-backup'/package.component(last['backup'])
    if hashlib.sha256(file.read_bytes()).hexdigest()!=last['sha256']:
        raise ValueError('The import backup has changed. Undo refused.')
    saved = package.read_package(file)
    existing = saved.meta.get('_snapshot_existing')
    if not isinstance(existing,list) or any(name not in saved.files for name in existing):
        raise ValueError('The import backup has no valid restoration manifest.')
    safety = backup()
    writes = {native_name(name):saved.files[name] for name in existing}
    for name in CONFIG:
        if name not in writes:
            writes[name] = None
    for name in last['created']:
        if name not in writes:
            writes[name] = None
    writes['projects-state/last-import.json'] = None
    transact(writes)
    return {'message':'The state from before the last import was restored.','backup':file.name,
            'safety_backup':safety.name}


def history():
    folder = project.ROOT/'projects-backup'
    return {'backups':[file.name for file in sorted(folder.glob('*.abstudio'),reverse=True)][:20],
            'last_import':project._read_json(project.ROOT/'projects-state/last-import.json', None)}
