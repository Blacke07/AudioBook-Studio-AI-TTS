"""Shared voices leave the characters on invented data: no passage changes, backups first, runs once."""
import json
import unittest

import conversion
import fixed_voices
import glossary
import project
import voice_library
import voice_rules
import test_voice_rules as fixtures


def recipe(custom, seed):
    return {'model': 'CustomVoice', 'custom_voice': custom, 'voice_design': '', 'seed': seed}


class VoiceLibraryTests(unittest.TestCase):
    def setUp(self):
        fixtures.VoiceRuleTests.setUp(self)
        # The layout older versions wrote: the shared voice is a character of the shared-voices category.
        self.older = {'version': 2, 'characters': [
            {'name': 'Ada', 'aliases': [], 'gender': 'female', 'note': '', **recipe('Ryan', 10)},
            {'name': 'Morgan', 'aliases': [], 'gender': 'male', 'note': '', **recipe('Aiden', 20)},
            {'name': 'Old man', 'aliases': [], 'gender': 'male', 'note': 'An older man', **recipe('Ryan', 30)},
            {'name': 'The guard', 'aliases': [], 'gender': 'male', 'note': '', **recipe('Aiden', 40), 'read_as': 'Old man'},
            {'name': 'Bram', 'aliases': [], 'gender': 'male', 'note': '', **recipe('Ryan', 50), 'read_as': 'Old man'}],
            'organization': {'categories': [
                {'id': 'uncategorized', 'name': 'Uncategorized', 'description': '', 'voice': 'own'},
                {'id': 'shared-voices', 'name': 'Shared voices', 'description': '', 'voice': 'Narrator'},
                {'id': 'guests', 'name': 'Guests', 'description': '', 'voice': 'Old man'}],
                'characters': {'Old man': {'category': 'shared-voices'}, 'The guard': {'category': 'guests'}}}}
        glossary.GLOSSARY_FILE.write_text(json.dumps(self.older), encoding='utf-8')
        fixed_voices.FOLDER.mkdir(exist_ok=True)
        fixed_voices.REGISTRY.write_text(json.dumps({'Old man': {
            'id': 'fix-0123456789', 'file': 'old-man-0123456789.wav', 'text': 'An approved take of the old man.',
            'seconds': 6.0, 'origin': {}, 'date': '2026-10-29T10:00:00'}}), encoding='utf-8')
        (fixed_voices.FOLDER / 'old-man-0123456789.wav').write_bytes(b'synthetic take')
        settings = project.load_settings()
        project.save_settings({**settings, 'multi_voice': True, 'announce_titles': False,
                               'voice_variation': {'Old man': 0.8}})
        # Bram reads with the old man everywhere, but in this chapter Morgan reads with Bram's own recipe.
        self.script['rows'] = [['Ada', '— Keep the lamp burning,', False, 0], ['The guard', 'Halt.', False, 0],
                               ['Bram', 'Who goes there?', False, 0], ['Morgan', 'A friend.', False, 0]]
        self.script['voice_rules'] = {'characters': {'Morgan': 'Bram'}, 'lines': []}
        self.chapter.save_script(self.script)

    def keys(self):
        return conversion.chapter_plan(self.chapter, project.load_settings())[2]

    def test_the_migration_moves_shared_voices_keeps_every_passage_and_runs_once(self):
        before = self.keys()
        original = glossary.GLOSSARY_FILE.read_bytes()
        backup = voice_library.migrate()
        self.assertEqual((backup / 'characters.json').read_bytes(), original)
        self.assertTrue((backup / 'registry.json').is_file() and (backup / 'settings.json').is_file())
        self.assertEqual(self.keys(), before, 'No passage is generated again')
        data = json.loads(glossary.GLOSSARY_FILE.read_text(encoding='utf-8'))
        self.assertEqual([voice['name'] for voice in data['voices']], ['Old man'])
        self.assertEqual({key: data['voices'][0][key] for key in voice_library.RECIPE}, recipe('Ryan', 30))
        self.assertEqual([entry['name'] for entry in data['characters']], ['Ada', 'Morgan', 'The guard', 'Bram'])
        self.assertNotIn('shared-voices', [cat['id'] for cat in data['organization']['categories']])
        self.assertNotIn('Old man', data['organization']['characters'])
        people = {entry['name']: entry for entry in data['characters']}
        self.assertNotIn('custom_voice', people['The guard'], 'Nobody reads with the guard\'s recipe')
        self.assertEqual(people['Bram']['custom_voice'], 'Ryan', 'A chapter rule still reads with Bram\'s recipe')
        self.assertEqual(voice_rules.global_rules()['The guard'], 'Old man')
        self.assertEqual(fixed_voices.get('Old man')['id'], 'fix-0123456789')
        self.assertEqual(project.load_settings()['voice_variation'], {'Old man': 0.8})
        written = glossary.GLOSSARY_FILE.read_bytes()
        self.assertIsNone(voice_library.migrate(), 'The migration runs once')
        self.assertEqual(glossary.GLOSSARY_FILE.read_bytes(), written)

    def test_an_older_package_document_is_converted_the_same_way(self):
        newer = voice_library.separate(self.older)
        self.assertEqual([voice['name'] for voice in newer['voices']], ['Old man'])
        self.assertEqual(self.older['characters'][2]['name'], 'Old man', 'The package data itself is not changed')
        self.assertIs(voice_library.separate(newer), newer, 'A newer document is left as it is')

    def test_a_voice_is_never_a_speaker_and_a_rule_can_point_to_it(self):
        voice_library.migrate()
        rows = glossary.load()
        self.assertNotIn('Old man', [row[0] for row in rows])
        self.assertIn('Old man', glossary.voice_names(rows))
        request = {'scope': 'everywhere', 'speaker': 'Ada', 'read_as': 'Old man'}
        _, report = voice_rules.plan(request)
        voice_rules.apply(request, report['plan_id'])
        chunks, voices, _ = conversion.chapter_plan(self.chapter, project.load_settings())
        self.assertEqual(chunks[0].voice_role, 'Old man')
        self.assertEqual(voices['Old man'].speaker, 'fix-0123456789')
        with self.assertRaisesRegex(ValueError, 'existing character'):
            voice_rules.plan({'scope': 'everywhere', 'speaker': 'Old man', 'read_as': 'Ada'})


if __name__ == '__main__':
    unittest.main()
