"""Folder buttons/media in the installed layout, using only an invented temporary project."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import app as studio
import fixed_voices
import glossary
from layout import Layout
import presets
import project


class InstalledPathsTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.home=Path(self.temp.name); layout=Layout(self.home); layout.prepare()
        self.layout=layout
        for module,name,value in [(project,'LAYOUT',layout),(project,'ROOT',layout.user),
            (project,'PROGRAM',layout.program),(project,'WORK',layout.user/'work'),
            (project,'EXPORT',layout.audiobooks),(project,'VOLUMES_FILE',layout.user/'volumes.json'),
            (fixed_voices,'FOLDER',layout.user/'voices'),(presets,'FOLDER',layout.program/'presets')]:
            item=patch.object(module,name,value); item.start(); self.addCleanup(item.stop)

    def test_media_tokens_resolve_only_work_audiobooks_voices_and_public_presets(self):
        for key,folder in project.media_roots().items():
            file=folder/'sample.wav'; file.parent.mkdir(parents=True,exist_ok=True); file.write_bytes(b'sample')
            self.assertEqual(project.media_token(file),key+'/sample.wav')
            self.assertEqual(project.media_path(key+'/sample.wav'),file)
            self.assertEqual(studio.audio(key+'/sample.wav').path,file)
        for unsafe in ('../settings.json','Data/User/settings.json','work/../../settings.json',
                       'C:/private.wav','work\\secret.wav','models/x.gguf'):
            with self.assertRaises(ValueError): project.media_path(unsafe)

    def test_folder_buttons_open_sources_audiobooks_and_work_at_the_new_locations(self):
        source=self.layout.user/'Sources/Example'; source.mkdir(parents=True)
        (source/'001 - The Lamp.txt').write_text('An invented scene.')
        project.write_json(project.VOLUMES_FILE,[{'name':'The Lantern House','source':str(source)}])
        with patch.object(studio.os,'startfile') as open_folder:
            for what,expected in [('source',source),('export',self.layout.audiobooks/'The Lantern House'),
                                  ('chapter',self.layout.user/'work/The Lantern House/001 - The Lamp')]:
                studio.open_folder({'what':what,'volume':'The Lantern House','stem':'001 - The Lamp'})
                self.assertEqual(open_folder.call_args.args[0],expected)
        self.assertEqual(project.backups_folder(),self.layout.backups/'Projects')
        video=self.layout.audiobooks/'The Lantern House/video/001 - The Lamp.mp4'
        video.parent.mkdir(parents=True,exist_ok=True); video.write_bytes(b'synthetic placeholder')
        with patch('subprocess.Popen') as explorer:
            studio.show_video({'volume':'The Lantern House','stem':'001 - The Lamp'})
            self.assertEqual(explorer.call_args.args[0],['explorer.exe','/select,',str(video)])

    def test_long_chapter_paths_are_refused_before_creating_work_or_export(self):
        long=Path('C:/')/('v'*120)/('c'*120+'.txt')
        with self.assertRaisesRegex(ValueError,'too long'):
            project.Chapter('A long volume',long)
        self.assertFalse(project.WORK.exists())
