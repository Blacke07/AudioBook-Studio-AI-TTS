"""Regression checks for speaker identity, preservation and pause planning."""
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np

import engine_client
import fixed_voices
from conversion import Chunk, generation_order, plan_chunks, trim_edges
from dialogue import (JOINED_PAUSE, NARRATOR, SCENE_PAUSE, UNASSIGNED, Line, Voice, drop_simple_tags,
                      prepare_script, read_cast, read_script)
from voices import CUSTOM_VOICE, VOICE_DESIGN


def words(text):
    return " ".join(text.split())


class DialogueTests(unittest.TestCase):
    def setUp(self):
        self.voice = Voice("Ryan", "An American male voice.", "Read naturally.", 42, VOICE_DESIGN)
        # Never read the author's real fixed voices.
        isolation = patch.object(fixed_voices, "REGISTRY", Path(__file__).with_name("_missing_registry.json"))
        isolation.start()
        self.addCleanup(isolation.stop)

    def test_consecutive_dialogue_is_never_flattened_into_one_request(self):
        text = '— Come in.\n— No, thank you.\n— Why not?'
        lines = read_script(text, False, None, "")
        chunks = plan_chunks(lines, {NARRATOR: self.voice}, 0.55)
        self.assertEqual([chunk.text for chunk in chunks], text.splitlines())
        self.assertEqual([chunk.pause_after for chunk in chunks], [0.55, 0.55, 0])

    def test_three_speakers_and_repeated_speaker_keep_explicit_cast(self):
        text = '— One.\n— Two.\n— Three.\n— Again.'
        roles = ["A", "B", "C", "B"]
        rows = [[role, line] for role, line in zip(roles, text.splitlines())]
        lines = read_script(text, True, rows, text)
        chunks = plan_chunks(lines, {role: self.voice for role in roles}, 0.5)
        self.assertEqual([chunk.role for chunk in chunks], roles)
        self.assertEqual(" ".join(chunk.text for chunk in chunks), " ".join(text.splitlines()))

    def test_unassigned_and_unknown_speakers_fail_before_generation(self):
        text = '— Who is there?'
        with self.assertRaisesRegex(ValueError, 'Assign'):
            read_script(text, True, prepare_script(text), text)
        with self.assertRaisesRegex(ValueError, 'has no voice'):
            plan_chunks([Line("Unknown", text, True)], {NARRATOR: self.voice}, 0.5)

    def test_changed_source_invalidates_assignments(self):
        with self.assertRaisesRegex(ValueError, 'latest text change'):
            read_script("Changed.", True, [[NARRATOR, "Earlier."]], "Earlier.")

    def test_preparation_preserves_prose_and_dialogue_words(self):
        text = ('He stopped.\nHe listened.\n\n— Stay here, she said. Not a word.\n— I will.\n\n'
                'Casey looked up. "For the guest," she said. "It\'s cold."\n\nHe nodded.')
        self.assertEqual(words(text), " ".join(words(row[1]) for row in prepare_script(text)))

    def test_dash_speech_tag_goes_to_narrator_and_names_the_speaker(self):
        rows = prepare_script("— It is green, Morgan said. Not a warning.", aliases={"morgan": "Morgan"})
        self.assertEqual(rows, [["Morgan", "— It is green,", False], [NARRATOR, "Morgan said.", True],
                                ["Morgan", "Not a warning.", True]])

    def test_alias_in_tag_resolves_to_glossary_name(self):
        rows = prepare_script("— Four, Max said.", aliases={"max": "Morgan"})
        self.assertEqual(rows[0][0], "Morgan")

    def test_pronoun_tag_is_split_but_left_for_attribution(self):
        rows = prepare_script("— The visitor gets the chair, he said. I'm not moving furniture today.")
        self.assertEqual([row[0] for row in rows], [UNASSIGNED, NARRATOR, UNASSIGNED])

    def lines_of(self, text):
        rows = prepare_script(text, aliases={"morgan": "Morgan", "riley": "Riley"})
        rows = [["Alex" if row[0] == UNASSIGNED else row[0], *row[1:]] for row in rows]
        return read_script(text, True, rows, text)

    def test_plain_tag_of_a_fixed_voice_is_dropped_and_speech_joined(self):
        lines, dropped = drop_simple_tags(self.lines_of("— It is green, Morgan said. Not a warning."), {"Morgan"})
        self.assertEqual([(line.role, line.text) for line in lines], [("Morgan", "— It is green. Not a warning.")])
        self.assertEqual(dropped, {1})

    def test_tag_at_the_end_is_dropped_and_informative_tags_stay(self):
        lines, _ = drop_simple_tags(self.lines_of("— Then both tickets are valid, Riley said."), {"Riley"})
        self.assertEqual([line.text for line in lines], ["— Then both tickets are valid,"])
        for text in ("— Confirmed, he said eventually. By the manager.", "— Saves time, Morgan said from the platform."):
            lines, dropped = drop_simple_tags(self.lines_of(text), {"Morgan", "Alex"})
            self.assertEqual(dropped, set(), text)

    def test_tags_of_unfixed_voices_are_kept(self):
        lines, dropped = drop_simple_tags(self.lines_of("— It is green, Morgan said. Not a warning."), set())
        self.assertEqual((len(lines), dropped), (3, set()))

    def test_unnamed_tag_is_split_but_names_nobody(self):
        rows = prepare_script("— Get up! someone shouted nearby.")
        self.assertEqual(rows, [[UNASSIGNED, "— Get up!", False], [NARRATOR, "someone shouted nearby.", True]])

    def test_reported_speech_is_not_mistaken_for_a_tag(self):
        for line in ("— Morgan said you'd come.", "— Look, Morgan said you'd come.", "— Yes, she said that."):
            self.assertEqual(len(prepare_script(line)), 1, line)

    def test_dialogue_inside_a_narrative_paragraph_is_extracted(self):
        rows = prepare_script('Riley looked at the clock, then at the timetable. "We can still make it."')
        self.assertEqual(rows, [[NARRATOR, "Riley looked at the clock, then at the timetable.", False],
                                [UNASSIGNED, '"We can still make it."', True]])

    def test_scare_quotes_stay_narration(self):
        rows = prepare_script('He called the shed "the office" and laughed.')
        self.assertEqual([row[0] for row in rows], [NARRATOR])

    def test_joined_rows_get_a_short_pause(self):
        text = "— It is green, Morgan said."
        rows = prepare_script(text, aliases={"morgan": "Morgan"})
        chunks = plan_chunks(read_script(text, True, rows, text), {NARRATOR: self.voice, "Morgan": self.voice}, 0.6)
        self.assertEqual([chunk.pause_after for chunk in chunks], [JOINED_PAUSE, 0])

    def test_cast_resolves_profiles_and_custom_interpretation_presets(self):
        rows = [["A", "Ryan — subtle tension", "Character — American, deep", 57]]
        cast = read_cast(rows, CUSTOM_VOICE, self.voice)
        self.assertEqual(cast['A'].speaker, 'Ryan')
        self.assertIn('controlled tension', cast['A'].instructions)
        design_cast = read_cast(rows, VOICE_DESIGN, self.voice)
        self.assertIn('American English', design_cast['A'].description)

    def test_character_can_use_another_model_than_the_narrator(self):
        rows = [["Riley", "", "female", "", "CustomVoice", "Sohee", "", 7]]
        cast = read_cast(rows, VOICE_DESIGN, self.voice)
        self.assertEqual((cast["Riley"].mode, cast["Riley"].speaker), (CUSTOM_VOICE, "Sohee"))

    def test_only_speaking_characters_need_a_complete_voice(self):
        rows = [["Silent", "", "male", "", "CustomVoice", "", "", 1], ["A", "", "male", "", "", "Aiden", "", 2]]
        self.assertIn("A", read_cast(rows, CUSTOM_VOICE, self.voice, {"A"}))
        with self.assertRaisesRegex(ValueError, "Silent"):
            read_cast(rows, CUSTOM_VOICE, self.voice)

    def test_generation_needs_at_most_one_model_switch(self):
        other = Voice("Sohee", "", "", 1, CUSTOM_VOICE)
        chunks = [Chunk(role, "x", 0) for role in (NARRATOR, "T", NARRATOR, "T")]
        order = generation_order(chunks, {NARRATOR: self.voice, "T": other})
        modes = [(self.voice if chunks[i].role == NARRATOR else other).mode for i in order]
        self.assertEqual(len([m for i, m in enumerate(modes) if i == 0 or m != modes[i - 1]]), 2)
        self.assertEqual(sorted(order), [0, 1, 2, 3])
        self.assertIsNone(engine_client._current_model)

    def test_trim_keeps_speech_and_a_short_margin(self):
        rate = 24000
        speech = np.sin(np.linspace(0, 400 * np.pi, rate // 2)).astype(np.float32) * 0.5
        audio = np.concatenate([np.zeros(rate // 2, np.float32), speech, np.zeros(rate, np.float32)])
        trimmed = trim_edges(audio, rate)
        self.assertGreaterEqual(trimmed.size, speech.size)
        self.assertLess(trimmed.size, speech.size + int(rate * 0.12))

    def test_scene_separator_is_a_pause_not_spoken_prose(self):
        lines = read_script('Before.\n\n❦\n\nAfter.', False, None, '')
        chunks = plan_chunks(lines, {NARRATOR: self.voice}, 0.5)
        self.assertEqual([chunk.text for chunk in chunks], ['Before.', 'After.'])
        self.assertEqual([chunk.pause_after for chunk in chunks], [SCENE_PAUSE, 0])


if __name__ == '__main__':
    unittest.main()
