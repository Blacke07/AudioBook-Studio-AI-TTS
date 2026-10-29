"""Explicit own recipes on invented identities; no inference, installation or personal data."""
import copy
import json
import unittest

import character_registry
import conversion
import fixed_voices
import glossary
import project
import project_transfer
import test_voice_rules as fixtures
import voice_library
import voice_rules


class OwnVoiceTests(unittest.TestCase):
    def setUp(self):
        fixtures.VoiceRuleTests.setUp(self)
        data = json.loads(glossary.GLOSSARY_FILE.read_text(encoding='utf-8'))
        data['voices'] = [{'name': 'Shared guide', 'gender': 'unknown', 'note': 'Invented shared voice.',
                           'model': 'CustomVoice', 'custom_voice': 'Ryan', 'voice_design': '', 'seed': 30}]
        data['characters'].append({'name': 'The visitor', 'aliases': ['Visitor'], 'gender': 'unknown',
                                   'note': 'An invented visitor.', 'read_as': 'Shared guide'})
        glossary.GLOSSARY_FILE.write_text(json.dumps(data), encoding='utf-8')
        project.save_settings({**project.load_settings(), 'multi_voice': True, 'announce_titles': False})
        self.script['rows'][0][0] = self.script['rows'][2][0] = 'The visitor'
        self.chapter.save_script(self.script)

    def request(self):
        return dict(role='The visitor', revision=character_registry.snapshot()['revision'],
                    model='VoiceDesign', design='A clear, natural adult voice with an American accent.',
                    custom='', seed=0)

    def altered(self, **changes):
        request = self.request(); request.update(changes); return request

    def document(self):
        return json.loads(glossary.GLOSSARY_FILE.read_text(encoding='utf-8'))

    def test_creation_changes_only_the_requested_recipe_and_keeps_passage_keys(self):
        before = self.document()
        keys = conversion.chapter_plan(self.chapter, project.load_settings())[2]
        settings = project.SETTINGS_FILE.read_bytes()
        script = self.chapter.script_file.read_bytes()
        result = voice_library.create_own_voice(self.request())
        after = self.document()
        expected = copy.deepcopy(before)
        expected['characters'][-1].update(model='VoiceDesign', custom_voice='',
                                          voice_design=self.request()['design'], seed=0)
        self.assertEqual(after, expected)
        self.assertEqual(result['read_as'], 'Shared guide')
        self.assertEqual(conversion.chapter_plan(self.chapter, project.load_settings())[2], keys)
        self.assertEqual(project.SETTINGS_FILE.read_bytes(), settings)
        self.assertEqual(self.chapter.script_file.read_bytes(), script)
        self.assertEqual(fixed_voices.load(), {})
        self.assertIn('The visitor', glossary.voice_names(glossary.load()))

    def test_a_narrator_reading_rule_is_preserved(self):
        data = self.document(); data['characters'][-1]['read_as'] = 'Narrator'
        glossary.GLOSSARY_FILE.write_text(json.dumps(data), encoding='utf-8')
        before = conversion.chapter_plan(self.chapter, project.load_settings())[2]
        voice_library.create_own_voice(self.request())
        self.assertEqual(voice_rules.global_rules()['The visitor'], 'Narrator')
        self.assertEqual(conversion.chapter_plan(self.chapter, project.load_settings())[2], before)

    def test_category_inheritance_and_metadata_are_preserved(self):
        data = character_registry.snapshot()['document']; entry = data['characters'][-1]; entry.pop('read_as')
        data['organization']['categories'][0]['voice'] = 'Shared guide'
        glossary.GLOSSARY_FILE.write_text(json.dumps(data), encoding='utf-8')
        voice_library.create_own_voice(self.request())
        after = self.document()
        self.assertNotIn('read_as', after['characters'][-1])
        self.assertEqual(after['organization'], data['organization'])
        self.assertEqual(voice_rules.global_rules()['The visitor'], 'Shared guide')

    def test_custom_voice_is_canonical_and_drops_unused_design(self):
        voice_library.create_own_voice(self.altered(model='CustomVoice', custom='aiden', design='Unused.', seed=71))
        entry = self.document()['characters'][-1]
        self.assertEqual((entry['custom_voice'], entry['voice_design'], entry['seed']), ('Aiden', '', 71))

    def test_existing_own_recipe_is_not_replaced(self):
        before = project_transfer.state_hash()
        with self.assertRaisesRegex(ValueError, 'already has an own voice'):
            voice_library.create_own_voice(self.altered(role='Ada'))
        self.assertEqual(project_transfer.state_hash(), before)

    def test_an_approved_reference_without_a_recipe_is_not_overwritten(self):
        project.write_json(fixed_voices.REGISTRY, {'The visitor': {
            'id':'fix-0123456789', 'file':'visitor.wav', 'text':'A complete invented reference sentence.',
            'seconds':5.0, 'origin':{}, 'date':'2026-10-29T10:00:00'}})
        (fixed_voices.FOLDER / 'visitor.wav').write_bytes(b'synthetic reference bytes')
        before = project_transfer.state_hash()
        with self.assertRaisesRegex(ValueError, 'already has an own voice'):
            voice_library.create_own_voice(self.request())
        self.assertEqual(project_transfer.state_hash(), before)

    def test_unknown_shared_or_reserved_role_cannot_become_a_new_identity(self):
        before = project_transfer.state_hash()
        for name in ('Missing', 'Shared guide', 'Narrator'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                voice_library.create_own_voice(self.altered(role=name))
        self.assertEqual(project_transfer.state_hash(), before)

    def test_stale_revision_makes_no_writes(self):
        before = project_transfer.state_hash()
        with self.assertRaisesRegex(ValueError, 'Characters changed'):
            voice_library.create_own_voice(self.altered(revision='stale'))
        self.assertEqual(project_transfer.state_hash(), before)

    def test_invalid_recipe_seed_and_extra_fields_make_no_writes(self):
        before = project_transfer.state_hash()
        for changes in ({'model':'Invalid'}, {'model':[]}, {'seed':True}, {'seed':-1}, {'seed':1.2},
                        {'seed':2147483648}, {'design':''}, {'design':[]},
                        {'model':'CustomVoice','custom':'Missing'}, {'extra':True}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                voice_library.create_own_voice(self.altered(**changes))
        self.assertEqual(project_transfer.state_hash(), before)

    def test_repeated_creation_is_explicitly_refused(self):
        voice_library.create_own_voice(self.request())
        before = project_transfer.state_hash()
        with self.assertRaisesRegex(ValueError, 'already has an own voice'):
            voice_library.create_own_voice(self.request())
        self.assertEqual(project_transfer.state_hash(), before)

    def test_only_an_explicit_reading_rule_switch_uses_the_new_recipe(self):
        voice_library.create_own_voice(self.request())
        request = {'scope':'everywhere','speaker':'The visitor','read_as':'The visitor'}
        _, preview = voice_rules.plan(request)
        voice_rules.apply(request, preview['plan_id'])
        chunks, voices, _ = conversion.chapter_plan(self.chapter, project.load_settings())
        self.assertEqual(chunks[0].voice_role, 'The visitor')
        self.assertIn('adult voice', voices['The visitor'].description)


if __name__ == '__main__':
    unittest.main()
