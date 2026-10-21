"""Validation and glossary checks independent of language-model accuracy."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import glossary
from auto_speakers import context_window, release_model, validate_assignments
from dialogue import NARRATOR, PAUSE, UNASSIGNED


class AttributionTests(unittest.TestCase):
    def test_model_release_uses_ollama_generate_endpoint(self):
        with patch('auto_speakers.request') as request:
            release_model()
        request.assert_called_once_with('/api/generate', {'model': 'gemma4:12b', 'keep_alive': 0}, timeout=60)

    def assignment(self, index, speaker, basis="explicit", gender="unknown"):
        return {"id": index, "speaker": speaker, "gender": gender, "basis": basis, "reason": "Speech tag."}

    def test_repeated_character_is_not_replaced_by_an_alternating_slot(self):
        items = [self.assignment(1, 'Mara'), self.assignment(2, 'Mara', 'context'), self.assignment(3, 'Ben')]
        checked = validate_assignments(items, [1, 2, 3], 'Mara and Ben waited.', [])
        self.assertEqual([item['speaker'] for item in checked], ['Mara', 'Mara', 'Ben'])

    def test_an_invented_name_is_left_unassigned(self):
        result = validate_assignments([self.assignment(1, 'Invented')], [1], 'Mara waited.', [])
        self.assertIsNone(result[0]['speaker'])
        self.assertEqual(result[0]['basis'], 'unclear')

    def test_missing_or_reordered_rows_are_rejected(self):
        with self.assertRaises(ValueError):
            validate_assignments([], [1], '', [])
        with self.assertRaises(ValueError):
            validate_assignments([self.assignment(2, 'Mara')], [1], 'Mara', [])

    def test_unknown_speaker_does_not_receive_a_guessed_identity(self):
        item = self.assignment(1, None, 'unclear')
        self.assertIsNone(validate_assignments([item], [1], 'A voice spoke.', [])[0]['speaker'])

    def test_alias_answer_becomes_the_glossary_name(self):
        result = validate_assignments([self.assignment(1, 'Max')], [1], 'Max waited.', ['Morgan'], {'max': 'Morgan'})
        self.assertEqual(result[0]['speaker'], 'Morgan')

    def test_pronoun_of_the_speech_tag_overrules_a_wrong_gender(self):
        result = validate_assignments([self.assignment(4, 'Alex', 'context')], [4], 'Alex and Riley.',
                                      ['Alex', 'Riley'], genders={'Alex': 'male', 'Riley': 'female'},
                                      hints={4: 'she'})
        self.assertIsNone(result[0]['speaker'])
        self.assertIn('she', result[0]['reason'])

    def test_unnamed_figure_keeps_the_story_description(self):
        result = validate_assignments([self.assignment(1, 'the conductor', 'context')], [1],
                                      'The conductor read the warrant.', [])
        self.assertEqual(result[0]['speaker'], 'The conductor')

    def test_narrator_answer_is_left_unassigned_instead_of_failing(self):
        result = validate_assignments([self.assignment(1, 'Narrator', 'context')], [1], 'x', [])
        self.assertIsNone(result[0]['speaker'])

    def test_context_stops_at_a_scene_break_and_shows_known_speakers(self):
        rows = [[NARRATOR, "Old scene."], [PAUSE, "❦"], [NARRATOR, "New scene."], ["Riley", "— Hi."],
                [UNASSIGNED, "— Hello."]]
        records = context_window(rows, [4])
        self.assertEqual([record["id"] for record in records], [2, 3, 4])
        self.assertEqual(records[1]["speaker"], "Riley")


class GlossaryTests(unittest.TestCase):
    def test_first_format_is_migrated_and_round_trips(self):
        with TemporaryDirectory() as directory:
            file = Path(directory) / 'characters.json'
            file.write_text(json.dumps([['Mara', 'Aiden', 'A warm American voice.', 19]]), encoding='utf-8')
            with patch('glossary.GLOSSARY_FILE', file):
                rows = glossary.load()
                self.assertEqual(rows, [['Mara', '', 'unknown', '', glossary.SAME_AS_NARRATOR, 'Aiden',
                                         'A warm American voice.', 19]])
                rows[0][2], rows[0][1] = 'female', 'Mar, M.'
                glossary.save(rows + [['Character 1', '', '', '', '', 'Ryan', 'x', 1]])
                self.assertEqual(glossary.load(), rows)
                self.assertEqual(json.loads(file.read_text(encoding='utf-8'))['characters'][0]['aliases'],
                                 ['Mar', 'M.'])
                self.assertFalse(file.with_suffix('.tmp').exists())

    def test_new_characters_never_repeat_an_existing_voice(self):
        rows = []
        for name in ('A', 'B', 'C'):
            rows.append(glossary.propose(name, 'female', rows))
        self.assertEqual(glossary.duplicate_voices(rows, 'VoiceDesign'), [])
        self.assertEqual(glossary.duplicate_voices(rows, 'CustomVoice'), [])
        self.assertTrue(all(row[2] == 'female' for row in rows))

    def test_duplicate_voices_are_reported_only_for_characters_that_speak(self):
        rows = [['A', '', 'male', '', '', 'Ryan', 'Same voice.', 1],
                ['B', '', 'male', '', '', 'Ryan', 'Same voice.', 2]]
        self.assertEqual(glossary.duplicate_voices(rows, 'VoiceDesign'), [['A', 'B']])
        self.assertEqual(glossary.duplicate_voices(rows, 'VoiceDesign', {'A'}), [])

    def test_alias_map_and_invalid_gender(self):
        rows = [['Evan Reed', 'Evan, Reed', 'male', '', '', '', 'x', 1]]
        self.assertEqual(glossary.alias_map(rows)['reed'], 'Evan Reed')
        with self.assertRaisesRegex(ValueError, 'gender'):
            glossary.normalize([['X', '', 'm', '', '', '', 'x', 1]])


if __name__ == '__main__':
    unittest.main()
