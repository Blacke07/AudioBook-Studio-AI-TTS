"""The optional VoxCPM2 narrator engine: invented text and fake runtimes; no inference, no owner data."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import conversion
import emotions
import engine_client
import project
import voices
import voxcpm_server
from dialogue import NARRATOR, Voice


class VoxCpmTests(unittest.TestCase):
    def runtime(self, root, model=True, python=True):
        root = Path(root)
        (root / "model").mkdir()
        if model:
            (root / "model" / "model.safetensors").write_bytes(b"x")
        interpreter = root / "python.exe"
        if python:
            interpreter.write_bytes(b"x")
        config = root / "voxcpm.json"
        config.write_text(json.dumps({"python": str(interpreter), "model": str(root / "model")}), encoding="utf-8")
        return config

    def test_every_emotion_has_a_style_and_neutral_has_none(self):
        self.assertEqual(set(emotions.STYLES), set(emotions.KEYS))
        self.assertEqual(emotions.style(emotions.NEUTRAL), "")
        for key in emotions.KEYS[1:]:
            self.assertTrue(emotions.style(key), key)
            self.assertNotRegex(emotions.style(key), r"[()\[\]<>]", key)  # a style is plain words

    def test_the_voxcpm_voice_needs_a_fixed_take_and_passes_the_style_through(self):
        self.assertEqual(voices.voice_parameters(voices.VOX_CLONE, "fix-abc", "", "calm and slow"),
                         ("fix-abc", "calm and slow"))
        with self.assertRaisesRegex(ValueError, "fixed voice"):
            voices.voice_parameters(voices.VOX_CLONE, "Ryan", "", "")

    def test_runtime_is_reported_only_when_both_paths_exist(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(engine_client, "VOXCPM_CONFIG", Path(folder) / "none.json"):
            self.assertIsNone(engine_client.voxcpm_runtime())
        for options in ({"model": False}, {"python": False}):
            with self.subTest(options), tempfile.TemporaryDirectory() as folder:
                with patch.object(engine_client, "VOXCPM_CONFIG", self.runtime(folder, **options)):
                    self.assertIsNone(engine_client.voxcpm_runtime())
        with tempfile.TemporaryDirectory() as folder, patch.object(engine_client, "VOXCPM_CONFIG", self.runtime(folder)):
            self.assertEqual(engine_client.voxcpm_runtime()["model"], Path(folder) / "model")

    def test_starting_the_engine_without_the_runtime_explains_what_to_do(self):
        with patch.object(engine_client, "voxcpm_runtime", return_value=None):
            with self.assertRaisesRegex(FileNotFoundError, "Choose Qwen"):
                engine_client.ensure_engine(voices.VOX_CLONE)

    def test_requests_match_each_engine(self):
        body = engine_client.request_body("Hello.", voices.VOX_CLONE, "fix-abc", "tender, warm", 7, 0.55)
        self.assertEqual(body, {"input": "Hello.", "voice": "fix-abc", "style": "tender, warm", "seed": 7})
        qwen = engine_client.request_body("Hello.", voices.BASE_CLONE, "fix-abc", "", 7, 0.55)
        self.assertEqual(qwen["voice"], "fix-abc")
        self.assertEqual(qwen["temperature"], 0.55)
        self.assertNotIn("instructions", qwen)
        self.assertEqual(engine_client._url(voices.VOX_CLONE), engine_client.VOXCPM_URL)
        self.assertEqual(engine_client._url(voices.BASE_CLONE), engine_client.BASE_URL)

    def test_the_server_turns_text_parentheses_into_commas_so_only_the_style_is_a_hint(self):
        self.assertEqual(voxcpm_server.styled("He left (quietly) at dawn.", "calm"), "(calm)He left, quietly, at dawn.")
        self.assertEqual(voxcpm_server.styled("Plain.", ""), "Plain.")
        self.assertEqual(voxcpm_server.styled("Plain.", "a (b) c"), "(a b c)Plain.")

    def narrator(self, engine):
        settings = {**project.DEFAULT_SETTINGS, "narrator": {**project.DEFAULT_SETTINGS["narrator"], "engine": engine}}
        with patch.object(conversion.fixed_voices, "get", return_value={"id": "fix-abc"}):
            return conversion.narrator_voice(settings)

    def test_the_narrator_engine_picks_the_reader_of_the_same_fixed_take(self):
        self.assertEqual(self.narrator("qwen").mode, voices.BASE_CLONE)
        chosen = self.narrator("voxcpm")
        self.assertEqual((chosen.mode, chosen.speaker), (voices.VOX_CLONE, "fix-abc"))

    def test_voxcpm_hears_the_emotion_as_a_style_and_neutral_is_unchanged(self):
        voice = self.narrator("voxcpm")
        chunk = conversion.Chunk(NARRATOR, "A line.", 0, emotion="tender")
        heard_voice, heard = conversion.delivered(chunk, voice)
        self.assertTrue(heard)
        self.assertEqual(heard_voice.instructions, emotions.style("tender"))
        self.assertEqual(conversion.delivered(conversion.Chunk(NARRATOR, "A line.", 0), voice), (voice, False))
        self.assertEqual(conversion.missing_takes([chunk], {NARRATOR: voice}), set())  # no per-emotion take is needed

    def test_keys_differ_by_engine_and_by_emotion_and_qwen_keys_are_unchanged(self):
        qwen, vox = self.narrator("qwen"), self.narrator("voxcpm")
        plain = conversion.Chunk(NARRATOR, "A line.", 0)
        tender = conversion.Chunk(NARRATOR, "A line.", 0, emotion="tender")
        keys = {conversion.passage_key(plain, qwen, 0.55), conversion.passage_key(plain, vox, 0.55),
                conversion.passage_key(tender, vox, 0.55)}
        self.assertEqual(len(keys), 3)
        self.assertEqual(conversion.passage_key(plain, qwen, 0.55),
                         conversion.passage_key(plain, Voice(qwen.speaker, "", "", qwen.seed, voices.BASE_CLONE), 0.55))

    def test_an_unknown_engine_in_the_saved_settings_falls_back_to_qwen(self):
        with tempfile.TemporaryDirectory() as folder:
            saved = Path(folder) / "settings.json"
            saved.write_text(json.dumps({"narrator": {"engine": "other"}}), encoding="utf-8")
            with patch.object(project, "SETTINGS_FILE", saved):
                self.assertEqual(project.load_settings()["narrator"]["engine"], "qwen")


if __name__ == "__main__":
    unittest.main()
