"""Journalled same-drive migration of a legacy installation. Never execute its code."""
import hashlib
import json
from pathlib import Path
import shutil
import uuid

from layout import Layout, USER_FILES, safe_destination, check_path_length


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def files(folder):
    folder = Path(folder)
    if folder.is_symlink() or folder.is_junction():
        raise ValueError('Migration does not follow links: ' + str(folder))
    if folder.is_file():
        yield folder
    elif folder.is_dir():
        for child in folder.iterdir():
            yield from files(child)


def journal_path(root):
    return safe_destination(root,Layout(Path(root)).state/'migration/journal.json')


def legacy_manifest(root):
    path = Path(root)/'installation-manifest.json'
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or not all(isinstance(data.get(k), list) for k in ('payload_files','initial_state_files','models')):
        raise ValueError('Invalid legacy installation manifest.')
    for item in data['payload_files']+data['initial_state_files']:
        relative = item['path']
        if ':' in relative or '\\' in relative or '..' in Path(relative).parts:
            raise ValueError('Unsafe legacy installation manifest path.')
        safe_destination(root, Path(root)/relative)
    return data


def plan(root):
    root = Path(root).resolve()
    layout = Layout(root)
    old = legacy_manifest(root)
    if old is None:
        return None
    transfer=root/'projects-state/transaction'
    if transfer.exists() and any(transfer.iterdir()):
        raise ValueError('Recover the unfinished Project import in the existing application before updating. No files were moved.')
    from state import collect
    collect(root)  # Configuration and fixed references must be valid before the first move.
    operations, occupied = [], set()

    def tree(source, target):
        source, target = root/source, root/target
        for file in files(source):
            destination = target if file == source else target/file.relative_to(source)
            safe_destination(root, destination)
            check_path_length(destination)
            if destination.exists() or str(destination).casefold() in occupied:
                raise ValueError('Migration destination already exists: ' + str(destination))
            occupied.add(str(destination).casefold())
            operations.append({'source':file.relative_to(root).as_posix(),
                               'target':destination.relative_to(root).as_posix(), 'sha256':digest(file)})

    for name in USER_FILES:
        tree(name, 'Data/User/'+name)
    for name in ('voices','work','projects-state'):
        tree(name, 'Data/User/'+name)
    tree('export','Audiobooks')
    tree('projects-backup','Backups/Projects')
    tree('.desktop','Data/State/desktop')
    for name in ('install.log','startup.log','engine.log'):
        tree(name,'Data/State/logs/'+('legacy-install.log' if name=='install.log' else name))
    tree('shortcuts.txt','Data/State/shortcuts.txt')

    volumes_file = root/'volumes.json'
    volumes = json.loads(volumes_file.read_text(encoding='utf-8'))
    if not isinstance(volumes,list): raise ValueError('The volume list is invalid. No files were moved.')
    sources = set()
    for volume in volumes:
        source = Path(volume['source'])
        # External books are never resolved, read or modified by migration.
        if source.is_absolute() and source.is_relative_to(root):
            safe_destination(root, source)
            relative = source.relative_to(root)
            if relative.parts[0] in {'models','runtime','.venv','tools','engine','work','Data','voices'}:
                raise ValueError('An internal chapter source conflicts with program/data folders.')
            sources.add(relative.as_posix())
            volume['source'] = str(layout.user/'Sources'/relative)
    if (root/'exemple').exists():
        sources.add('exemple')
    for source in sorted(sources):
        tree(source, 'Data/User/Sources/'+source)
    replacement = json.dumps(volumes, ensure_ascii=False, indent=2).encode('utf-8')
    original = volumes_file.read_bytes()
    cleanup = []
    # Only manifest-owned, unchanged program files. Modified or unknown files are left behind.
    protected = {item['source'] for item in operations}
    for item in old['payload_files']:
        name = item['path']
        file = root/name
        if name in protected or name.startswith(('models/','voices/','work/','export/')):
            continue
        if file.is_file() and digest(file) == item['sha256']:
            cleanup.append({'path':name,'sha256':item['sha256']})
    for folder in ('runtime','.venv','.install','.downloads','tools/ffmpeg','tools/ollama','licenses/ffmpeg','__pycache__'):
        for file in files(root/folder):
            cleanup.append({'path':file.relative_to(root).as_posix(),'sha256':digest(file)})
    # Older setup left a second model library. Move missing pinned files by rename;
    # remove an identical duplicate only after commit; never remove unknown model files.
    models={item['name']:item['sha256'] for item in old['models']}
    gemma=old.get('gemma',{})
    for item in gemma.get('blobs',[]):
        models['ollama/blobs/'+item['digest'].replace(':','-')]=item['digest'].split(':')[1]
    if gemma.get('sha256'):
        tag=gemma.get('tag','gemma4:12b').replace(':','/')
        models['ollama/manifests/registry.ollama.ai/library/'+tag]=gemma['sha256']
    for file in files(root/'Local Models'):
        relative=file.relative_to(root/'Local Models').as_posix()
        expected=models.get(relative)
        if expected is None or digest(file)!=expected:
            continue
        target=root/'models'/relative
        safe_destination(root,target)
        if target.exists():
            if digest(target)!=expected: raise ValueError('Conflicting model file: '+str(target))
            cleanup.append({'path':file.relative_to(root).as_posix(),'sha256':expected})
        else:
            tree(file.relative_to(root).as_posix(),'models/'+relative)
    return {'format':'audiobook-layout-migration-1','id':uuid.uuid4().hex, 'operations':operations,
            'cleanup':cleanup, 'volumes_before':original.hex(),
            'volumes_after':replacement.hex() if sources else None}


def migrate(root, checkpoint=lambda phase, index: None):
    root = Path(root).resolve()
    journal = journal_path(root)
    data = json.loads(journal.read_text(encoding='utf-8')) if journal.exists() else plan(root)
    if data is None:
        return False
    if data.get('format') != 'audiobook-layout-migration-1':
        raise ValueError('Invalid migration journal. No files were changed.')
    if not journal.exists():
        # The durable journal and small configuration preimages precede the first rename.
        backup = safe_destination(root,Layout(root).backups/'Migrations'/data['id'])
        backup.mkdir(parents=True, exist_ok=True)
        for name in USER_FILES:
            if (root/name).exists():
                shutil.copyfile(root/name, backup/name)
        write_json(journal, data)
    for index, item in enumerate(data['operations']):
        source = safe_destination(root, root/item['source'])
        target = safe_destination(root, root/item['target'])
        if source.exists():
            if target.exists() or digest(source) != item['sha256']:
                raise ValueError('Migration conflict; neither file was overwritten: ' + str(source))
            target.parent.mkdir(parents=True, exist_ok=True)
            source.rename(target)
        expected = item['sha256']
        if item['source'] == 'volumes.json' and data['volumes_after']:
            if target.exists() and target.read_bytes() == bytes.fromhex(data['volumes_after']):
                expected = digest(target)
        if not target.is_file() or digest(target) != expected:
            raise ValueError('Migration verification failed: ' + str(target))
        checkpoint('moved', index)
    if data['volumes_after']:
        target = Layout(root).user/'volumes.json'
        current = target.read_bytes()
        if current not in (bytes.fromhex(data['volumes_before']), bytes.fromhex(data['volumes_after'])):
            raise ValueError('Volume locations changed during migration.')
        temporary = safe_destination(root,target.with_suffix('.migration-tmp'))
        temporary.write_bytes(bytes.fromhex(data['volumes_after']))
        temporary.replace(target)
    checkpoint('ready', len(data['operations']))
    return True


def rollback(root):
    root = Path(root).resolve()
    path = journal_path(root)
    data = json.loads(path.read_text(encoding='utf-8'))
    # Check every precondition before changing anything.
    for item in data['operations']:
        source, target = safe_destination(root,root/item['source']), safe_destination(root,root/item['target'])
        if source.exists():
            if target.exists() or digest(source) != item['sha256']:
                raise ValueError('Cannot roll back changed migration files.')
        elif target.exists():
            expected = item['sha256']
            if item['source']=='volumes.json' and data['volumes_after'] and target.read_bytes()==bytes.fromhex(data['volumes_after']):
                expected=digest(target)
            if digest(target)!=expected:
                raise ValueError('Cannot roll back changed migration files.')
        else:
            raise ValueError('Cannot roll back a missing migration file.')
    for item in reversed(data['operations']):
        source, target = root/item['source'], root/item['target']
        if target.exists():
            if item['source']=='volumes.json' and data['volumes_before']:
                target.write_bytes(bytes.fromhex(data['volumes_before']))
            source.parent.mkdir(parents=True, exist_ok=True)
            target.rename(source)
    path.unlink()


def finish(root):
    """Called only after the new installation passes verification. Models are never removed."""
    root = Path(root).resolve()
    path = journal_path(root)
    if not path.exists():
        return
    data = json.loads(path.read_text(encoding='utf-8'))
    for item in data['cleanup']:
        if item['path'].startswith(('models/','Data/','Audiobooks/','Backups/')):
            raise ValueError('Invalid legacy cleanup destination.')
        target = safe_destination(root, root/item['path'])
        # The two root EXEs have already been replaced by the new payload.
        if item['path'] in ('AudioBook Studio.exe','Uninstall AudioBook Studio.exe'):
            continue
        if target.is_file() and digest(target)==item['sha256']:
            target.unlink()
    (root/'installation-manifest.json').unlink(missing_ok=True)
    (root/'.studio-install-incomplete').unlink(missing_ok=True)
    write_json(safe_destination(root,Layout(root).backups/'Migrations'/data['id']/'receipt.json'), data)
    # Remove empty legacy directories only; preserve unknown files and never follow links.
    for folder in ('voices','work','export','projects-backup','projects-state','exemple','.desktop',
                   'runtime','.venv','.install','.downloads','tools','licenses','web','engine','assets','presets','__pycache__','Local Models'):
        base=root/folder
        prune_empty(base)
    path.unlink()


def prune_empty(folder):
    if folder.is_symlink() or folder.is_junction() or not folder.is_dir(): return
    for child in folder.iterdir():
        if not child.is_symlink() and not child.is_junction() and child.is_dir(): prune_empty(child)
    if not any(folder.iterdir()): folder.rmdir()
