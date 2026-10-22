"""Restore a verified old data snapshot, with a read-only preview by default. No code/models imported."""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from layout import Layout, safe_destination, check_path_length
import migration
import publication


def plan(snapshot, target):
    snapshot, target=Path(snapshot).resolve(),Path(target).resolve()
    layout=Layout(target)
    installed=json.loads(layout.manifest.read_text(encoding='utf-8'))
    if installed.get('layout_version')!=2: raise ValueError('Install the new layout before restoring data.')
    transfer=layout.user/'projects-state/transaction'
    if transfer.exists() and any(transfer.iterdir()):
        raise ValueError('Recover the unfinished Project import before restoring a backup.')
    data=json.loads((snapshot/'backup-manifest.json').read_text(encoding='utf-8-sig'))
    if data.get('Format')!='AudioBookStudio-data-backup-1': raise ValueError('Unsupported backup format.')
    old=Path(data['Source'])
    entries=[]; seen=set()
    for entry in data['Entries']:
        name=entry['Path'].replace('\\','/')
        if not name.startswith('application/'): continue
        name=name[len('application/'):]
        if name.startswith('projects-state/transaction/'):
            raise ValueError('The backup contains an unfinished Project import. Recover it in an isolated copy first.')
        if name in ('settings.json','characters.json','volumes.json') or name.startswith(('voices/','work/','projects-state/')):
            destination='Data/User/'+name
        elif name.startswith('export/'):
            destination='Audiobooks/'+name[len('export/'):]
        elif name.startswith('projects-backup/'):
            destination='Backups/Projects/'+name[len('projects-backup/'):]
        elif name.startswith('exemple/'):
            destination='Data/User/Sources/'+name
        else: continue
        if '..' in Path(name).parts or ':' in name: raise ValueError('Unsafe backup path.')
        source=safe_destination(snapshot,snapshot/'application'/name)
        output=safe_destination(target,target/destination); check_path_length(output)
        if destination.casefold() in seen: raise ValueError('Duplicate backup destination.')
        seen.add(destination.casefold())
        if migration.digest(source)!=entry['SHA256']: raise ValueError('Backup hash mismatch: '+name)
        replacement=None
        if name=='volumes.json':
            volumes=json.loads(source.read_text(encoding='utf-8'))
            for volume in volumes:
                folder=Path(volume['source'])
                if folder.is_absolute() and folder.is_relative_to(old):
                    relative=folder.relative_to(old)
                    if not relative.parts or relative.parts[0]!='exemple':
                        raise ValueError('Review the old internal source location before restoring: '+str(relative))
                    volume['source']=str(layout.user/'Sources'/relative)
            replacement=json.dumps(volumes,ensure_ascii=False,indent=2).encode('utf-8')
        entries.append({'source':str(source),'path':destination,'source_sha256':entry['SHA256'],
                        'sha256':hashlib.sha256(replacement).hexdigest() if replacement is not None else entry['SHA256'],
                        'replacement':None if replacement is None else replacement.hex(),
                        'modified_utc':entry.get('ModifiedUtc'),
                        'before':migration.digest(output) if output.exists() else None})
    if not all(any(e['path']=='Data/User/'+name for e in entries) for name in ('settings.json','characters.json','volumes.json')):
        raise ValueError('The backup does not contain all three configuration files.')
    active=publication.journal(target,scope='restore')
    if active.exists():
        previous=json.loads(active.read_text())
        by_path={entry['path']:entry for entry in previous['entries']}
        for item in entries:
            prior=by_path.get(item['path'])
            if prior is None or prior['after']!=item['sha256'] or item['before'] not in (prior['before'],prior['after']):
                raise ValueError('An interrupted restore conflicts with the current files. Roll it back before changing backups.')
            item['before']=prior['before']
    key=hashlib.sha256(json.dumps(entries,sort_keys=True).encode()).hexdigest()
    return {'plan_hash':key,'files':len(entries),'entries':entries}


def apply(snapshot,target,expected,checkpoint=lambda index: None):
    target=Path(target).resolve(); layout=Layout(target)
    import psutil
    for process in psutil.process_iter(['pid','exe']):
        if process.pid==os.getpid(): continue
        executable=process.info['exe']
        if executable and Path(executable).is_relative_to(target):
            raise ValueError('Close AudioBook Studio before restoring data.')
    data=plan(snapshot,target)
    if data['plan_hash']!=expected: raise ValueError('Backup or destination changed after preview. Preview again.')
    stage=safe_destination(target,layout.state/'restore/payload'); stage.mkdir(parents=True,exist_ok=True)
    for item in data['entries']:
        file=safe_destination(target,stage/item['path']); file.parent.mkdir(parents=True,exist_ok=True)
        if item['replacement'] is None: shutil.copy2(item['source'],file)
        else: file.write_bytes(bytes.fromhex(item['replacement']))
        if item['modified_utc'] is not None:
            timestamp=datetime.fromisoformat(item['modified_utc']).timestamp()
            os.utime(file,(timestamp,timestamp))
        if migration.digest(file)!=item['sha256']: raise ValueError('Restore staging hash mismatch.')
    manifest={'payload':{'sha256':data['plan_hash']},'payload_files':data['entries'],'initial_state_files':[]}
    publication.publish(target,stage,manifest,checkpoint,scope='restore')
    for item in data['entries']:
        if migration.digest(target/item['path'])!=item['sha256']: raise ValueError('Restored file hash mismatch.')
    publication.finish(target,scope='restore')
    return {'restored_files':data['files'],'verified':True}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup',type=Path,required=True)
    parser.add_argument('--target',type=Path,required=True)
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--plan-hash')
    args=parser.parse_args()
    if args.apply:
        if not args.plan_hash: parser.error('--apply requires the hash of a reviewed preview')
        print(json.dumps(apply(args.backup,args.target,args.plan_hash),indent=2))
    else:
        preview=plan(args.backup,args.target)
        print(json.dumps({'dry_run':True,'plan_hash':preview['plan_hash'],'files':preview['files'],
                          'destinations':[e['path'] for e in preview['entries']]},indent=2))
