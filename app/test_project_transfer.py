"""Project transfers on invented data only: no installed apps, engines, models or downloads."""
import hashlib
import asyncio
import json
from pathlib import Path
import shutil
import stat
import subprocess
import threading
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import zipfile

import numpy as np
import soundfile as sf
import fixed_voices
import glossary
import project
import project_api
import project_package as package
import project_transfer as transfer
import app as studio
from dialogue import segment
from test_video_jobs import request, async_request


class ProjectTransferTests(unittest.TestCase):
    def setUp(self):
        access = patch.object(studio,'project_access',type(studio.project_access)())
        access.start()
        self.addCleanup(access.stop)
        self.temp = TemporaryDirectory(prefix='project-transfer-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for module,name,value in [(project,'ROOT',self.root),(project,'WORK',self.root/'work'),
            (project,'SETTINGS_FILE',self.root/'settings.json'),(project,'VOLUMES_FILE',self.root/'volumes.json'),
            (glossary,'GLOSSARY_FILE',self.root/'characters.json'),(fixed_voices,'FOLDER',self.root/'voices'),
            (fixed_voices,'REGISTRY',self.root/'voices/registry.json'),(fixed_voices,'SAMPLES',self.root/'voices/samples.json')]:
            item = patch.object(module,name,value)
            item.start()
            self.addCleanup(item.stop)
        self.source = self.root/'chapters'
        self.source.mkdir()
        self.text = 'The lantern made a narrow circle on the floor. BOOK_TEXT_SENTINEL'
        (self.source/'001 - The Lamp.txt').write_text(self.text,encoding='utf-8')
        project.add_volume('The Lantern House',self.source)
        glossary.save([glossary.propose('Ada','female',[])])
        project.save_settings(project.load_settings())
        self.chapter = project.chapters('The Lantern House')[0]
        self.chapter.save_script({'rows':[['Ada',self.text,False,0]],'source_hash':project.text_hash(self.text),'report':''})
        reference = self.root/'reference.wav'
        sf.write(reference,.04*np.sin(2*np.pi*200*np.arange(100800)/24000),24000)
        self.voice = fixed_voices.fix('Ada',reference,'This is a newly written reference sentence for an invented voice.',{'seed':42})
        project.write_json(fixed_voices.SAMPLES,{'Ada':{'sample':'A newly written audition sentence.', 'real':[self.text]}})
        self.path = self.root/'incoming.abstudio'
        package.write_package(self.path,package.collect(package.PARTS))

    def files(self):
        return {str(p.relative_to(self.root)):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}

    def empty(self):
        glossary.save([])
        project.write_json(fixed_voices.REGISTRY,{})
        project.write_json(fixed_voices.SAMPLES,{})
        project.write_json(project.VOLUMES_FILE,[])
        self.chapter.script_file.unlink()
        for path in fixed_voices.FOLDER.glob('*.wav'):
            path.unlink()

    def preview(self, choices=None):
        incoming = package.read_package(self.path)
        choices = choices or {'parts':list(package.PARTS)}
        _, report = transfer.plan(incoming,choices)
        return incoming,choices,transfer.state_hash(),report

    def test_volume_ids_survive_export_and_import(self):
        original = project.volume_id(project.get_volume('The Lantern House'))
        incoming = package.read_package(self.path)
        self.assertEqual(incoming.volumes[0].get('id'), original)
        self.empty()
        writes, _ = transfer.plan(incoming, {'parts': ['volumes']})
        self.assertIn('volumes.json', writes)
        self.assertEqual(package.json_data(writes['volumes.json'])[0]['id'], original)

    def linked_package(self):
        """Repack with Ada linked to a context, a scoped alias and a scoped label; returns the volume ID."""
        import character_registry as registry
        volume = project.volume_id(project.get_volume('The Lantern House'))
        created = registry.context_edit(dict(action='create', name='Hall', volume=volume,
                                             revision=registry.snapshot()['revision']))
        hall = created['document']['organization']['contexts'][0]['id']
        state = registry.snapshot()
        state['document']['characters'][0]['aliases'] = ['the keeper']
        meta = state['document']['organization']['characters']['Ada']
        meta['volumes'], meta['contexts'] = [volume], [hall]
        meta['alias_scopes'] = {'the keeper': dict(volumes=[volume], contexts=[hall])}
        meta['labels'] = [dict(label='The keeper', contexts=[hall])]
        result = registry.plan(state)
        registry.apply(result['request'], result['plan_id'])
        package.write_package(self.path, package.collect(package.PARTS))
        return volume

    def fresh(self):
        self.empty()
        glossary.GLOSSARY_FILE.unlink()

    def test_context_links_import_into_an_empty_project(self):
        import character_registry as registry
        volume = self.linked_package()
        self.fresh()
        incoming, choices, state, report = self.preview()
        transfer.apply(incoming, choices, state, report)
        meta = registry.organization()['characters']['Ada']
        context = registry.organization()['contexts'][0]
        self.assertEqual((context['name'], context['volume']), ('Hall', volume))
        self.assertEqual((meta['volumes'], meta['contexts']), ([volume], [context['id']]))
        self.assertEqual(meta['alias_scopes']['the keeper'], dict(volumes=[volume], contexts=[context['id']]))
        self.assertEqual(registry.resolved_label('Ada', 'The Lantern House', [context['id']]), 'The keeper')
        self.assertEqual(registry.resolved_label('Ada', 'The Lantern House', []), 'Ada')
        self.assertNotIn('the keeper', registry.alias_map('The Lantern House', []))

    def test_import_matches_volumes_by_name_not_by_id(self):
        import character_registry as registry
        self.linked_package()
        self.fresh()
        project.add_volume('The Lantern House', self.source)
        volumes = project.volumes()
        volumes[0]['id'] = 'volume-local'
        project.write_json(project.VOLUMES_FILE, volumes)
        incoming, choices, state, report = self.preview({'parts': ['cast']})
        transfer.apply(incoming, choices, state, report)
        meta = registry.organization()['characters']['Ada']
        self.assertEqual(meta['volumes'], ['volume-local'])
        self.assertEqual(registry.organization()['contexts'][0]['volume'], 'volume-local')
        self.assertEqual(meta['alias_scopes']['the keeper']['volumes'], ['volume-local'])

    def test_scoped_alias_is_not_imported_when_its_volume_is_missing(self):
        import character_registry as registry
        self.linked_package()
        self.fresh()
        incoming, choices, state, report = self.preview({'parts': ['cast']})
        character = next(item for item in report['items'] if item['kind'] == 'character')
        self.assertIn('the keeper', character['reason'])
        transfer.apply(incoming, choices, state, report)
        self.assertEqual(registry.organization()['contexts'], [])
        self.assertNotIn('alias_scopes', registry.organization()['characters']['Ada'])
        self.assertEqual(glossary.aliases_of(glossary.load()[0][1]), [])
        self.assertNotIn('the keeper', registry.alias_map(None, []))

    def test_preview_is_read_only_and_roundtrip_undo_restores_exact_state(self):
        self.empty()
        before = transfer.capture()
        files = self.files()
        incoming,choices,state,report = self.preview()
        self.assertEqual(files,self.files())
        result = transfer.apply(incoming,choices,state,report)
        self.assertTrue(result['backup'])
        self.assertEqual(glossary.load()[0][0],'Ada')
        self.assertEqual(fixed_voices.get('Ada')['id'],self.voice['id'])
        self.assertEqual(self.chapter.script()['rows'][0][1],self.text)
        self.assertEqual(hashlib.sha256((fixed_voices.FOLDER/self.voice['file']).read_bytes()).hexdigest(),
                         hashlib.sha256(incoming.files['voices/'+self.voice['file']]).hexdigest())
        self.assertFalse(list(project.WORK.rglob('*.wav')))
        transfer.undo()
        self.assertEqual(before,transfer.capture())
        self.assertFalse((fixed_voices.FOLDER/self.voice['file']).exists())
        self.assertEqual(len(transfer.history()['backups']),2)

    def test_conflicts_default_to_keep_mine_and_settings_are_opt_in(self):
        incoming = package.read_package(self.path)
        writes,report = transfer.plan(incoming,{})
        self.assertFalse(writes)
        for kind in ('character','voice','script','settings'):
            self.assertTrue(any(row['kind']==kind and row['action']=='skip' for row in report['items']))
        incoming.characters[0][3] = 'Updated personality'
        incoming.settings['narrator']['seed'] = 123
        choices = {'parts':['settings','cast','volumes'],'characters':['Ada'],'voices':['Ada'],
                   'scripts':['The Lantern House/001 - The Lamp']}
        writes,report = transfer.plan(incoming,choices)
        self.assertIn('characters.json',writes)
        self.assertIn('settings.json',writes)
        self.assertIn('work/The Lantern House/001 - The Lamp/script.json',writes)
        transfer.apply(incoming,choices,transfer.state_hash(),report)
        self.assertEqual(glossary.load()[0][3],'Updated personality')
        self.assertEqual(project.load_settings()['narrator']['seed'],123)
        transfer.undo()
        self.assertEqual(project.load_settings()['narrator']['seed'],42)
        self.assertEqual(project.load_settings()['narrator']['temperature'],.55)

    def test_script_hash_mismatch_is_skipped_without_changing_text(self):
        self.chapter.script_file.unlink()
        (self.source/'001 - The Lamp.txt').write_text('A changed opening.',encoding='utf-8')
        incoming,choices,state,report = self.preview()
        item = next(row for row in report['items'] if row['kind']=='script')
        self.assertIn('Text has changed',item['reason'])
        self.assertEqual(incoming.scripts[('The Lantern House','001 - The Lamp')]['rows'][0][1],self.text)
        self.assertFalse(any(name.startswith('work/') for name in transfer.plan(incoming,choices)[0]))

    def test_missing_folder_can_be_located_without_writing_at_preview(self):
        self.empty()
        incoming = package.read_package(self.path)
        incoming.volumes[0]['source'] = str(self.root/'missing')
        writes,report = transfer.plan(incoming,{'parts':['cast','volumes']})
        self.assertTrue(next(row for row in report['items'] if row['kind']=='volume')['missing'])
        self.assertFalse(any(name.startswith('work/') for name in writes))
        before = self.files()
        writes,report = transfer.plan(incoming,{'parts':['cast','volumes'],'locations':{'The Lantern House':str(self.source)}})
        self.assertTrue(any(name.startswith('work/') for name in writes))
        self.assertEqual(before,self.files())

    def test_network_source_is_not_contacted_implicitly(self):
        self.empty()
        incoming = package.read_package(self.path)
        incoming.volumes[0]['source'] = '//untrusted.example/share'
        original = Path.is_dir
        def check(path):
            self.assertNotIn('untrusted.example',str(path))
            return original(path)
        with patch.object(Path,'is_dir',check):
            writes,report = transfer.plan(incoming,{'parts':['cast','volumes']})
        self.assertFalse(any(name.startswith('work/') for name in writes))

    def test_untrusted_sources_are_not_persisted_and_can_be_located(self):
        self.empty()
        incoming = package.read_package(self.path)
        for source in ('\\\\untrusted.example\\share','//untrusted.example/share',
                       '\\\\?\\UNC\\untrusted.example\\share','\\\\?\\C:\\Books',
                       'C:relative','relative-folder','/rooted-folder','file://untrusted.example/share'):
            incoming.volumes[0]['source'] = source
            with self.subTest(source=source):
                with self.assertRaisesRegex(ValueError,'absolute local drive'):
                    project.add_volume('Untrusted volume',source)
                writes,report = transfer.plan(incoming,{'parts':['cast','volumes']})
                self.assertFalse('volumes.json' in writes)
                self.assertTrue(any(row['kind']=='volume' and row['action']=='skip'
                                    and 'local' in row['reason'].lower() for row in report['items']))
                self.assertFalse(any(name.startswith('work/') for name in writes))
                writes,_ = transfer.plan(incoming,{'parts':['cast','volumes'],
                    'locations':{'The Lantern House':str(self.source)}})
                self.assertEqual(package.json_data(writes['volumes.json'])[0]['source'],str(self.source))
                self.assertTrue(any(name.startswith('work/') for name in writes))

    def test_overview_never_contacts_an_old_network_volume(self):
        project.write_json(project.VOLUMES_FILE,[{'name':'Untrusted volume','source':'//untrusted.example/share'}])
        original = Path.is_dir
        def check(path):
            self.assertNotIn('untrusted.example',str(path))
            return original(path)
        with patch.object(Path,'is_dir',check):
            code,result = request('GET','/api/overview',{})
        self.assertEqual(code,200)
        self.assertIn('local',result['volumes'][0]['error'].lower())

    def test_forged_script_with_correct_hash_is_skipped(self):
        self.chapter.script_file.unlink()
        incoming = package.read_package(self.path)
        for rows in ([['Ada','Unrelated injected narration.',False]],
                     [['Ada',self.text+' Unwanted extra text.',False]],
                     [['Ada','BOOK_TEXT_SENTINEL',False]]):
            incoming.scripts[('The Lantern House','001 - The Lamp')]['rows']=rows
            with self.subTest(rows=rows):
                writes,report = transfer.plan(incoming,{'parts':['cast','volumes']})
                self.assertFalse(any(name.startswith('work/') for name in writes))
                self.assertTrue(any(row['kind']=='script' and 'text' in row['reason'].lower()
                                    and row['action']=='skip' for row in report['items']))

    def test_unchanged_segmented_text_accepts_split_rows_and_whitespace(self):
        text='Chapter 1 — The Lamp\n\n“Wait here,” Ada said.\n\nThe light\nwent out.\n\n***'
        (self.source/'001 - The Lamp.txt').write_text(text,encoding='utf-8')
        text=self.chapter.text()
        self.chapter.script_file.unlink()
        incoming=package.read_package(self.path)
        rows=[['Scene break' if item.kind=='pause' else 'Narrator',item.text,False]
              for item in segment(text)]
        rows[-2][1]='  The light   went out.  '
        rows[0:1]=[['Narrator','Chapter 1',False],['Narrator','— The Lamp',True]]
        incoming.scripts[('The Lantern House','001 - The Lamp')]={'source_hash':project.text_hash(text),'rows':rows}
        writes,_=transfer.plan(incoming,{'parts':['cast','volumes']})
        result=package.json_data(writes['work/The Lantern House/001 - The Lamp/script.json'])
        self.assertEqual(result['rows'],rows)

    def test_display_name_controls_reserved_and_case_duplicates_are_rejected(self):
        for name in ('','\tAda','Ada\x7f','Ada\u0085','Narrator','narrator','Unassigned','Scene break','A'*1025):
            with self.subTest(name=name),self.assertRaises(ValueError):
                package.cast_rows({'characters':[{'name':name,'gender':'unknown'}]})
        with self.assertRaisesRegex(ValueError,'letter case'):
            package.cast_rows({'characters':[{'name':'Ada','gender':'female'},{'name':'ADA','gender':'female'}]})

    def test_display_names_roundtrip_and_backup_are_not_filesystem_components(self):
        names=['Dr.','Capt. Kerr.','Voice: Radio','Ada/Tom','The "Old" Man','A'*120]
        glossary.save([glossary.propose(name,'unknown',[]) for name in names])
        project.write_json(fixed_voices.REGISTRY,{names[0]:self.voice})
        project.write_json(fixed_voices.SAMPLES,{names[0]:{'sample':'A newly written sample.'}})
        self.chapter.save_script({'source_hash':project.text_hash(self.text),
                                  'rows':[[names[0],self.text,False]]})
        parsed=package.write_package(self.path,package.collect(package.PARTS))
        self.assertEqual([row[0] for row in parsed.characters],names)
        self.assertTrue(transfer.backup().is_file())
        self.empty()
        incoming,choices,state,report=self.preview()
        transfer.apply(incoming,choices,state,report)
        self.assertEqual([row[0] for row in glossary.load()],names)
        self.assertEqual(self.chapter.script()['rows'][0][0],names[0])
        # A second import and its Undo must also back up this existing cast successfully.
        before=transfer.capture()
        incoming.settings['author']='An invented update'
        _,report=transfer.plan(incoming,choices)
        transfer.apply(incoming,choices,transfer.state_hash(),report)
        transfer.undo()
        self.assertEqual(before,transfer.capture())

    def test_native_dialog_does_not_block_navigation_or_worker_status(self):
        entered,release=threading.Event(),threading.Event()
        def dialog(_):
            entered.set()
            if not release.wait(3): raise RuntimeError('Synthetic dialog timed out')
            return None
        async def exercise():
            task=asyncio.create_task(async_request('POST','/api/project/import/preview',{}))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait,1))
                navigation=await asyncio.wait_for(async_request('GET','/api/characters',{}),.5)
                status=await asyncio.wait_for(async_request('GET','/api/status',{}),.5)
                self.assertEqual((navigation[0],status[0]),(200,200))
            finally:
                release.set()
                await task
        with patch.object(project_api,'native_dialog',dialog):
            asyncio.run(exercise())

    def test_job_started_during_dialog_is_rechecked_before_reading_the_package(self):
        before=self.files()
        def dialog(_):
            studio.worker._state['running']=True
            return self.path
        with patch.dict(studio.worker._state,{'running':False}),patch.object(project_api,'native_dialog',dialog):
            self.assertEqual(request('POST','/api/project/import/preview',{})[0],400)
        self.assertEqual(before,self.files())

    def test_slow_voice_preview_allows_other_readers(self):
        entered,release=threading.Event(),threading.Event()
        def preview(*args):
            entered.set()
            if not release.wait(3): raise RuntimeError('Synthetic preview timed out')
            return self.root/'work/previews/demo.wav'
        async def exercise():
            task=asyncio.create_task(async_request('POST','/api/narrator/preview',
                {'narrator':project.load_settings()['narrator']}))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait,1))
                code,_=await asyncio.wait_for(async_request('GET','/api/characters',{}),.5)
                self.assertEqual(code,200)
            finally:
                release.set()
                await task
        with patch.object(studio,'preview_voice',preview):
            asyncio.run(exercise())

    def test_import_writer_blocks_readers_until_complete_but_status_stays_live(self):
        self.empty()
        with patch.object(project_api,'native_dialog',return_value=self.path):
            code,preview=request('POST','/api/project/import/preview',{})
        self.assertEqual(code,200)
        entered,release=threading.Event(),threading.Event()
        original=transfer.transact
        def transact(writes):
            entered.set()
            if not release.wait(3): raise RuntimeError('Synthetic transaction timed out')
            original(writes)
        async def exercise():
            writer=asyncio.create_task(async_request('POST','/api/project/import/apply',
                {'token':preview['token'],'confirm':True}))
            reader=None
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait,1))
                reader=asyncio.create_task(async_request('GET','/api/characters',{}))
                with self.assertRaises(asyncio.TimeoutError):
                    await asyncio.wait_for(asyncio.shield(reader),.1)
                self.assertEqual((await asyncio.wait_for(async_request('GET','/api/status',{}),.5))[0],200)
                self.assertFalse(studio.worker.status()['running'])
                with self.assertRaisesRegex(ValueError,'transfer is in progress'):
                    studio.worker.submit('The Lantern House',[],[])
            finally:
                release.set()
                self.assertEqual((await writer)[0],200)
                if reader:
                    self.assertEqual((await reader)[0],200)
        with patch.object(transfer,'transact',transact):
            asyncio.run(exercise())

    def test_unrecognized_recovery_state_fails_without_touching_data(self):
        before=transfer.capture()
        folder=self.root/'projects-state/transaction'
        folder.mkdir(parents=True)
        project.write_json(folder/'owner.json',{'format':'unknown'})
        with self.assertRaisesRegex(RuntimeError,'manual review'):
            transfer.recover()
        self.assertEqual(before,transfer.capture())
        self.assertTrue(folder.is_dir())

    def test_cancelled_import_request_keeps_gate_until_transaction_finishes(self):
        self.empty()
        with patch.object(project_api,'native_dialog',return_value=self.path):
            _,preview=request('POST','/api/project/import/preview',{})
        entered,release=threading.Event(),threading.Event()
        original=transfer.transact
        def transact(writes):
            entered.set()
            if not release.wait(3): raise RuntimeError('Synthetic cancellation timed out')
            original(writes)
        async def exercise():
            writer=asyncio.create_task(async_request('POST','/api/project/import/apply',
                {'token':preview['token'],'confirm':True}))
            reader=None
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait,1))
                writer.cancel()
                await asyncio.sleep(.05)
                reader=asyncio.create_task(async_request('GET','/api/characters',{}))
                with self.assertRaises(asyncio.TimeoutError):
                    await asyncio.wait_for(asyncio.shield(reader),.1)
            finally:
                release.set()
                try:
                    await writer
                except asyncio.CancelledError:
                    pass
                if reader:
                    await reader
        with patch.object(transfer,'transact',transact):
            asyncio.run(exercise())
        self.assertEqual(glossary.load()[0][0],'Ada')

    def test_cast_only_contains_no_chapter_text_or_real_book_samples(self):
        files = package.collect(['cast'])
        self.assertFalse(any(name.startswith('scripts/') for name in files))
        self.assertNotIn(b'BOOK_TEXT_SENTINEL',b''.join(files.values()))
        self.assertNotIn('volumes.json',files)
        self.assertNotIn('real',package.json_data(files['voices/samples.json'])['Ada'])

    def test_changed_project_or_archive_invalidates_preview(self):
        self.empty()
        incoming,choices,state,report = self.preview()
        project.save_settings({**project.load_settings(),'author':'An invented author'})
        with self.assertRaisesRegex(ValueError,'changed after preview'):
            transfer.apply(incoming,choices,state,report)

    def test_corrupt_wav_and_wrong_id_are_rejected(self):
        files = package.collect(['cast'])
        files['voices/'+self.voice['file']] = b'not a wave file'
        with self.assertRaises(ValueError):
            package.write_package(self.path,files)
        files = package.collect(['cast'])
        registry = package.json_data(files['voices/registry.json'])
        registry['Ada']['id'] = 'fix-0000000000'
        files['voices/registry.json'] = package.encoded(registry)
        with self.assertRaisesRegex(ValueError,'ID does not match'):
            package.write_package(self.path,files)

    def test_matching_id_cannot_make_unreadable_or_short_wav_valid(self):
        files = package.collect(['cast'])
        for content in (b'not a wav',):
            registry = package.json_data(files['voices/registry.json'])
            registry['Ada']['id'] = 'fix-'+hashlib.sha1(content+registry['Ada']['text'].encode()).hexdigest()[:10]
            changed = {**files,'voices/registry.json':package.encoded(registry),'voices/'+self.voice['file']:content}
            with self.assertRaises(ValueError):
                package.write_package(self.path,changed)

    def test_hostile_archive_paths_duplicates_and_links_are_rejected(self):
        for name in ('/absolute.json','../escape.json','safe/../escape.json','C:/escape.json',
                     'safe\\escape.json','CON.json','folder//bad.json','folder/trailing .json '):
            with zipfile.ZipFile(self.path,'w') as archive:
                archive.writestr(name,b'{}')
            with self.subTest(name=name),self.assertRaises(ValueError):
                package.read_package(self.path)
        with zipfile.ZipFile(self.path,'w') as archive:
            archive.writestr('safe.json',b'{}')
            archive.writestr('SAFE.json',b'{}')
        with self.assertRaisesRegex(ValueError,'Duplicate'):
            package.read_package(self.path)
        link = zipfile.ZipInfo('link.json')
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK|0o777)<<16
        with zipfile.ZipFile(self.path,'w') as archive:
            archive.writestr(link,b'../../outside')
        with self.assertRaisesRegex(ValueError,'Unsafe'):
            package.read_package(self.path)

    def test_archive_limits_and_future_versions_and_unknown_entries(self):
        files = package.collect(['settings'])
        meta = package.json_data(files['project.json'])
        meta['version'] = 2
        with self.assertRaisesRegex(ValueError,'version'):
            package.write_package(self.path,{**files,'project.json':package.encoded(meta)})
        with zipfile.ZipFile(self.path,'w',zipfile.ZIP_DEFLATED) as archive:
            for name,content in files.items(): archive.writestr(name,content)
            archive.writestr('extra.exe',b'untrusted, never extracted')
        self.assertIn('extra.exe',package.read_package(self.path).ignored)
        for constant in ('MAX_ENTRIES','MAX_TOTAL','MAX_JSON'):
            with patch.object(package,constant,1),self.assertRaises(ValueError):
                package.read_package(self.path)

    def test_duplicate_json_and_invalid_names_or_gender_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'Duplicate JSON'):
            package.json_data(b'{"x":1,"x":2}')
        for entry in ({'name':'\x00Ada','gender':'female'},{'name':'Ada','gender':'other'},
                      {'name':'Narrator','gender':'male'}):
            with self.assertRaises(ValueError):
                package.cast_rows({'characters':[entry]})

    def test_interruption_rolls_back_all_files(self):
        self.empty()
        before = transfer.capture()
        incoming,choices,state,report = self.preview()
        original = Path.replace
        failed = False
        def replace(path,destination):
            nonlocal failed
            if not failed and path.name=='registry.json' and 'after' in path.parts:
                failed = True
                raise OSError('Synthetic interrupted import')
            return original(path,destination)
        with patch.object(Path,'replace',replace),self.assertRaisesRegex(OSError,'interrupted'):
            transfer.apply(incoming,choices,state,report)
        self.assertTrue(failed)
        self.assertEqual(before,transfer.capture())
        self.assertFalse((self.root/'projects-state/last-import.json').exists())

    def test_abrupt_process_exit_is_recovered_before_next_start(self):
        before = transfer.capture()
        code = '''
import os,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import project,project_transfer
project.ROOT=Path(sys.argv[2])
original=Path.replace
def replace(path,destination):
    result=original(path,destination)
    if path.name=='characters.json' and 'after' in path.parts:
        os._exit(24)
    return result
Path.replace=replace
project_transfer.transact({'characters.json':b'{"version":2,"characters":[]}', 'settings.json':b'{}'})
'''
        result = subprocess.run([sys.executable,'-B','-c',code,str(Path(transfer.__file__).parent),str(self.root)])
        self.assertEqual(result.returncode,24)
        self.assertTrue(transfer.recover())
        self.assertEqual(before,transfer.capture())

    def test_native_dialog_export_and_import_api_and_origin_filter(self):
        output = self.root/'exported.abstudio'
        with patch.object(project_api,'native_dialog',return_value=output):
            code,preview = request('POST','/api/project/export/preview',{'parts':['cast']})
        self.assertEqual(code,200)
        self.assertFalse(output.exists())
        self.assertEqual(request('POST','/api/project/export/apply',{'token':preview['token']})[0],400)
        self.assertEqual(request('POST','/api/project/export/apply',{'token':preview['token'],'confirm':True})[0],200)
        self.assertTrue(output.exists())
        self.empty()
        with patch.object(project_api,'native_dialog',return_value=self.path) as dialog:
            self.assertEqual(request('POST','/api/project/import/preview',{},'https://foreign.example')[0],403)
            dialog.assert_not_called()
            code,preview = request('POST','/api/project/import/preview',{})
        self.assertEqual(code,200)
        self.assertEqual(request('POST','/api/project/import/apply',{'token':preview['token'],'confirm':True})[0],200)
        code,undo = request('POST','/api/project/undo/preview',{})
        self.assertEqual(code,200)
        self.assertEqual(request('POST','/api/project/undo/apply',{'token':undo['token'],'confirm':True})[0],200)
        self.assertEqual(glossary.load(),[])

    def test_export_requires_explicit_overwrite_and_stale_archive_is_refused(self):
        before = self.path.read_bytes()
        with patch.object(project_api,'native_dialog',return_value=self.path):
            code,preview = request('POST','/api/project/export/preview',{'parts':['settings']})
        self.assertEqual(code,200)
        self.assertEqual(request('POST','/api/project/export/apply',{'token':preview['token'],'confirm':True})[0],400)
        self.assertEqual(before,self.path.read_bytes())
        with patch.object(project_api,'native_dialog',return_value=self.path):
            code,preview = request('POST','/api/project/import/preview',{})
        self.path.write_bytes(before+b'changed')
        self.assertEqual(request('POST','/api/project/import/apply',{'token':preview['token'],'confirm':True})[0],400)

    def test_busy_worker_refuses_transfer(self):
        with patch.dict(studio.worker._state,{'running':True}),patch.object(project_api,'native_dialog') as dialog:
            self.assertEqual(request('POST','/api/project/import/preview',{})[0],400)
            dialog.assert_not_called()

    def test_voice_conflict_replaces_only_when_selected_and_undo_restores_it(self):
        old = fixed_voices.get('Ada')
        before = transfer.capture()
        replacement = self.root/'replacement.wav'
        sf.write(replacement,.04*np.sin(2*np.pi*320*np.arange(110400)/24000),24000)
        text = 'This is a different newly written synthetic reference sentence.'
        digest = hashlib.sha1(replacement.read_bytes()+text.encode()).hexdigest()[:10]
        incoming = package.read_package(self.path)
        entry = {**old,'id':'fix-'+digest,'file':'ada-'+digest+'.wav','text':text}
        incoming.registry['Ada'] = package.check_voice(entry,replacement.read_bytes())
        incoming.files['voices/'+entry['file']] = replacement.read_bytes()
        writes,_ = transfer.plan(incoming,{'parts':['cast']})
        self.assertNotIn('voices/registry.json',writes)
        choices = {'parts':['cast'],'voices':['Ada']}
        _,report = transfer.plan(incoming,choices)
        transfer.apply(incoming,choices,transfer.state_hash(),report)
        self.assertEqual(fixed_voices.get('Ada')['id'],entry['id'])
        transfer.undo()
        self.assertEqual(before,transfer.capture())

    def test_undo_refuses_modified_backup_without_changing_project(self):
        self.empty()
        incoming,choices,state,report = self.preview()
        result = transfer.apply(incoming,choices,state,report)
        path = self.root/'projects-backup'/result['backup']
        path.write_bytes(path.read_bytes()+b'changed')
        before = transfer.capture()
        with self.assertRaisesRegex(ValueError,'backup has changed'):
            transfer.undo()
        self.assertEqual(before,transfer.capture())

    def test_settings_unknown_keys_are_ignored_and_invalid_values_are_rejected(self):
        incoming = project.load_settings()
        incoming['future_key'] = 'ignored'
        incoming['narrator']['future_key'] = 'ignored'
        result = package.clean_settings(incoming)
        self.assertNotIn('future_key',result)
        self.assertNotIn('future_key',result['narrator'])
        for value in (float('nan'),-1,True):
            with self.assertRaises(ValueError):
                package.clean_settings({**incoming,'dialogue_pause':value})

    def test_runtime_projects_are_never_public_source_assets(self):
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
        from audit_public import public_file
        for name in ('app/projects-backup/private.abstudio','app/projects-state/reports/private.json',
                     'app/work/Book/Chapter/script.json','app/export/Book/private.txt','app/private.abstudio'):
            self.assertFalse(public_file(name),name)
        self.assertTrue(public_file('app/project_transfer.py'))
        self.assertTrue(public_file('docs/PROJECT_FORMAT.md'))


if __name__=='__main__':
    unittest.main()
