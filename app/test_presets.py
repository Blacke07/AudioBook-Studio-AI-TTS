"""Voice presets: a complete catalog, and applying one fixes the voice like an auditioned take."""
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import soundfile as sf

import fixed_voices
import glossary
import presets
import project
from dialogue import NARRATOR


class PresetTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        # Never touch the installation's own settings, glossary or voices.
        for target, name, value in ((project, "SETTINGS_FILE", root / "settings.json"),
                                    (glossary, "GLOSSARY_FILE", root / "characters.json"),
                                    (fixed_voices, "FOLDER", root / "voices"),
                                    (fixed_voices, "REGISTRY", root / "voices" / "registry.json"),
                                    (fixed_voices, "SAMPLES", root / "voices" / "samples.json")):
            patcher = patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.voices = root / "voices"

    def test_catalog_is_complete_and_matches_its_recordings(self):
        items = presets.load()
        self.assertEqual(len({item["id"] for item in items}), len(items))
        self.assertIn("narrator-warm", {item["id"] for item in items if item["kind"] == "narrator"})
        self.assertTrue(any(item["kind"] == "character" for item in items))
        for item in items:
            file = presets.FOLDER / item["file"]
            self.assertEqual(hashlib.sha256(file.read_bytes()).hexdigest(), item["sha256"], item["id"])
            self.assertGreaterEqual(sf.info(file).duration, fixed_voices.MIN_SECONDS, item["id"])
            self.assertGreaterEqual(len(item["text"]), 20)
            self.assertIn(item["gender"], ("male", "female"))
            self.assertTrue(item["description"].startswith(("A ", "An ")), item["id"])  # gender and age first

    def test_narrator_preset_is_fixed_and_keeps_seed_and_temperature(self):
        entry = presets.apply("man-dry-understated", NARRATOR)
        self.assertTrue((self.voices / entry["file"]).is_file())
        self.assertEqual(fixed_voices.get(NARRATOR)["id"], entry["id"])
        self.assertEqual(fixed_voices.get(NARRATOR)["origin"]["preset"], "man-dry-understated")
        narrator = project.load_settings()["narrator"]
        self.assertEqual((narrator["seed"], narrator["temperature"]), (42, 0.55))
        self.assertEqual(narrator["description"], presets.get("man-dry-understated")["description"])

    def test_character_preset_sets_voice_recipe_and_missing_gender(self):
        glossary.save([["Morgan", "", "unknown", "", glossary.SAME_AS_NARRATOR, "", "A placeholder voice.", 1]])
        preset = presets.get("woman-precise-ironic")
        presets.apply(preset["id"], "Morgan")
        row = glossary.load()[0]
        self.assertEqual((row[2], row[6], row[7]), ("female", preset["description"], preset["seed"]))
        self.assertEqual(fixed_voices.sample_for("Morgan"), preset["text"])
        self.assertEqual(fixed_voices.get("Morgan")["text"], " ".join(preset["text"].split()))

    def test_unknown_preset_or_character_is_refused_without_changes(self):
        with self.assertRaisesRegex(ValueError, "not available"):
            presets.apply("missing", NARRATOR)
        with self.assertRaisesRegex(ValueError, "not in the character glossary"):
            presets.apply("narrator-warm", "Nobody")
        self.assertEqual(fixed_voices.load(), {})


if __name__ == "__main__":
    unittest.main()
