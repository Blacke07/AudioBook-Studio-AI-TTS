"""Installer integrity tests. Never read or write the user's working app."""
import hashlib
import io
from contextlib import redirect_stdout
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


core = load('install_core', 'installer/install.py')
state = load('state', 'installer/state.py')
launcher = load('launcher', 'installer/launcher.py')


class InstallerTests(unittest.TestCase):
    def test_cold_ollama_health_timeout_waits_for_the_existing_startup_deadline(self):
        with patch.object(launcher, 'urlopen', side_effect=TimeoutError):
            self.assertIsNone(launcher.ollama_ready())

    def test_existing_ollama_must_have_exact_model_not_just_the_same_tag(self):
        launcher.require_model({'models':[{'name':'gemma4:12b','digest':'exact'}]},'gemma4:12b','exact')
        for tags in (None, {'models':[]}, {'models':[{'name':'gemma4:12b','digest':'different'}]},
                     {'models':[{'name':'gemma4:12b','digest':'exact'}]}):   # right model, but another model set
            with self.assertRaisesRegex(RuntimeError,'pinned Gemma'):
                launcher.require_model(tags,'gemma4:e4b-it-qat','exact')

    def test_checksum_rejects_a_same_size_corrupted_model(self):
        with TemporaryDirectory() as folder:
            file = Path(folder) / 'model.gguf'
            file.write_bytes(b'wrong')
            item = {'size':5, 'sha256':hashlib.sha256(b'right').hexdigest()}
            self.assertFalse(core.matches(file, item))

    def test_manual_copy_preserves_source_and_rejects_conflicts(self):
        with TemporaryDirectory() as folder:
            source, target = Path(folder) / 'source', Path(folder) / 'target'
            source.write_bytes(b'correct')
            item = {'size':7,'sha256':hashlib.sha256(b'correct').hexdigest()}
            core.import_model(source, target, item)
            self.assertEqual(source.read_bytes(), b'correct')
            self.assertEqual(target.read_bytes(), b'correct')
            target.write_bytes(b'incorrect')
            with self.assertRaises(RuntimeError): core.import_model(source, target, item)

    def test_local_models_move_without_copying_and_retry_keeps_the_same_file(self):
        with TemporaryDirectory() as folder:
            root=Path(folder); staging=root/'Local Models'; staging.mkdir()
            (staging/'my notes.txt').write_bytes(b'keep me')
            item={'size':7,'sha256':hashlib.sha256(b'correct').hexdigest()}
            for name in ('model.gguf','ollama/blobs/sha256-example'):
                source=staging/name; source.parent.mkdir(parents=True,exist_ok=True); source.write_bytes(b'correct')
                target=root/'models'/name; identity=source.stat().st_ino
                with patch.object(core.shutil,'copyfile',side_effect=AssertionError('Model data was copied')):
                    core.import_model(source,target,item,staging=staging)
                    core.import_model(source,target,item,staging=staging)  # Resume after the move already finished.
                self.assertFalse(source.exists())
                self.assertEqual(target.stat().st_ino,identity)
                self.assertEqual(target.read_bytes(),b'correct')
            self.assertEqual((staging/'my notes.txt').read_bytes(),b'keep me')

    def test_external_model_library_is_copied_even_with_installation_staging_enabled(self):
        with TemporaryDirectory() as folder:
            root=Path(folder); source=root/'library/model.gguf'; source.parent.mkdir(); source.write_bytes(b'correct')
            target=root/'app/models/model.gguf'; item={'size':7,'sha256':hashlib.sha256(b'correct').hexdigest()}
            core.import_model(source,target,item,staging=root/'app/Local Models')
            self.assertEqual(source.read_bytes(),b'correct')
            self.assertEqual(target.read_bytes(),b'correct')
            self.assertNotEqual(source.stat().st_ino,target.stat().st_ino)

    def test_bad_staged_models_or_destination_conflicts_never_consume_source(self):
        with TemporaryDirectory() as folder:
            root=Path(folder); staging=root/'Local Models'; staging.mkdir()
            source=staging/'model.gguf'; target=root/'models/model.gguf'
            item={'size':7,'sha256':hashlib.sha256(b'correct').hexdigest()}
            source.write_bytes(b'invalid')
            with self.assertRaisesRegex(RuntimeError,'pinned model'): core.import_model(source,target,item,staging)
            self.assertEqual(source.read_bytes(),b'invalid'); self.assertFalse(target.exists())
            source.write_bytes(b'correct'); target.parent.mkdir(); target.write_bytes(b'unknown')
            with self.assertRaisesRegex(RuntimeError,'different file'): core.import_model(source,target,item,staging)
            self.assertEqual(source.read_bytes(),b'correct'); self.assertEqual(target.read_bytes(),b'unknown')

    def test_staged_junction_is_refused_without_moving_external_data(self):
        with TemporaryDirectory() as folder:
            root=Path(folder); staging=root/'Local Models'; staging.mkdir()
            external=root/'external'; external.mkdir(); (external/'model.gguf').write_bytes(b'correct')
            junction=staging/'ollama'
            subprocess.run(['cmd','/c','mklink','/J',str(junction),str(external)],check=True,capture_output=True)
            try:
                item={'size':7,'sha256':hashlib.sha256(b'correct').hexdigest()}
                with self.assertRaisesRegex(RuntimeError,'must not use links'):
                    core.import_model(junction/'model.gguf',root/'models/model.gguf',item,staging)
                self.assertEqual((external/'model.gguf').read_bytes(),b'correct')
                self.assertFalse((root/'models').exists())
            finally: junction.rmdir()

    def test_failed_post_move_check_keeps_file_and_reports_its_location(self):
        with TemporaryDirectory() as folder:
            root=Path(folder); staging=root/'Local Models'; staging.mkdir()
            source=staging/'model.gguf'; source.write_bytes(b'correct'); target=root/'models/model.gguf'
            with patch.object(core,'matches',side_effect=[True,False]):
                with self.assertRaisesRegex(RuntimeError,'file retained at'):
                    core.import_model(source,target,{},staging)
            self.assertEqual(target.read_bytes(),b'correct'); self.assertFalse(source.exists())

    def test_install_moves_both_model_families_and_resumes_after_partial_transfer(self):
        from argparse import Namespace
        with TemporaryDirectory() as folder:
            root=Path(folder); staging=root/'Local Models'; staging.mkdir()
            marker=root/'.studio-install-incomplete'; marker.write_text('AudioBookStudio-Installer-1')
            manifest=json.loads((ROOT/'manifest.json').read_text()); name=manifest['default_profile']
            wanted={manifest['profiles'][name][key] for key in core.PROFILE_FILES}
            expected={}
            for item in manifest['models']:
                if item['name'] not in wanted: continue
                content=('Qwen '+item['name']).encode(); item.update(size=len(content),sha256=hashlib.sha256(content).hexdigest())
                expected[item['name']]=content
            gemma=manifest['gemma_models'][manifest['profiles'][name]['gemma']]
            for index,item in enumerate(gemma['blobs']):
                content=('Gemma '+str(index)).encode(); item.update(size=len(content),digest='sha256:'+hashlib.sha256(content).hexdigest())
                expected['ollama/blobs/'+item['digest'].replace(':','-')]=content
            identities={}
            for relative,content in expected.items():
                source=staging/relative; source.parent.mkdir(parents=True,exist_ok=True); source.write_bytes(content)
                identities[relative]=source.stat().st_ino
            (staging/'my notes.txt').write_text('preserve')
            payload=root/'payload.zip'; ffmpeg=root/'ffmpeg.zip'; ollama=root/'ollama.zip'
            for archive,entries in [(payload,{'app.py':b'# synthetic fixture'}),
                                     (ffmpeg,{'ffmpeg/bin/ffmpeg.exe':b'fake','ffmpeg/bin/ffprobe.exe':b'fake'}),
                                     (ollama,{'ollama.exe':b'fake'})]:
                with zipfile.ZipFile(archive,'w') as bundle:
                    for path,content in entries.items(): bundle.writestr(path,content)
            manifest['payload']={'size':payload.stat().st_size,'sha256':core.sha256(payload)}
            spec=root/'manifest.json'; spec.write_text(json.dumps(manifest))
            args=Namespace(target=root,bundle=payload,manifest=spec,cache=root/'cache',manual_models=staging,profile=name)
            downloads={manifest['ffmpeg']['name']:ffmpeg,manifest['ollama']['name']:ollama}
            original=core.import_model; calls=0
            def interrupted(*values,**options):
                nonlocal calls
                calls+=1
                if calls==2: raise RuntimeError('simulated interruption')
                return original(*values,**options)
            with patch.object(core,'hardware'),patch.object(core,'run'),\
                    patch.object(core.shutil,'disk_usage',return_value=Namespace(free=10**15)),\
                    patch.object(core,'download',side_effect=lambda item,cache:downloads[item['name']]),\
                    redirect_stdout(io.StringIO()):
                with patch.object(core,'import_model',side_effect=interrupted):
                    with self.assertRaisesRegex(RuntimeError,'simulated interruption'): core.install(args)
                self.assertTrue(marker.exists())
                self.assertEqual(sum(not (staging/name).exists() for name in expected),1)
                core.install(args)
            self.assertFalse(marker.exists())
            for relative,content in expected.items():
                self.assertFalse((staging/relative).exists(),relative)
                target=root/'models'/relative
                self.assertEqual(target.read_bytes(),content)
                self.assertEqual(target.stat().st_ino,identities[relative])
            self.assertEqual((staging/'my notes.txt').read_text(),'preserve')

    def test_zip_cannot_write_outside_installation(self):
        with TemporaryDirectory() as folder:
            folder = Path(folder)
            archive = folder / 'bad.zip'
            with zipfile.ZipFile(archive,'w') as package:
                package.writestr('../escaped.txt','bad')
            with self.assertRaises(RuntimeError): core.safe_extract(archive, folder / 'target')
            self.assertFalse((folder / 'escaped.txt').exists())

    def test_normal_zip_extracts(self):
        with TemporaryDirectory() as folder:
            folder=Path(folder)
            with zipfile.ZipFile(folder/'ok.zip','w') as archive:
                archive.writestr('web/index.html','fine')
            core.safe_extract(folder/'ok.zip',folder/'target')
            self.assertEqual((folder/'target/web/index.html').read_text(),'fine')

    def test_existing_unmarked_installation_is_refused(self):
        from argparse import Namespace
        with TemporaryDirectory() as folder:
            root=Path(folder)
            config=root/'settings.json'
            config.write_text('personal')
            with self.assertRaises(RuntimeError): core.install(Namespace(target=root))
            self.assertEqual(config.read_text(),'personal')

    def test_command_line_refusal_does_not_even_create_a_log(self):
        with TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'settings.json').write_text('personal')
            result=subprocess.run([sys.executable,str(ROOT/'installer/install.py'),'--target',str(root),
                                   '--bundle','missing','--manifest','missing','--cache','missing'],capture_output=True)
            self.assertNotEqual(result.returncode,0)
            self.assertEqual([file.name for file in root.iterdir()],['settings.json'])

    def test_initial_state_includes_settings_and_referenced_voices_only(self):
        with TemporaryDirectory() as folder:
            root=Path(folder)
            self.voice_fixture(root)
            (root/'chapter.txt').write_text('Private manuscript')
            (root/'voices/unused.wav').write_bytes(b'old take')
            (root/'volumes.json').write_text('[]')
            contents=state.collect(root)
            self.assertEqual(contents['settings.json'],b'{"narrator":{"temperature":0.55,"seed":42}}')
            self.assertEqual(contents['voices/narrator.wav'],b'approved voice')
            self.assertNotIn('chapter.txt',contents)
            self.assertEqual(contents['volumes.json'], b'[]')
            self.assertNotIn('voices/unused.wav',contents)
            records=state.records(contents)
            state.check_initial(root,records)
            (root/'settings.json').write_text('{"seed":35}')
            with self.assertRaisesRegex(ValueError,'differs'): state.check_initial(root,records)

    @staticmethod
    def voice_fixture(root):
        (root/'voices').mkdir()
        (root/'settings.json').write_bytes(b'{"narrator":{"temperature":0.55,"seed":42}}')
        (root/'characters.json').write_text('{"characters":[]}')
        (root/'voices/narrator.wav').write_bytes(b'approved voice')
        (root/'voices/samples.json').write_text('{}')
        (root/'volumes.json').write_text('[]')
        (root/'voices/registry.json').write_text(json.dumps({'Narrator':{
            'id':'fix-123','file':'narrator.wav','text':'Reference text'}}))

    def test_missing_reference_and_external_voice_path_are_refused(self):
        with TemporaryDirectory() as folder:
            root=Path(folder); self.voice_fixture(root)
            registry=root/'voices/registry.json'
            for name in ('../escape.wav','D:/escape.wav','missing.wav'):
                registry.write_text(json.dumps({'Narrator':{'id':'fix-123','file':name,'text':'Reference'}}))
                with self.assertRaises((ValueError,FileNotFoundError)): state.collect(root)

    def test_bootstrap_target_preflight_never_writes_and_refuses_existing_app(self):
        with TemporaryDirectory() as folder:
            root=Path(folder); target=root/'target'; target.mkdir()
            script=root/'bootstrap.ps1'
            script.write_text((ROOT/'installer/bootstrap.ps1').read_text(encoding='utf-8'),encoding='utf-8-sig')
            setup=target/'AudioBookStudio-Setup.exe'; setup.write_bytes(b'installer')
            arguments=['powershell.exe','-NoProfile','-File',str(script),'-Target',str(target),
                       '-InstallerPath',str(setup),'-CheckTarget']
            before={file.name:file.read_bytes() for file in target.iterdir()}
            result=subprocess.run(arguments,capture_output=True)
            self.assertEqual(result.returncode,0,result.stdout)
            self.assertEqual(before,{file.name:file.read_bytes() for file in target.iterdir()})
            (target/'settings.json').write_bytes(b'my settings')
            result=subprocess.run(arguments,capture_output=True)
            self.assertNotEqual(result.returncode,0)
            self.assertEqual((target/'settings.json').read_bytes(),b'my settings')
            self.assertFalse((target/'.studio-install-incomplete').exists())
            self.assertFalse((target/'install.log').exists())

    def test_bootstrap_accepts_only_plain_model_set_names(self):
        with TemporaryDirectory() as folder:
            root=Path(folder); script=root/'bootstrap.ps1'; target=root/'target'; target.mkdir()
            script.write_text((ROOT/'installer/bootstrap.ps1').read_text(encoding='utf-8'),encoding='utf-8-sig')
            arguments=['powershell.exe','-NoProfile','-File',str(script),'-Target',str(target),'-CheckTarget','-Profile']
            self.assertEqual(subprocess.run(arguments+['compact'],capture_output=True).returncode,0)
            for name in ('compact --target C:\\','Compact','compact;dir'):
                self.assertNotEqual(subprocess.run(arguments+[name],capture_output=True).returncode,0,name)
            self.assertEqual(list(target.iterdir()),[])

    def test_bootstrap_refuses_wrong_folder_and_invalid_marker(self):
        with TemporaryDirectory() as folder:
            root=Path(folder); script=root/'bootstrap.ps1'; target=root/'target'; target.mkdir()
            script.write_text((ROOT/'installer/bootstrap.ps1').read_text(encoding='utf-8'),encoding='utf-8-sig')
            arguments=['powershell.exe','-NoProfile','-File',str(script),'-Target',str(target),'-CheckTarget']
            result=subprocess.run(arguments+['-InstallerPath',str(root/'outside.exe')],capture_output=True)
            self.assertNotEqual(result.returncode,0)
            (target/'.studio-install-incomplete').write_text('wrong owner')
            result=subprocess.run(arguments,capture_output=True)
            self.assertNotEqual(result.returncode,0)

    def test_pinned_model_metadata_has_complete_hashes(self):
        manifest=json.loads((ROOT/'manifest.json').read_text())
        self.assertEqual(len(manifest['models']),6)
        for item in [manifest['python'],manifest['ffmpeg'],manifest['ollama'],*manifest['models']]:
            self.assertEqual(len(item['sha256']),64)
            self.assertTrue(item['url'].startswith('https://'))
        for tag,gemma in manifest['gemma_models'].items():
            # The stored Ollama manifest is exactly the pinned one, and lists exactly the pinned blobs.
            content=bytes.fromhex(gemma['content_hex'])
            self.assertEqual(hashlib.sha256(content).hexdigest(),gemma['sha256'],tag)
            layers=json.loads(content)
            self.assertEqual([layer['digest'] for layer in [layers['config'],*layers['layers']]],
                             [blob['digest'] for blob in gemma['blobs']],tag)

    def test_every_model_set_resolves_to_pinned_files_only(self):
        manifest=json.loads((ROOT/'manifest.json').read_text())
        self.assertEqual(set(manifest['profiles']),{'standard','compact'})
        self.assertIn(manifest['default_profile'],manifest['profiles'])
        for name,profile in manifest['profiles'].items():
            resolved=core.resolve(manifest,name)
            self.assertEqual(resolved['profile'],name)
            self.assertEqual({item['name'] for item in resolved['models']},
                             {profile[key] for key in core.PROFILE_FILES})
            self.assertEqual(resolved['gemma']['tag'],profile['gemma'])
            self.assertEqual(resolved['gemma']['sha256'],manifest['gemma_models'][profile['gemma']]['sha256'])
            self.assertNotIn('profiles',resolved); self.assertNotIn('gemma_models',resolved)
            self.assertEqual(resolved['model_profile']['base'],manifest['profiles']['standard']['base'])
        compact=core.resolve(manifest,'compact')
        self.assertFalse(any('F32' in item['name'] and 'talker' in item['name'] for item in compact['models']))
        with self.assertRaisesRegex(RuntimeError,'Unknown model set'):
            core.resolve(manifest,'tiny')

    def test_graphics_card_limits_follow_the_model_set(self):
        manifest=json.loads((ROOT/'manifest.json').read_text())
        standard,compact=manifest['profiles']['standard'],manifest['profiles']['compact']
        policy=manifest['hardware']
        core.check_hardware(standard,'RTX 4080',' 8.9','12282','617.42',policy)
        core.check_hardware(compact,'RTX 4060','8.9','8188','617.42',policy)
        with self.assertRaisesRegex(RuntimeError,'Standard model set requires at least 12 GB'):
            core.check_hardware(standard,'RTX 4060','8.9','8188','617.42',policy)
        with self.assertRaisesRegex(RuntimeError,'Compact model set requires at least 8 GB'):
            core.check_hardware(compact,'RTX 4050','8.9','6141','617.42',policy)
        with self.assertRaisesRegex(RuntimeError,'compute capability'):
            core.check_hardware(compact,'GTX 1080','6.1','8192','617.42',policy)

    def test_older_and_newer_rtx_architectures_keep_memory_and_driver_requirements(self):
        manifest=json.loads((ROOT/'manifest.json').read_text())
        policy=manifest['hardware']
        standard,compact=manifest['profiles']['standard'],manifest['profiles']['compact']
        for name,capability,memory in (('RTX 2080 Ti','7.5','11264'),('RTX 3060','8.6','12288'),
                                       ('RTX 4060','8.9','8188'),('RTX 5090','12.0','32768')):
            with self.subTest(name=name):
                core.check_hardware(compact,name,capability,memory,'617.42',policy)
                if int(memory)>=standard['min_vram_mb']:
                    core.check_hardware(standard,name,capability,memory,'617.42',policy)
                else:
                    with self.assertRaisesRegex(RuntimeError,'12 GB'):
                        core.check_hardware(standard,name,capability,memory,'617.42',policy)
                with self.assertRaisesRegex(RuntimeError,'driver'):
                    core.check_hardware(compact,name,capability,memory,'570.64',policy)
        with self.assertRaisesRegex(RuntimeError,'8 GB'):
            core.check_hardware(compact,'RTX 2060','7.5','6144','617.42',policy)
        core.check_hardware(standard,'RTX 3060','8.6','12288',policy['min_driver'],policy)

    def test_dialogue_model_names_cannot_leave_the_models_folder(self):
        self.assertEqual(core.ollama_location('gemma4:e4b-it-qat'),('gemma4','e4b-it-qat'))
        for tag in ('gemma4','gemma4:','../x:1','gemma4:..','a/b:c','gemma4:x\\y'):
            with self.assertRaises(RuntimeError,msg=tag): core.ollama_location(tag)

    def test_log_restores_streams_before_closing(self):
        from argparse import Namespace
        with TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'.studio-install-incomplete').write_text('AudioBookStudio-Installer-1')
            original_out,original_error=sys.stdout,sys.stderr
            with patch.object(core,'install',side_effect=lambda args: print('complete')):
                self.assertEqual(core.main(Namespace(target=root)),0)
            self.assertIs(sys.stdout,original_out)
            self.assertIs(sys.stderr,original_error)
            self.assertIn('complete',(root/'install.log').read_text())

    def test_child_output_is_visible_and_failures_propagate(self):
        output=io.StringIO()
        with redirect_stdout(output):
            core.run([sys.executable,'-c',"print('child visible')"])
        self.assertIn('child visible',output.getvalue())
        with redirect_stdout(io.StringIO()), self.assertRaises(subprocess.CalledProcessError):
            core.run([sys.executable,'-c','raise SystemExit(3)'])


if __name__ == '__main__': unittest.main()
