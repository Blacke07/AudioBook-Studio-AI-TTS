"""Recoverable publication of program files; existing user data is never overwritten."""
import json
from pathlib import Path
import shutil
import uuid

from layout import Layout, safe_destination, USER
from migration import digest, write_json


def journal(root, scope='install'):
    if scope not in ('install','restore'): raise ValueError('Invalid file transaction scope.')
    return safe_destination(root,Layout(Path(root)).state/scope/'publication.json')


def publish(root, staging, manifest, checkpoint=lambda index: None, *, scope='install'):
    root, staging = Path(root).resolve(), Path(staging).resolve()
    layout, record_path = Layout(root), journal(root,scope)
    prior = json.loads(record_path.read_text()) if record_path.exists() else None
    if prior is not None and prior['payload'] != manifest['payload']['sha256']:
        raise ValueError('An interrupted update uses a different payload. Resume that setup or roll it back first.')
    if prior is None:
        seed = scope=='install' and not any(layout.user.iterdir())
        entries=[]
        for item in manifest['payload_files'] + (manifest['initial_state_files'] if seed else []):
            name=item['path']
            if scope=='install' and name.startswith(USER+'/') and item not in manifest['initial_state_files']:
                raise ValueError('The program payload may not overwrite user data.')
            allowed=(name.startswith(('Data/User/','Audiobooks/','Backups/Projects/')) if scope=='restore' else
                     name.startswith(('Data/Program/','Data/User/')) or name in
                     ('AudioBook Studio.exe','Uninstall AudioBook Studio.exe','Data/README.txt'))
            if not allowed:
                raise ValueError('Unexpected payload destination: '+name)
            file=safe_destination(root,root/name)
            old=digest(file) if file.exists() else None
            entries.append({'path':name,'before':old,'after':item['sha256']})
        before=layout.state/scope/'before'
        # Persist every preimage before the write-ahead journal and first replacement.
        for entry in entries:
            if entry['before']:
                copy=safe_destination(root,before/entry['path']); copy.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(root/entry['path'],copy)
                if digest(copy)!=entry['before']: raise ValueError('Program preimage copy failed.')
        prior={'payload':manifest['payload']['sha256'],'seed':seed,'entries':entries,
               'manifest_before':layout.manifest.read_bytes().hex() if layout.manifest.exists() else None}
        write_json(record_path,prior)
    for index, entry in enumerate(prior['entries']):
        name=entry['path']
        source=staging/name
        target=safe_destination(root,root/name)
        if digest(source)!=entry['after']: raise ValueError('Staged payload failed verification: '+name)
        current=digest(target) if target.exists() else None
        if current not in (entry['before'],entry['after']):
            raise ValueError('A file changed during the interrupted update; it was kept: '+name)
        if current!=entry['after']:
            target.parent.mkdir(parents=True,exist_ok=True)
            temporary=safe_destination(root,target.with_name(target.name+'.setup-tmp'))
            shutil.copy2(source,temporary)
            if digest(temporary)!=entry['after']: raise ValueError('Program copy failed: '+name)
            temporary.replace(target)
        checkpoint(index)
    return prior['seed']


def rollback(root, scope='install'):
    root=Path(root).resolve(); layout=Layout(root)
    data=json.loads(journal(root,scope).read_text())
    for entry in data['entries']:
        target=safe_destination(root,root/entry['path'])
        if target.exists() and digest(target) not in (entry['before'],entry['after']):
            raise ValueError('Cannot roll back a program file changed by another process.')
        if entry['before']:
            before=layout.state/scope/'before'/entry['path']
            if not before.exists() or digest(before)!=entry['before']:
                raise ValueError('Missing program rollback preimage.')
    for entry in reversed(data['entries']):
        # Keep seeded personal data even if verification fails. A retry can verify and reuse it.
        if scope=='install' and entry['path'].startswith(USER+'/'): continue
        target=root/entry['path']
        if entry['before']:
            shutil.copy2(layout.state/scope/'before'/entry['path'],target)
        else:
            target.unlink(missing_ok=True)
    if data['manifest_before'] is None:
        layout.manifest.unlink(missing_ok=True)
    else:
        layout.manifest.write_bytes(bytes.fromhex(data['manifest_before']))
    journal(root,scope).unlink()


def finish(root, scope='install'):
    root=Path(root).resolve(); layout=Layout(root)
    if scope=='restore':
        backup=safe_destination(root,layout.backups/'Restores'/uuid.uuid4().hex)
        backup.mkdir(parents=True)
        before=layout.state/scope/'before'
        if before.exists(): before.rename(backup/'before')
        shutil.copy2(journal(root,scope),backup/'receipt.json')
    for name in ('before','payload'):
        folder=safe_destination(root,layout.state/scope/name)
        if folder.exists():
            # Only controlled staging/preimage files, never author folders or links.
            from migration import files
            list(files(folder))
            shutil.rmtree(folder)
    journal(root,scope).unlink(missing_ok=True)
