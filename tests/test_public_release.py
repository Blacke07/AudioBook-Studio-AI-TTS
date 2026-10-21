"""Fail closed when release preparation accidentally introduces personal data or unapproved media."""
import json
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import audit_public


class PublicSourceFilesTests(unittest.TestCase):
    def test_internal_maintainer_documents_are_not_packaged(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            for name in audit_public.FILES:
                (root / name).write_text('public source', encoding='utf-8')
            excluded = ('AGENTS.md', 'HANDOFF.md', 'app/CLAUDE.txt', 'app/.codex/instructions.json',
                        'app/author-notes.md', 'docs/RELEASE.md', 'docs/Predare.docx')
            for name in excluded:
                file = root / name
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_text('internal maintainer notes', encoding='utf-8')
            names = {file.relative_to(root).as_posix() for file in audit_public.source_files(root)}
            self.assertEqual(names, set(audit_public.FILES))
            self.assertTrue(names.isdisjoint(excluded))

    def test_product_guides_and_build_instructions_remain_public(self):
        for name in audit_public.PUBLIC_MARKDOWN:
            with self.subTest(name=name):
                self.assertTrue(audit_public.public_file(name))
        self.assertTrue(audit_public.public_file('docs/screenshots/volume.png'))
        self.assertTrue(audit_public.public_file('app/auto_speakers.py'))
        self.assertFalse(audit_public.public_file('docs/personal-recording.wav'))


class PublicReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        demo = json.loads((ROOT / 'demo-provenance.json').read_text())
        names = ['demo-provenance.json', 'app/settings.json', 'app/characters.json', 'app/volumes.json',
                 'app/voices/registry.json', 'app/voices/' + demo['narrator']['file'], 'app/assets/voice_mean.npy',
                 'app/presets/presets.json'] + ['app/presets/' + preset['file'] for preset in demo.get('presets', [])]
        for name in names:
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
        sources = patch.object(audit_public, 'source_files', return_value=[])
        sources.start()
        self.addCleanup(sources.stop)

    def test_fresh_synthetic_demo_passes(self):
        audit_public.audit(self.root, native=False)

    def test_nonempty_cast_and_volume_list_cannot_ship(self):
        for name, value, message in (
            ('app/characters.json', {'characters': [{'name': 'Private character'}]}, 'empty cast'),
            ('app/volumes.json', [{'source': 'C:/Books'}], 'no volume paths'),
        ):
            file = self.root / name
            original = file.read_bytes()
            file.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError, message):
                audit_public.audit(self.root, native=False)
            file.write_bytes(original)

    def test_unapproved_reference_wav_cannot_ship(self):
        file = self.root / 'app/voices/unapproved.wav'
        file.write_bytes(b'not a distributed demo')
        with patch.object(audit_public, 'source_files', return_value=[file]):
            with self.assertRaisesRegex(ValueError, 'Unexpected binary'):
                audit_public.audit(self.root, native=False)

    def test_changed_or_unlisted_preset_cannot_ship(self):
        demo = json.loads((self.root / 'demo-provenance.json').read_text())
        self.assertTrue(demo['presets'])
        first = self.root / 'app/presets' / demo['presets'][0]['file']
        original = first.read_bytes()
        first.write_bytes(original + b'changed')
        with self.assertRaisesRegex(ValueError, 'Synthetic public asset changed'):
            audit_public.audit(self.root, native=False)
        first.write_bytes(original)
        catalog = self.root / 'app/presets/presets.json'
        items = json.loads(catalog.read_text(encoding='utf-8'))
        catalog.write_text(json.dumps(items[1:]), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Voice presets differ'):
            audit_public.audit(self.root, native=False)

    def test_changed_calibration_fails_before_packaging(self):
        (self.root / 'app/assets/voice_mean.npy').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'Synthetic public asset changed'):
            audit_public.audit(self.root, native=False)

    def test_personal_home_path_is_detected_in_text_and_native_strings(self):
        for encoding in ('utf-8', 'utf-16-le'):
            with self.assertRaisesRegex(ValueError, 'Personal path'):
                audit_public.check_content('fixture', str(Path.home()).encode(encoding))
