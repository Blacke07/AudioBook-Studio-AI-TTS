"""Disposable legacy migration, update and layout tests. No real installation or backup is read."""
import hashlib
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'app'))
sys.path.insert(0,str(ROOT/'installer'))
from layout import Layout, check_path_length
import migration
import publication
import restore_data


def put(root,name,content):
    file=root/name; file.parent.mkdir(parents=True,exist_ok=True); file.write_bytes(content)
    return file


def legacy(root):
    entries={'settings.json':b'{"narrator":{"seed":42,"temperature":0.55}}',
             'characters.json':b'{"characters":[]}',
             'volumes.json':json.dumps([{'name':'The Lantern House','source':str(root/'exemple')}]).encode(),
             'voices/registry.json':b'{}','voices/samples.json':b'{}','voices/approved.wav':b'fixed sample',
             'work/Book/001/script.json':b'{"rows":[]}', 'work/passages/abc.wav':b'generated audio',
             'export/Book/001.mp3':b'finished audio','projects-backup/before.abstudio':b'old backup',
             'projects-state/last-import.json':b'{}','exemple/001.txt':b'Invented chapter.',
             '.desktop/window.json':b'[0,0,900,700,0]', 'startup.log':b'prior log',
             '.venv/Scripts/python.exe':b'reproducible dependency','app.py':b'# legacy code',
             'my notes.txt':b'unknown user file','models/model.gguf':b'model'}
    for name,content in entries.items(): put(root,name,content)
    manifest={'payload_files':[{'path':'app.py','sha256':migration.digest(root/'app.py')}],
              'initial_state_files':[{'path':name,'sha256':migration.digest(root/name)} for name in
                                      ('settings.json','characters.json','volumes.json')],
              'models':[{'name':'model.gguf','sha256':migration.digest(root/'models/model.gguf')}], 'gemma':{}}
    put(root,'installation-manifest.json',json.dumps(manifest).encode())
    return entries


class LayoutTests(unittest.TestCase):
    def test_installed_and_development_paths_are_explicit_and_separate(self):
        root=Path('C:/Synthetic Studio')
        paths=Layout.for_program(root/'Data/Program')
        self.assertTrue(paths.installed)
        self.assertEqual(paths.user,root/'Data/User')
        self.assertEqual(paths.models,root/'models')
        self.assertEqual(paths.audiobooks,root/'Audiobooks')
        self.assertFalse(Layout.for_program(root/'source/app').installed)

    def test_migration_preserves_bytes_models_inode_and_external_books(self):
        with TemporaryDirectory() as folder:
            root=Path(folder); old=legacy(root)
            identity=(root/'models/model.gguf').stat().st_ino
            self.assertTrue(migration.migrate(root))
            self.assertEqual((root/'Data/User/settings.json').read_bytes(),old['settings.json'])
            self.assertEqual((root/'Data/User/voices/approved.wav').read_bytes(),old['voices/approved.wav'])
            self.assertEqual((root/'Audiobooks/Book/001.mp3').read_bytes(),old['export/Book/001.mp3'])
            self.assertEqual((root/'Data/User/work/passages/abc.wav').read_bytes(),old['work/passages/abc.wav'])
            volumes=json.loads((root/'Data/User/volumes.json').read_bytes())
            self.assertEqual(volumes[0]['source'],str(root/'Data/User/Sources/exemple'))
            migration.finish(root)
            self.assertEqual((root/'models/model.gguf').stat().st_ino,identity)
            self.assertEqual((root/'my notes.txt').read_bytes(),old['my notes.txt'])
            self.assertFalse((root/'app.py').exists())
            self.assertFalse(migration.journal_path(root).exists())

    def test_migration_resumes_after_every_move_and_before_commit(self):
        with TemporaryDirectory() as folder:
            baseline=Path(folder)/'base'; legacy(baseline)
            count=len(migration.plan(baseline)['operations'])
            for failure in range(count+1):
                root=Path(folder)/str(failure); old=legacy(root)
                def fail(phase,index):
                    if index==failure: raise InterruptedError('simulated process exit')
                with self.assertRaises(InterruptedError): migration.migrate(root,fail)
                migration.migrate(root)
                self.assertEqual((root/'Data/User/voices/approved.wav').read_bytes(),old['voices/approved.wav'])
                self.assertEqual((root/'Data/User/work/passages/abc.wav').read_bytes(),old['work/passages/abc.wav'])

    def test_rollback_restores_original_volume_paths_and_every_moved_file(self):
        with TemporaryDirectory() as folder:
            root=Path(folder); old=legacy(root)
            migration.migrate(root); migration.rollback(root)
            for name,content in old.items(): self.assertEqual((root/name).read_bytes(),content,name)

    def test_conflict_and_changed_rollback_file_fail_without_overwriting(self):
        with TemporaryDirectory() as folder:
            root=Path(folder); legacy(root)
            put(root,'Data/User/settings.json',b'other author data')
            with self.assertRaisesRegex(ValueError,'already exists'): migration.migrate(root)
            self.assertEqual((root/'Data/User/settings.json').read_bytes(),b'other author data')
        with TemporaryDirectory() as folder:
            root=Path(folder); legacy(root); migration.migrate(root)
            put(root,'Data/User/voices/approved.wav',b'changed after migration')
            with self.assertRaisesRegex(ValueError,'changed'): migration.rollback(root)
            self.assertEqual((root/'Data/User/voices/approved.wav').read_bytes(),b'changed after migration')

    def test_publication_seeds_once_resumes_and_preserves_author_data_on_reinstall(self):
        with TemporaryDirectory() as folder:
            root=Path(folder)/'install'; paths=Layout(root); paths.prepare()
            stage=Path(folder)/'stage'
            config=b'{"seed":42,"temperature":0.55}'
            records=[]
            for name,content in [('Data/Program/app.py',b'# new code'),('Data/User/settings.json',config)]:
                put(stage,name,content); records.append({'path':name,'sha256':hashlib.sha256(content).hexdigest()})
            manifest={'payload':{'sha256':'fixture'},'payload_files':records[:1],'initial_state_files':records[1:]}
            def interrupt(index): raise InterruptedError('power loss')
            with self.assertRaises(InterruptedError): publication.publish(root,stage,manifest,interrupt)
            self.assertTrue(publication.publish(root,stage,manifest))
            publication.finish(root)
            put(root,'Data/User/settings.json',b'author settings')
            self.assertFalse(publication.publish(root,stage,manifest))
            self.assertEqual((root/'Data/User/settings.json').read_bytes(),b'author settings')

    def test_publication_rollback_restores_program_and_keeps_personal_data(self):
        with TemporaryDirectory() as folder:
            root=Path(folder)/'install'; paths=Layout(root); paths.prepare()
            put(root,'Data/Program/app.py',b'old code'); put(root,'Data/User/settings.json',b'personal')
            stage=Path(folder)/'stage'; put(stage,'Data/Program/app.py',b'new code')
            manifest={'payload':{'sha256':'fixture'},'payload_files':[{'path':'Data/Program/app.py',
                       'sha256':hashlib.sha256(b'new code').hexdigest()}],'initial_state_files':[]}
            publication.publish(root,stage,manifest); publication.rollback(root)
            self.assertEqual((root/'Data/Program/app.py').read_bytes(),b'old code')
            self.assertEqual((root/'Data/User/settings.json').read_bytes(),b'personal')

    def test_local_models_duplicates_removed_only_after_commit_and_missing_models_renamed(self):
        with TemporaryDirectory() as folder:
            root=Path(folder); legacy(root)
            put(root,'Local Models/model.gguf',b'model')
            put(root,'Local Models/my model.gguf',b'unknown')
            migration.migrate(root)
            self.assertTrue((root/'Local Models/model.gguf').exists())
            migration.finish(root)
            self.assertFalse((root/'Local Models/model.gguf').exists())
            self.assertEqual((root/'Local Models/my model.gguf').read_bytes(),b'unknown')

    def test_long_paths_fail_explicitly_before_creating_output(self):
        with TemporaryDirectory() as folder:
            path=Path(folder)/('a'*100)/('b'*100)/'more'/'long.mp4'
            self.assertGreater(len(str(path)),260)
            with self.assertRaisesRegex(ValueError,'too long'): check_path_length(path)
            self.assertFalse(path.exists())

    def test_malicious_legacy_manifest_escape_is_refused_without_changes(self):
        with TemporaryDirectory() as folder:
            root=Path(folder); old=legacy(root)
            data=json.loads((root/'installation-manifest.json').read_text())
            data['payload_files'].append({'path':'../outside.txt','sha256':'0'*64})
            put(root,'installation-manifest.json',json.dumps(data).encode())
            with self.assertRaises(ValueError): migration.migrate(root)
            self.assertEqual((root/'settings.json').read_bytes(),old['settings.json'])

    def test_old_backup_restoration_is_dry_run_verified_and_resumable(self):
        with TemporaryDirectory() as folder:
            root=Path(folder); target=root/'install'; Layout(target).prepare()
            put(target,'Data/State/installation-manifest.json',b'{"layout_version":2}')
            put(target,'Data/User/settings.json',b'public initial settings')
            snapshot=root/'snapshot'
            contents={'settings.json':b'{"seed":42,"temperature":0.55}', 'characters.json':b'{"characters":[]}',
                      'volumes.json':b'[]','voices/approved.wav':b'approved take',
                      'work/passages/abc.wav':b'generated audio','export/Book/001.mp3':b'export',
                      'app.py':b'old code must not be copied', 'models/model.gguf':b'model must not be copied'}
            entries=[]
            for name,content in contents.items():
                put(snapshot,'application/'+name,content)
                entries.append({'Path':'application\\'+name.replace('/','\\'),'Bytes':len(content),
                                'ModifiedUtc':'2026-10-20T12:00:02Z' if name.startswith('export/') else '2026-10-20T12:00:00Z',
                                'SHA256':hashlib.sha256(content).hexdigest()})
            put(snapshot,'backup-manifest.json',json.dumps({'Format':'AudioBookStudio-data-backup-1',
                'Source':str(root/'old installation'),'Entries':entries}).encode())
            preview=restore_data.plan(snapshot,target)
            self.assertEqual((target/'Data/User/settings.json').read_bytes(),b'public initial settings')
            self.assertEqual(preview['files'],6)
            def interrupt(index): raise InterruptedError('interrupted restoration')
            with self.assertRaises(InterruptedError): restore_data.apply(snapshot,target,preview['plan_hash'],interrupt)
            self.assertTrue(restore_data.apply(snapshot,target,preview['plan_hash'])['verified'])
            self.assertEqual((target/'Data/User/voices/approved.wav').read_bytes(),b'approved take')
            self.assertEqual((target/'Data/User/work/passages/abc.wav').read_bytes(),b'generated audio')
            self.assertEqual((target/'Audiobooks/Book/001.mp3').read_bytes(),b'export')
            self.assertGreater((target/'Audiobooks/Book/001.mp3').stat().st_mtime,
                               (target/'Data/User/work/passages/abc.wav').stat().st_mtime)
            self.assertFalse((target/'Data/Program/app.py').exists())
            self.assertFalse((target/'models/model.gguf').exists())
            self.assertTrue(list((target/'Backups/Restores').glob('*/before/Data/User/settings.json')))
            put(snapshot,'application/voices/approved.wav',b'corrupted backup sample')
            with self.assertRaisesRegex(ValueError,'hash mismatch'): restore_data.plan(snapshot,target)
            self.assertEqual((target/'Data/User/voices/approved.wav').read_bytes(),b'approved take')

    def test_unavailable_reference_is_refused_before_migration_writes(self):
        with TemporaryDirectory() as folder:
            root=Path(folder); old=legacy(root)
            put(root,'voices/registry.json',b'{"Narrator":{"id":"fix-a","file":"missing.wav","text":"sample"}}')
            with self.assertRaises(FileNotFoundError): migration.migrate(root)
            self.assertEqual((root/'settings.json').read_bytes(),old['settings.json'])
            self.assertFalse(migration.journal_path(root).exists())

    def test_missing_model_is_renamed_once_without_copying(self):
        with TemporaryDirectory() as folder:
            root=Path(folder); legacy(root)
            (root/'Local Models').mkdir()
            original=root/'models/model.gguf'; identity=original.stat().st_ino
            original.rename(root/'Local Models/model.gguf')
            migration.migrate(root)
            self.assertEqual(original.stat().st_ino,identity)
            self.assertFalse((root/'Local Models/model.gguf').exists())

    def test_external_manuscript_is_not_moved_or_rewritten(self):
        with TemporaryDirectory() as folder:
            outer=Path(folder); root=outer/'install'; legacy(root)
            source=put(outer,'chapters/001.txt',b'An untouched invented chapter.')
            put(root,'volumes.json',json.dumps([{'name':'Book','source':str(source.parent)}]).encode())
            migration.migrate(root)
            self.assertEqual(source.read_bytes(),b'An untouched invented chapter.')
            self.assertEqual(json.loads((root/'Data/User/volumes.json').read_text())[0]['source'],str(source.parent))

    def test_junction_migration_is_refused_without_following_the_target(self):
        import subprocess
        with TemporaryDirectory() as folder:
            outer=Path(folder); root=outer/'install'; legacy(root)
            outside=outer/'outside'; outside.mkdir(); put(outside,'keep.txt',b'outside')
            link=root/'work/link'
            subprocess.run(['cmd','/c','mklink','/J',str(link),str(outside)],check=True,capture_output=True)
            try:
                with self.assertRaisesRegex(ValueError,'links'): migration.migrate(root)
                self.assertEqual((outside/'keep.txt').read_bytes(),b'outside')
            finally: link.rmdir()

    def test_unfinished_project_import_is_refused_before_layout_migration(self):
        with TemporaryDirectory() as folder:
            root=Path(folder); old=legacy(root)
            put(root,'projects-state/transaction/owner.json',b'{}')
            with self.assertRaisesRegex(ValueError,'unfinished Project import'): migration.migrate(root)
            self.assertEqual((root/'settings.json').read_bytes(),old['settings.json'])
            self.assertFalse(migration.journal_path(root).exists())

    def test_native_restore_tool_accepts_the_new_payload_layout_and_prior_releases(self):
        import subprocess
        import zipfile
        for prefix in ('','Data/Program/'):
            with self.subTest(prefix=prefix), TemporaryDirectory() as folder:
                root=Path(folder)
                script=put(root,'tools/restore_native.ps1',(ROOT/'tools/restore_native.ps1').read_bytes())
                archive=root/'payload.zip'
                with zipfile.ZipFile(archive,'w') as bundle:
                    bundle.writestr(prefix+'engine/build/synthetic.dll',b'synthetic runtime fixture')
                source=put(root,'Fixture.cs',b'class Fixture { static void Main() {} }')
                exe=root/'fixture.exe'
                subprocess.run(['C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe','/nologo',
                    '/out:'+str(exe),'/resource:'+str(archive)+',payload.zip',str(source)],check=True,capture_output=True)
                run=subprocess.run(['powershell.exe','-NoProfile','-File',str(script),'-Installer',str(exe)],capture_output=True)
                self.assertEqual(run.returncode,0,run.stdout+run.stderr)
                self.assertEqual((root/'build/native/engine/build/synthetic.dll').read_bytes(),b'synthetic runtime fixture')

    def test_program_preimage_junction_cannot_overwrite_an_external_file(self):
        import subprocess
        with TemporaryDirectory() as folder:
            base=Path(folder); root=base/'install'; paths=Layout(root); paths.prepare()
            put(root,'Data/Program/app.py',b'old program'); put(root,'Data/User/settings.json',b'author')
            external=put(base,'external/Data/Program/app.py',b'precious external file')
            before=root/'Data/State/install/before'; before.parent.mkdir(parents=True)
            subprocess.run(['cmd','/c','mklink','/J',str(before),str(base/'external')],check=True,capture_output=True)
            stage=base/'stage'; put(stage,'Data/Program/app.py',b'new program')
            manifest={'payload':{'sha256':'fixture'},'payload_files':[{'path':'Data/Program/app.py',
                       'sha256':hashlib.sha256(b'new program').hexdigest()}],'initial_state_files':[]}
            try:
                with self.assertRaises(ValueError): publication.publish(root,stage,manifest)
                self.assertEqual(external.read_bytes(),b'precious external file')
            finally: before.rmdir()
