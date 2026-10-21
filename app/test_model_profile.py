"""Model sets: a source checkout is Standard, an installation reads its own set, and only another model file
changes the audio cache key (Standard keys and fixed-voice keys stay as they were)."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import conversion
import model_profile
from conversion import Chunk, passage_key
from dialogue import Voice
from voices import BASE_CLONE, CUSTOM_VOICE, STANDARD_MODEL_FILES, VOICE_DESIGN

COMPACT = {"name": "compact", "label": "Compact", "voice_design": "qwen-talker-1.7b-voicedesign-Q8_0.gguf",
           "custom_voice": "qwen-talker-1.7b-customvoice-Q8_0.gguf", "base": "qwen-talker-1.7b-base-Q8_0.gguf",
           "codec": "qwen-tokenizer-12hz-F32.gguf", "gemma": "gemma4:e4b-it-qat", "render_factor": 0.45}


class ModelProfileTests(unittest.TestCase):
    def installed(self, profile):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        manifest = {"payload_files": []}
        if profile is not None:
            manifest["model_profile"] = profile
        (root / "installation-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return root

    def test_source_checkout_and_older_installation_use_standard(self):
        with TemporaryDirectory() as folder:
            self.assertEqual(model_profile.load(Path(folder)), model_profile.STANDARD)
        self.assertEqual(model_profile.load(self.installed(None)), model_profile.STANDARD)

    def test_installation_reads_its_own_model_set(self):
        profile = model_profile.load(self.installed(COMPACT))
        self.assertEqual(profile["voice_design"], "qwen-talker-1.7b-voicedesign-Q8_0.gguf")
        self.assertEqual(profile["gemma"], "gemma4:e4b-it-qat")
        self.assertEqual(profile["base"], model_profile.STANDARD["base"])  # fixed voices: same clone model

    def test_damaged_profile_cannot_point_elsewhere(self):
        for key, value in (("voice_design", "..\\..\\other.gguf"), ("codec", "C:/model.gguf"), ("base", "model.bin"),
                           ("gemma", "gemma4"), ("gemma", "../gemma:1")):
            with self.assertRaises(ValueError, msg=value):
                model_profile.load(self.installed({**COMPACT, key: value}))
        incomplete = dict(COMPACT)
        del incomplete["gemma"]
        with self.assertRaisesRegex(ValueError, "incomplete"):
            model_profile.load(self.installed(incomplete))

    def test_cache_key_changes_only_for_another_model_file(self):
        chunk = Chunk("Mira", "The tide is turning.", 0.3)
        voices = {mode: Voice("", "A woman in her twenties.", "Calm.", 7, mode)
                  for mode in (VOICE_DESIGN, CUSTOM_VOICE, BASE_CLONE)}
        standard = {mode: passage_key(chunk, voice, 0.55) for mode, voice in voices.items()}
        compact = dict(STANDARD_MODEL_FILES)
        compact[VOICE_DESIGN] = COMPACT["voice_design"]
        compact[CUSTOM_VOICE] = COMPACT["custom_voice"]
        with patch.dict(conversion.MODEL_FILES, compact):
            changed = {mode: passage_key(chunk, voice, 0.55) for mode, voice in voices.items()}
        self.assertNotEqual(standard[VOICE_DESIGN], changed[VOICE_DESIGN])
        self.assertNotEqual(standard[CUSTOM_VOICE], changed[CUSTOM_VOICE])
        self.assertEqual(standard[BASE_CLONE], changed[BASE_CLONE])  # audio with fixed voices stays valid

    def test_standard_cache_keys_are_unchanged_by_this_feature(self):
        # Key computed before model sets existed (same inputs); existing generated audio must remain reusable.
        chunk = Chunk("Narrator", "The storm reached the island.", 0.6)
        voice = Voice("", "A man in his forties.", "Unhurried.", 42, VOICE_DESIGN)
        self.assertEqual(passage_key(chunk, voice, 0.55), "e2495351559986a101e1")


if __name__ == "__main__":
    unittest.main()
