"""The Local Models folder setup prepares: instruction file, no overwrites, and no manual import until models exist."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CSC = Path(r'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe')
GUIDE = '_place models here'


class LocalModelsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='AudioBook setup ')
        cls.setup = Path(cls.temp.name) / 'Setup.exe'
        subprocess.run([str(CSC), '/nologo', '/target:winexe', '/platform:x64', '/codepage:65001',
                        '/reference:System.Windows.Forms.dll', '/reference:System.Drawing.dll',
                        '/reference:System.Web.Extensions.dll', '/resource:' + str(ROOT / 'manifest.json') + ',manifest.json',
                        '/out:' + str(cls.setup), str(ROOT / 'installer/Setup.cs'),
                        str(ROOT / 'installer/DesktopRuntime.cs')], check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def setUp(self):
        work = tempfile.TemporaryDirectory(prefix='AudioBook target ')
        self.addCleanup(work.cleanup)
        self.target = Path(work.name) / 'AudioBook Studio'
        self.target.mkdir()

    def prepare(self, *profile):
        subprocess.run([str(self.setup), '--prepare-local-models', str(self.target), *profile], check=True, timeout=60)
        return self.target / 'Local Models'

    def assertListsModelSet(self, text, name):
        manifest = json.loads((ROOT / 'manifest.json').read_text(encoding='utf-8'))
        profile = manifest['profiles'][name]
        wanted = {profile[key] for key in ('voice_design', 'custom_voice', 'base', 'codec')}
        self.assertIn('Model set: ' + profile['label'], text)
        for item in manifest['models']:
            self.assertEqual(item['name'] in text, item['name'] in wanted, item['name'])
            self.assertEqual(item['sha256'] in text, item['name'] in wanted, item['name'])
        chosen = manifest['gemma_models'][profile['gemma']]['blobs']
        for gemma in manifest['gemma_models'].values():
            for blob in gemma['blobs']:
                listed = 'ollama\\blobs\\' + blob['digest'].replace(':', '-') in text
                self.assertEqual(listed, blob in chosen, blob['digest'])

    def model_source(self):
        script = Path(self.target.parent) / 'bootstrap.ps1'
        script.write_text((ROOT / 'installer/bootstrap.ps1').read_text(encoding='utf-8'), encoding='utf-8-sig')
        before = sorted(str(path) for path in self.target.rglob('*'))
        result = subprocess.run(['powershell.exe', '-NoProfile', '-File', str(script), '-Target', str(self.target),
                                 '-AcceptLicenses', '-CheckModels'], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(before, sorted(str(path) for path in self.target.rglob('*')))  # detection writes nothing
        return result.stdout.strip().splitlines()[-1]

    def test_prepared_folder_lists_every_pinned_file_without_extension(self):
        models = self.prepare()
        guide = models / GUIDE
        self.assertTrue(guide.is_file())
        self.assertEqual(guide.suffix, '')
        self.assertTrue((models / 'ollama/blobs').is_dir())
        self.assertListsModelSet(guide.read_text(encoding='utf-8'), 'standard')

    def test_compact_list_names_only_the_compact_files(self):
        models = self.prepare('compact')
        self.assertListsModelSet((models / GUIDE).read_text(encoding='utf-8'), 'compact')

    def test_switching_model_set_updates_only_the_list_setup_wrote(self):
        models = self.prepare('standard')
        self.prepare('compact')
        self.assertListsModelSet((models / GUIDE).read_text(encoding='utf-8'), 'compact')
        (models / GUIDE).write_text('my own notes', encoding='utf-8')
        self.prepare('standard')
        self.assertEqual((models / GUIDE).read_text(encoding='utf-8'), 'my own notes')

    def test_unknown_model_set_is_refused_without_writing(self):
        result = subprocess.run([str(self.setup), '--prepare-local-models', str(self.target), 'tiny'], timeout=60)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(list(self.target.iterdir()), [])

    def test_preparing_again_never_overwrites_user_files(self):
        models = self.prepare()
        (models / GUIDE).write_text('my own notes', encoding='utf-8')
        (models / 'qwen-talker-1.7b-base-Q8_0.gguf').write_bytes(b'model')
        self.prepare()
        self.assertEqual((models / GUIDE).read_text(encoding='utf-8'), 'my own notes')
        self.assertEqual((models / 'qwen-talker-1.7b-base-Q8_0.gguf').read_bytes(), b'model')

    def test_folder_with_only_the_instructions_downloads_automatically(self):
        self.assertEqual(self.model_source(), 'Model source: download')
        self.prepare()
        self.assertEqual(self.model_source(), 'Model source: download')

    def test_any_supplied_model_file_switches_to_verified_manual_import(self):
        models = self.prepare()
        (models / 'ollama/blobs/sha256-abc').write_bytes(b'blob')
        self.assertEqual(self.model_source(), 'Model source: manual')


if __name__ == '__main__':
    unittest.main()
