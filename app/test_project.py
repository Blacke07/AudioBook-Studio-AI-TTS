"""Volumes, chapter states, resumable rendering and export, with a fake engine and temporary folders."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import numpy as np
import soundfile as sf

import conversion
import export
import fixed_voices
import glossary
import pipeline
import project
from dialogue import INNER_VOICE, NARRATOR, UNASSIGNED, prepare_script
from voices import BASE_CLONE

CHAPTER = "— I —\n\nMorgan stopped on the step.\n— To Northport, Morgan said.\n— Yes.\n\n<She breathes first.>\n\n❦\n\n`Thought.` He left."


def fake_generate(text, voice, temperature, variant=0):
    fake_generate.calls.append(text)
    return np.full(int(24000 * (0.3 + len(text) / 30)), 0.1, dtype=np.float32)


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        root = Path(self.temp.name)
        self.source = root / "book"
        self.source.mkdir()
        (self.source / "001 - First.txt").write_text(CHAPTER, encoding="utf-8")
        (self.source / "002 - Second.txt").write_text("Only prose here.", encoding="utf-8")
        (self.source / "!Plan.md").write_text("ignored", encoding="utf-8")
        patches = [patch.object(project, name, root / value) for name, value in (
            ("SETTINGS_FILE", "settings.json"), ("VOLUMES_FILE", "volumes.json"), ("WORK", "work"),
            ("PASSAGES", "work/passages"), ("PROBES", "work/previews"), ("EXPORT", "export"))]
        patches.append(patch.object(glossary, "GLOSSARY_FILE", root / "characters.json"))
        patches.append(patch.object(fixed_voices, "FOLDER", root / "voices"))
        patches.append(patch.object(fixed_voices, "REGISTRY", root / "voices" / "registry.json"))
        patches.append(patch.object(conversion, "generate", fake_generate))
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        self.addCleanup(self.temp.cleanup)
        fake_generate.calls = []
        glossary.save([["Morgan", "", "male", "", "", "Ryan", "A deep male voice.", 7],
                       glossary.propose(INNER_VOICE, "unknown", [])])
        self.settings = project.load_settings()
        project.add_volume("Book", self.source)

    def chapter(self, number=0):
        return project.chapters("Book")[number]

    def test_chapters_are_ordered_and_titled(self):
        self.assertEqual([(c.number, c.title) for c in project.chapters("Book")], [(1, "First"), (2, "Second")])
        self.assertEqual(project.announcement("262 - North"), "Chapter 262. North.")

    def test_headings_and_inner_voice_lines(self):
        rows = prepare_script(CHAPTER, aliases={"morgan": "Morgan"})
        self.assertEqual(rows[0], [NARRATOR, "— I —", False])
        self.assertIn([INNER_VOICE, "<She breathes first.>", False], rows)
        self.assertEqual(conversion.speakable("— Fire II —"), "Fire Two.")
        self.assertEqual(conversion.speakable("`Thought.` He [left] <now>."), "Thought. He left now.")

    def test_full_flow_wait_for_author_then_render_resume_and_export(self):
        chapter = self.chapter()
        self.assertEqual(pipeline.status(chapter, self.settings, glossary.load())[0], "new")
        pipeline.analyze(chapter, False, self.settings)
        state, details = pipeline.status(chapter, self.settings, glossary.load())
        self.assertEqual((state, details["unclear"]), ("needs_review", 1))
        script = chapter.script()
        script["rows"] = [["Alex" if row[0] == UNASSIGNED else row[0], *row[1:]] for row in script["rows"]]
        chapter.save_script(script)
        glossary.add_missing([glossary.propose("Alex", "male", glossary.load())])
        self.assertEqual(pipeline.status(chapter, self.settings, glossary.load())[0], "analyzed")

        stops = iter([False, False, True])
        self.assertIsNone(conversion.render_chapter(chapter, self.settings, should_stop=lambda: next(stops)))
        self.assertEqual(pipeline.status(chapter, self.settings, glossary.load())[0], "partial")
        first = len(fake_generate.calls)
        meta = conversion.render_chapter(chapter, self.settings)
        self.assertEqual(len(fake_generate.calls) - first, len(meta["keys"]) - first)  # resumed, nothing redone
        self.assertTrue(fake_generate.calls[0].startswith("Chapter 1. First."))
        self.assertEqual(pipeline.status(chapter, self.settings, glossary.load())[0], "generated")

        script["rows"][-1][3] = 1  # another take of one line: only that passage is generated again
        chapter.save_script(script)
        state, details = pipeline.status(chapter, self.settings, glossary.load())
        self.assertEqual(state, "outdated")
        self.assertEqual(pipeline.STATES["outdated"], "Audio outdated")
        self.assertRegex(details["outdated_reason"], r"^1 of \d+ passages no longer match the generated audio")
        before = len(fake_generate.calls)
        conversion.render_chapter(chapter, self.settings)
        self.assertEqual(len(fake_generate.calls) - before, 1)

        if export.available():
            target = export.export_chapter(chapter, self.settings)
            self.assertEqual(target.suffix, ".mp3")
            self.assertEqual(pipeline.status(chapter, self.settings, glossary.load())[0], "exported")
            conversion.render_chapter(self.chapter(1), self.settings | {"multi_voice": False})
            volume, count, _ = export.export_volume("Book", self.settings)
            self.assertEqual((volume.suffix, count), (".m4b", 2))

    def test_unclear_lines_can_be_left_to_the_narrator(self):
        chapter = self.chapter()
        pipeline.analyze(chapter, False, self.settings)
        relaxed = self.settings | {"unclear_policy": "narrator"}
        self.assertEqual(pipeline.status(chapter, relaxed, glossary.load())[0], "analyzed")

    def test_changed_source_text_is_detected(self):
        chapter = self.chapter()
        pipeline.analyze(chapter, False, self.settings)
        chapter.path.write_text(CHAPTER + "\nNew line.", encoding="utf-8")
        self.assertEqual(pipeline.status(chapter, self.settings, glossary.load())[0], "modified")

    def test_fixed_voices_replace_the_recipe_with_the_clone(self):
        folder = Path(self.temp.name) / "voices"
        with patch.object(fixed_voices, "FOLDER", folder), patch.object(fixed_voices, "REGISTRY", folder / "registry.json"):
            take = Path(self.temp.name) / "take.wav"
            sf.write(take, np.zeros(24000 * 2, dtype=np.float32), 24000)
            with self.assertRaisesRegex(ValueError, "at least"):
                fixed_voices.fix(NARRATOR, take, "A text that is long enough for a take.", {})
            sf.write(take, np.full(24000 * 6, 0.1, dtype=np.float32), 24000)
            narrator = fixed_voices.fix(NARRATOR, take, "A text that is long enough for a take.", {})
            morgan = fixed_voices.fix("Morgan", take, "Another text, long enough for Morgan.", {})
            voice = conversion.narrator_voice(self.settings)
            self.assertEqual((voice.mode, voice.speaker), (BASE_CLONE, narrator["id"]))
            chapter = self.chapter()
            pipeline.analyze(chapter, False, self.settings)
            chunks, voices, _ = conversion.chapter_plan(chapter, self.settings | {"unclear_policy": "narrator"})
            self.assertEqual(voices["Morgan"].speaker, morgan["id"])
            self.assertEqual(fixed_voices.reference(morgan["id"])[1], "Another text, long enough for Morgan.")
            fixed_voices.unfix(NARRATOR)
            self.assertNotEqual(conversion.narrator_voice(self.settings).mode, BASE_CLONE)

    def test_drifting_take_is_redone_and_the_best_one_kept(self):
        project.PASSAGES.mkdir(parents=True, exist_ok=True)
        voice = conversion.Voice("fix-x", "", "", 1, BASE_CLONE)
        references = {"Riley": Path("riley.wav"), "Casey": Path("casey.wav")}
        chunk = conversion.Chunk("Riley", "A line long enough to be judged by its voice fingerprint.", 0)
        for margins, expected in (([0.01, 0.20], (2, False)), ([0.01, 0.03, 0.02], (3, True))):
            verdicts = iter({"own": 0.6, "other": "Casey", "other_score": 0.6 - m, "margin": m} for m in margins)
            with patch.object(conversion.voice_check, "judge", lambda *a: next(verdicts)):
                conversion.render_checked(chunk, voice, 0.4, f"k{len(margins)}", references)
            check = project._read_json(conversion.passage_file(f"k{len(margins)}").with_suffix(".qc.json"), {})
            self.assertEqual((check["attempts"], check["drifting"]), expected)
            self.assertEqual(check["margin"], max(margins))
            self.assertTrue(conversion.passage_file(f"k{len(margins)}").exists())
            self.assertEqual(list(project.PASSAGES.glob("*.try*.wav")), [])

    def test_changing_a_voice_only_invalidates_that_character(self):
        chapter = self.chapter()
        pipeline.analyze(chapter, False, self.settings)
        _, _, before = conversion.chapter_plan(chapter, self.settings | {"unclear_policy": "narrator"})
        rows = glossary.load()
        rows[0][6] = "Another voice."
        glossary.save(rows)
        chunks, _, after = conversion.chapter_plan(chapter, self.settings | {"unclear_policy": "narrator"})
        changed = {chunk.role for chunk, old, new in zip(chunks, before, after) if old != new}
        self.assertEqual(changed, {"Morgan"})


if __name__ == "__main__":
    unittest.main()
