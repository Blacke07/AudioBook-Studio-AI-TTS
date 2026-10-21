"""Uninstaller safety on fake installations in temporary folders. Never touches a real installation."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
CSC = Path(r'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe')
NAME = 'Uninstall AudioBook Studio.exe'

APP = ['app.py', 'web/index.html', 'engine/build/tts-server.exe', 'assets/voice_mean.npy', 'licenses/ggml-MIT.txt',
       'AudioBook Studio.exe', NAME]
OWNED = ['runtime/python/python.exe', '.venv/Scripts/python.exe', 'tools/ffmpeg/ffmpeg.exe', 'tools/ollama/ollama.exe',
         'licenses/ffmpeg/LICENSE.txt', '.downloads/cache.zip', 'install.log', 'startup.log', '__pycache__/app.cpython-312.pyc']
MODELS = ['models/model.gguf', 'models/ollama/blobs/sha256-abc', 'models/ollama/manifests/registry.ollama.ai/library/gemma4/12b']
DATA = ['settings.json', 'characters.json', 'volumes.json', 'voices/registry.json', 'voices/narrator.wav',
        'work/passages/a.wav', 'export/Book/1.mp3']
FOREIGN = ['AudioBookStudio-Setup-1.0.0.exe', 'Local Models/_place models here', 'my notes.txt']


def make_installation(root, foreign=True, payload_paths=None):
    manifest = {'version': '1.0.0', 'payload_files': [{'path': p, 'sha256': '0' * 64} for p in (payload_paths or APP)],
                'initial_state_files': [{'path': p, 'sha256': '0' * 64} for p in DATA[:5]],
                'models': [{'name': 'model.gguf', 'size': 1, 'sha256': '0' * 64}],
                'gemma': {'blobs': [{'digest': 'sha256:abc', 'size': 1}], 'sha256': '0' * 64}}
    for relative in APP + OWNED + MODELS + DATA + (FOREIGN if foreign else []):
        file = root / relative
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(b'x' * 10)
    (root / 'installation-manifest.json').write_text(json.dumps(manifest), encoding='utf-8')


class UninstallerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='AudioBook uninstall ')
        cls.folder = Path(cls.temp.name)
        cls.exe = cls.folder / NAME
        subprocess.run([str(CSC), '/nologo', '/target:winexe', '/platform:x64', '/codepage:65001',
                        '/reference:System.Windows.Forms.dll', '/reference:System.Web.Extensions.dll',
                        '/out:' + str(cls.exe), str(ROOT / 'installer/Uninstall.cs')], check=True, capture_output=True)
        cls.setup = cls.folder / 'Setup.exe'
        subprocess.run([str(CSC), '/nologo', '/target:winexe', '/platform:x64', '/codepage:65001',
                        '/reference:System.Windows.Forms.dll', '/reference:System.Drawing.dll',
                        '/reference:System.Web.Extensions.dll', '/out:' + str(cls.setup), str(ROOT / 'installer/Setup.cs')],
                       check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def setUp(self):
        self.work = tempfile.TemporaryDirectory(prefix='AudioBook fake install ')
        self.addCleanup(self.work.cleanup)
        self.root = Path(self.work.name) / 'AudioBook Studio'
        self.report = Path(self.work.name) / 'report.json'

    def run_uninstaller(self, *flags, exe=None):
        result = subprocess.run([str(exe or self.exe), '--target', str(self.root), '--yes', '--report', str(self.report),
                                 *flags], timeout=120)
        return result.returncode, json.loads(self.report.read_text(encoding='utf-8'))

    def assertExist(self, paths, exist=True):
        for relative in paths:
            self.assertEqual((self.root / relative).exists(), exist, relative)

    def test_removes_application_and_keeps_user_data_and_foreign_files(self):
        make_installation(self.root)
        code, report = self.run_uninstaller()
        self.assertEqual(code, 0, report)
        self.assertExist(APP + OWNED + MODELS + ['installation-manifest.json'], False)
        self.assertExist(DATA + FOREIGN)
        for folder in ('runtime', '.venv', 'tools', 'models', 'engine', 'web', 'licenses', '__pycache__'):
            self.assertFalse((self.root / folder).exists(), folder)
        self.assertFalse(report['deleted_data'])

    def test_deletes_user_data_only_on_request_and_never_foreign_files(self):
        make_installation(self.root)
        code, report = self.run_uninstaller('--delete-data')
        self.assertEqual(code, 0, report)
        self.assertExist(DATA, False)
        self.assertExist(FOREIGN)
        self.assertTrue(self.root.is_dir())

    def test_removes_the_folder_when_nothing_else_remains(self):
        make_installation(self.root, foreign=False)
        code, report = self.run_uninstaller('--delete-data')
        self.assertEqual(code, 0, report)
        self.assertFalse(self.root.exists())

    def test_folder_without_installation_manifest_is_refused(self):
        self.root.mkdir(parents=True)
        (self.root / 'settings.json').write_text('{}')
        (self.root / 'app.py').write_text('print(1)')
        code, report = self.run_uninstaller('--delete-data')
        self.assertEqual(code, 1)
        self.assertIn('not an AudioBook Studio installation', report['error'])
        self.assertExist(['settings.json', 'app.py'])

    def test_manifest_path_outside_the_installation_is_refused_before_any_removal(self):
        outside = Path(self.work.name) / 'outside.txt'
        outside.write_text('keep me')
        make_installation(self.root, payload_paths=APP + ['../outside.txt'])
        code, report = self.run_uninstaller()
        self.assertEqual(code, 1)
        self.assertEqual(outside.read_text(), 'keep me')
        self.assertExist(APP + OWNED + MODELS + DATA)

    def test_links_are_removed_without_touching_their_targets(self):
        make_installation(self.root)
        target = Path(self.work.name) / 'linked target'
        target.mkdir()
        (target / 'precious.txt').write_text('keep me')
        subprocess.run(['cmd', '/c', 'mklink', '/J', str(self.root / '.venv/Lib'), str(target)], check=True,
                       capture_output=True)
        code, report = self.run_uninstaller()
        self.assertEqual(code, 0, report)
        self.assertEqual((target / 'precious.txt').read_text(), 'keep me')
        self.assertFalse((self.root / '.venv').exists())

    def test_running_program_from_the_folder_blocks_uninstall_without_stopping_it(self):
        make_installation(self.root)
        sleeper = self.root / '.venv/Scripts/python.exe'
        source = Path(self.work.name) / 'Sleeper.cs'
        source.write_text('class S { static void Main() { System.Threading.Thread.Sleep(60000); } }')
        subprocess.run([str(CSC), '/nologo', '/out:' + str(sleeper), str(source)], check=True, capture_output=True)
        process = subprocess.Popen([str(sleeper)], creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            time.sleep(0.5)
            code, report = self.run_uninstaller('--delete-data')
            self.assertEqual(code, 2)
            self.assertIn('python.exe', report['error'])
            self.assertIsNone(process.poll())
            self.assertExist(APP + MODELS + DATA)
        finally:
            process.kill()
            process.wait()

    def test_removes_only_shortcuts_that_still_open_this_installation(self):
        make_installation(self.root)
        other = Path(self.work.name) / 'Other App'
        other.mkdir()
        desktop, programs = Path(self.work.name) / 'Desktop', Path(self.work.name) / 'Programs'
        subprocess.run([str(self.setup), '--create-shortcuts', str(other), str(desktop), ''], check=True, timeout=60)
        subprocess.run([str(self.setup), '--create-shortcuts', str(self.root), str(desktop), str(programs)], check=True, timeout=60)
        foreign = desktop / 'AudioBook Studio.lnk'                       # another installation's shortcut
        mine = [desktop / 'AudioBook Studio (AudioBook Studio).lnk', programs / 'AudioBook Studio.lnk']
        self.assertTrue(foreign.exists() and all(link.exists() for link in mine))
        with (self.root / 'shortcuts.txt').open('a', encoding='utf-8') as listed:
            listed.write(str(foreign) + '\n')                             # listed, but it does not open this installation
        code, report = self.run_uninstaller()
        self.assertEqual(code, 0, report)
        self.assertFalse(any(link.exists() for link in mine))
        self.assertTrue(foreign.exists())
        self.assertFalse((self.root / 'shortcuts.txt').exists())

    def test_removes_the_dialogue_model_of_a_compact_installation(self):
        make_installation(self.root)
        manifest_file = self.root / 'installation-manifest.json'
        manifest = json.loads(manifest_file.read_text(encoding='utf-8'))
        manifest['gemma']['tag'] = 'gemma4:e4b-it-qat'
        manifest['profile'] = 'compact'
        manifest_file.write_text(json.dumps(manifest), encoding='utf-8')
        library = self.root / 'models/ollama/manifests/registry.ollama.ai/library/gemma4'
        (library / '12b').rename(library / 'e4b-it-qat')   # a Compact installation has only its own model
        compact = library / 'e4b-it-qat'
        code, report = self.run_uninstaller()
        self.assertEqual(code, 0, report)
        self.assertFalse(compact.exists())
        self.assertFalse((self.root / 'models').exists())
        self.assertExist(DATA + FOREIGN)

    def test_dry_run_lists_without_removing(self):
        make_installation(self.root)
        code, report = self.run_uninstaller('--dry-run')
        self.assertEqual(code, 0, report)
        self.assertIn('runtime', report['planned'])
        self.assertIn('models\\model.gguf', report['planned'])
        self.assertExist(APP + OWNED + MODELS + DATA)

    def test_runs_from_a_temporary_copy_and_removes_its_own_exe(self):
        make_installation(self.root)
        inside = self.root / NAME
        inside.write_bytes(self.exe.read_bytes())
        result = subprocess.run([str(inside), '--yes', '--report', str(self.report)], timeout=60)
        self.assertEqual(result.returncode, 0)
        deadline = time.monotonic() + 60
        while not self.report.exists() and time.monotonic() < deadline:
            time.sleep(0.2)
        report = json.loads(self.report.read_text(encoding='utf-8'))
        self.assertEqual(report['code'], 0, report)
        self.assertFalse(inside.exists())
        self.assertExist(DATA + FOREIGN)
        copy = Path(report['temporary_copy'])
        self.assertTrue(copy.name.startswith('AudioBookStudio-Uninstall-'))
        deadline = time.monotonic() + 20
        while copy.exists() and time.monotonic() < deadline:
            time.sleep(0.2)
        self.assertFalse(copy.exists())


if __name__ == '__main__':
    unittest.main()
