"""Emotion audition seeds and saved descriptions; no inference or personal data."""
from copy import deepcopy
import unittest

from dialogue import Voice
from emotion_audition import prepare_voice
from voices import VOICE_DESIGN, CUSTOM_VOICE, CHARACTER_PROFILES


class EmotionAuditionTests(unittest.TestCase):
    def setUp(self):
        self.recipe = Voice('Ryan', 'A changed, rough bass voice.', 'Read naturally.', 99, VOICE_DESIGN)
        self.fixed = {'id': 'fix-synthetic', 'origin': {'seed': 2608, 'design': 'A clear, light baritone.'}}

    def test_approved_description_wins_over_the_edited_character_recipe(self):
        voice = prepare_voice(self.recipe, self.fixed, 'shouting')
        self.assertEqual(voice.description, 'A clear, light baritone.')
        self.assertEqual(voice.seed, 2608)
        self.assertIn('Shout this line', voice.instructions)

    def test_manual_seed_is_exact_not_an_offset_from_the_reference(self):
        for seed in (0, 26, 2608, 2147483647):
            with self.subTest(seed=seed):
                self.assertEqual(prepare_voice(self.recipe, self.fixed, 'calm', seed).seed, seed)

    def test_invalid_seed_is_refused(self):
        for seed in (-1, True, False, 1.5, '2608', '', 2147483648):
            with self.subTest(seed=seed):
                with self.assertRaisesRegex(ValueError, 'whole-number seed'):
                    prepare_voice(self.recipe, self.fixed, 'angry', seed)

    def test_legacy_reference_without_description_uses_the_current_recipe(self):
        voice = prepare_voice(self.recipe, {'origin': {'seed': 13}}, 'calm')
        self.assertEqual((voice.description, voice.seed), (self.recipe.description, 13))

    def test_legacy_reference_without_seed_uses_the_current_recipe_seed(self):
        self.assertEqual(prepare_voice(self.recipe, {}, 'calm').seed, 99)

    def test_named_saved_profile_is_resolved_to_its_description(self):
        profiles = next(group for group in CHARACTER_PROFILES.values() if group)
        name = next(iter(profiles))
        self.fixed['origin']['design'] = name
        self.assertEqual(prepare_voice(self.recipe, self.fixed, 'calm').description, profiles[name])

    def test_inputs_and_neutral_reference_are_not_modified(self):
        before = deepcopy(self.fixed)
        voice = prepare_voice(self.recipe, self.fixed, 'angry', 31)
        self.assertEqual(self.fixed, before)
        self.assertEqual(self.recipe.seed, 99)
        self.assertEqual(self.recipe.instructions, 'Read naturally.')
        self.assertEqual(voice.mode, VOICE_DESIGN)

    def test_custom_voice_keeps_its_named_speaker(self):
        voice = prepare_voice(Voice('Aiden', '', 'Natural.', 11, CUSTOM_VOICE), self.fixed, 'angry', 31)
        self.assertEqual((voice.speaker, voice.mode), ('Aiden', CUSTOM_VOICE))

    def test_unknown_emotion_is_not_silently_accepted(self):
        with self.assertRaises(ValueError):
            prepare_voice(self.recipe, self.fixed, 'imaginary')
