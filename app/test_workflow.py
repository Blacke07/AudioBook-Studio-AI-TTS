"""Synthetic speaker failures and all-or-nothing stage prerequisites; no model inference."""
from collections import deque
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import Mock, patch

import auto_speakers as speakers
import glossary
import pipeline
import project
from worker import Worker


class AnalysisRepairTests(unittest.TestCase):
    def test_schema_requires_batch_length_and_limits_ids_without_mutating_template(self):
        first = speakers.assignment_schema([4, 7, 10])["properties"]["assignments"]
        second = speakers.assignment_schema([20])["properties"]["assignments"]
        self.assertEqual((first["minItems"], first["maxItems"]), (3, 3))
        self.assertEqual(first["items"]["properties"]["id"]["enum"], [4, 7, 10])
        self.assertEqual(second["minItems"], 1)
        self.assertNotIn("minItems", speakers.SCHEMA["properties"]["assignments"])

    def test_missing_ids_diagnosis_is_precise_and_contains_no_story_text(self):
        with self.assertRaises(speakers.AnalysisError) as caught:
            speakers.validate_assignments([{"id": 2}], [2, 9], "Private story", [])
        detail = caught.exception.diagnostic
        self.assertEqual(detail["missing_rows"], [10])
        self.assertEqual((detail["expected_count"], detail["returned_count"]), (2, 1))
        self.assertNotIn("Private story", json.dumps(detail))

    def test_repair_uses_three_line_batches_and_keeps_uncertain_lines_unassigned(self):
        calls = []
        def response(path, data, timeout):
            content = json.loads(data["messages"][1]["content"])
            ids = content["requested_ids"]
            calls.append((ids, data["format"]))
            assignments = [dict(id=i, speaker=None, gender="unknown", basis="unclear", reason="Unclear.") for i in ids]
            return {"message": {"content": json.dumps({"assignments": assignments})}, "done_reason": "stop"}
        text = "\n\n".join("— A complete invented sentence." for _ in range(7))
        with patch.object(speakers, "ensure_ollama"), patch.object(speakers, "request", side_effect=response), \
                patch.object(speakers, "release_model") as release:
            rows, _, entries, report, _ = speakers.attribute(text, [], "VoiceDesign", lambda *a, **k: None,
                                                            batch_size=speakers.REPAIR_BATCH)
        self.assertEqual([len(ids) for ids, _ in calls], [3, 3, 1])
        self.assertTrue(all(row[0] == "Unassigned" for row in rows))
        self.assertEqual(entries, [])
        self.assertIn("7 unclear", report)
        release.assert_called_once()

    def test_failed_repair_keeps_previous_script_and_records_batch_diagnostic(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "001 - Test.txt"
            source.write_text("— An invented line.", encoding="utf-8")
            with patch.object(project, "WORK", root / "work"):
                chapter = project.Chapter("Demo", source)
                original = {"source_hash":project.text_hash(chapter.text()), "rows":[["Ada", chapter.text(), False, 0]]}
                chapter.save_script(original)
                error = speakers.AnalysisError("Incomplete batch.", "incomplete", [1, 3], [{"id": 1}])
                error.diagnostic.update(batch=2, batches=5, model="synthetic")
                with patch.object(pipeline, "attribute", side_effect=error), patch.object(pipeline, "close_engine"), \
                        patch.object(glossary, "load", return_value=[]):
                    with self.assertRaises(speakers.AnalysisError):
                        pipeline.analyze(chapter, True, {"multi_voice":True,"narrator":{"mode":"VoiceDesign"}}, repair=True)
                self.assertEqual(chapter.script(), original)
                detail = json.loads((chapter.work / "analysis-error.json").read_text())
                self.assertEqual(detail["missing_rows"], [4])
                self.assertEqual(detail["source_hash"], original["source_hash"])

    def test_manual_preparation_clears_error_and_does_not_call_ai(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "001 - Test.txt"
            source.write_text("— An invented line.", encoding="utf-8")
            with patch.object(project, "WORK", root / "work"):
                chapter = project.Chapter("Demo", source)
                chapter.work.mkdir(parents=True)
                chapter.error_file.write_text("analysis: incomplete")
                project.write_json(chapter.work / "analysis-error.json", {"code":"incomplete"})
                with patch.object(pipeline, "attribute") as ai, patch.object(glossary, "load", return_value=[]), \
                        patch.object(glossary, "add_missing", return_value=[]):
                    pipeline.analyze(chapter, False, {"multi_voice":True,"narrator":{"mode":"VoiceDesign"}})
                ai.assert_not_called()
                self.assertFalse(chapter.error_file.exists())
                self.assertFalse((chapter.work / "analysis-error.json").exists())
                self.assertEqual(chapter.script()["rows"][0][0], "Unassigned")


class ManualEditorTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.source = root / "001.txt"
        self.source.write_text("— A complete invented sentence.", encoding="utf-8")
        for module, name, value in ((project, "WORK", root / "work"),):
            item = patch.object(module, name, value)
            item.start(); self.addCleanup(item.stop)
        self.chapter = project.Chapter("Demo", self.source)
        self.chapter.work.mkdir(parents=True)
        self.chapter.error_file.write_text("analysis: AI did not assign all requested lines.")
        import app as studio
        self.studio = studio
        for item in (patch.object(project, "get_chapter", return_value=self.chapter),
                     patch.object(glossary, "load", return_value=[]),
                     patch.object(glossary, "add_missing", return_value=[])):
            item.start(); self.addCleanup(item.stop)

    def test_failed_analysis_still_shows_text_and_editable_speakers_without_creating_files(self):
        before = sorted(path.name for path in self.chapter.work.iterdir())
        with patch.object(pipeline, "attribute") as ai:
            page = self.studio.chapter("Demo", "001")
        ai.assert_not_called()
        self.assertTrue(page["manual_draft"])
        self.assertEqual(page["lines"][0]["text"], self.chapter.text())
        self.assertEqual(page["lines"][0]["speaker"], "Unassigned")
        self.assertEqual(before, sorted(path.name for path in self.chapter.work.iterdir()))

    def test_manual_save_needs_no_model_and_clears_analysis_error_without_changing_source(self):
        before = self.source.read_bytes()
        draft = pipeline.manual_script(self.chapter, [])
        draft["rows"][0][0] = "Narrator"
        with patch.object(pipeline, "attribute") as ai:
            self.studio.save_rows({"volume":"Demo","stem":"001","rows":draft["rows"],
                                   "source_hash":draft["source_hash"]})
        ai.assert_not_called()
        self.assertFalse(self.chapter.error_file.exists())
        self.assertEqual(self.chapter.script()["rows"][0][0], "Narrator")
        self.assertEqual(self.source.read_bytes(), before)

    def test_changed_text_rejects_old_manual_draft_without_saving(self):
        draft = pipeline.manual_script(self.chapter, [])
        self.source.write_text("A different invented sentence.")
        with self.assertRaisesRegex(ValueError, "text has changed"):
            self.studio.save_rows({"volume":"Demo","stem":"001","rows":draft["rows"],
                                   "source_hash":draft["source_hash"]})
        self.assertFalse(self.chapter.script_file.exists())

    def test_manual_save_waits_for_running_analysis_so_it_cannot_overwrite_the_authors_edits(self):
        draft = pipeline.manual_script(self.chapter, [])
        with patch.object(self.studio.worker, "_state", {"running":True}), \
                self.assertRaisesRegex(ValueError, "Stop the queue"):
            self.studio.save_rows({"volume":"Demo","stem":"001","rows":draft["rows"],
                                   "source_hash":draft["source_hash"]})
        self.assertFalse(self.chapter.script_file.exists())

    def test_manual_editor_cannot_replace_book_text_with_arbitrary_rows(self):
        draft = pipeline.manual_script(self.chapter, [])
        draft["rows"][0][1] = "An unauthorized replacement."
        with self.assertRaisesRegex(ValueError, "line text has changed"):
            self.studio.save_rows({"volume":"Demo","stem":"001","rows":draft["rows"],
                                   "source_hash":draft["source_hash"]})
        self.assertFalse(self.chapter.script_file.exists())

    def test_split_works_before_any_ai_analysis_and_preserves_all_words(self):
        original = self.chapter.text()
        self.studio.split_row({"volume":"Demo","stem":"001","index":0,"phrase":"invented",
                               "speaker":"Narrator","source_hash":project.text_hash(original)})
        script = self.chapter.script()
        self.assertEqual(len(script["rows"]), 2)
        self.assertEqual(" ".join(row[1] for row in script["rows"]), original)
        self.assertFalse(self.chapter.error_file.exists())
        current = "— A revised invented sentence."
        self.source.write_text(current, encoding="utf-8")
        self.studio.split_row({"volume":"Demo","stem":"001","index":0,"phrase":"invented",
                               "speaker":"Narrator","source_hash":project.text_hash(current)})
        self.assertEqual(" ".join(row[1] for row in self.chapter.script()["rows"]), current)


class WorkflowTests(unittest.TestCase):
    def worker(self):
        worker = Worker.__new__(Worker)
        worker._wake = threading.Condition()
        worker._jobs = deque()
        worker._transfers = 0
        worker._stop = threading.Event()
        worker._state = {"running":False,"log":[]}
        return worker

    def test_batch_gate_does_not_generate_any_audio_when_one_chapter_needs_review(self):
        chapters = [Mock(stem="001"), Mock(stem="002")]
        states = {"001":("analyzed", {"text_ready":True,"estimated_seconds":1}),
                  "002":("needs_review", {"text_ready":False,"reason":"One unassigned speaker."})}
        worker = self.worker()
        with patch.object(project, "chapters", return_value=chapters), \
                patch.object(project, "load_settings", return_value={"video":{"enabled":False}}), \
                patch.object(glossary, "load", return_value=[]), \
                patch.object(pipeline, "status", side_effect=lambda c, *a:states[c.stem]), \
                patch("worker.render_chapter") as render:
            worker._run({"volume":"Demo","stems":["001","002"],"steps":["render"],"force":False})
        render.assert_not_called()
        self.assertIn("002", " ".join(worker.status()["log"]))
        self.assertIn("Batch waiting", " ".join(worker.status()["log"]))

    def test_selected_ready_chapter_is_allowed_even_if_another_unselected_chapter_is_not(self):
        chapter = Mock(stem="001")
        with patch.object(glossary, "load", return_value=[]), \
                patch.object(pipeline, "status", return_value=("analyzed", {"text_ready":True})):
            pipeline.require_ready([chapter], {}, "render")

    def test_video_and_export_require_current_audio_for_every_target(self):
        chapter = Mock(stem="001")
        for step in ("export", "video"):
            with self.subTest(step=step), patch.object(glossary, "load", return_value=[]), \
                    patch.object(pipeline, "status", return_value=("outdated", {"text_ready":True})):
                with self.assertRaisesRegex(ValueError, "Generate current audio"):
                    pipeline.require_ready([chapter], {}, step)

    def test_automatic_run_stops_after_analysis_if_any_chapter_remains_unassigned(self):
        chapter = Mock(stem="001")
        chapter.script.return_value = {"rows":[["Unassigned","An invented line.",False,0]]}
        worker = self.worker()
        with patch.object(project, "chapters", return_value=[chapter]), \
                patch.object(project, "load_settings", return_value={"multi_voice":True,"video":{"enabled":False}}), \
                patch.object(glossary, "load", return_value=[]), \
                patch.object(pipeline, "status", return_value=("needs_review", {"text_ready":False})), \
                patch.object(pipeline, "analyze", return_value=([],"",[])) as analyze, \
                patch("worker.release_model"), patch("worker.render_chapter") as render:
            worker._run({"volume":"Demo","stems":["001"],"steps":["analyze","render","export"],"force":False})
        analyze.assert_called_once()
        render.assert_not_called()

    def test_generation_error_can_be_resumed_but_missing_text_analysis_cannot(self):
        self.assertTrue(pipeline.readiness("error", {"text_ready":True})["can_generate"])
        self.assertFalse(pipeline.readiness("analyzed", {"text_ready":False})["can_generate"])
        self.assertFalse(pipeline.readiness("error", {"text_ready":True,"reason":"Invalid voice."})["can_generate"])

    def test_api_refuses_blocked_generation_before_queueing_it(self):
        import app as studio
        chapter = Mock(stem="001")
        with patch.object(project, "chapters", return_value=[chapter]), \
                patch.object(glossary, "load", return_value=[]), \
                patch.object(pipeline, "status", return_value=("new", {"text_ready":False})), \
                patch.object(studio.worker, "submit") as submit:
            with self.assertRaisesRegex(ValueError, "Finish text analysis"):
                studio.run({"volume":"Demo","stems":["001"],"steps":["render"]})
        submit.assert_not_called()

    def test_api_does_not_replace_missing_chapter_with_a_different_batch(self):
        import app as studio
        with patch.object(project, "chapters", return_value=[Mock(stem="001")]), \
                patch.object(studio.worker, "submit") as submit:
            with self.assertRaisesRegex(ValueError, "no longer exist"):
                studio.run({"volume":"Demo","stems":["002"],"steps":["analyze"]})
        submit.assert_not_called()

    def test_repair_endpoint_queues_only_the_requested_analysis_and_mode(self):
        import app as studio
        chapter = Mock()
        chapter.error_file.exists.return_value = True
        chapter.error_file.read_text.return_value = "analysis: AI did not assign all requested lines."
        with patch.object(project, "get_chapter", return_value=chapter), \
                patch.object(studio.worker, "submit") as submit:
            studio.repair_analysis({"volume":"Demo","stem":"001","mode":"small_batches"})
        submit.assert_called_once_with("Demo", ["001"], ["analyze"], True, analysis_mode="small_batches")

    def test_legacy_analysis_error_has_repair_guidance_but_no_invented_counts(self):
        with TemporaryDirectory() as directory:
            chapter = Mock(work=Path(directory))
            issue = pipeline.analysis_problem(chapter, "An invented line.")
        self.assertNotIn("expected_count", issue)
        self.assertIn("three", issue["repair"])

    def test_existing_explicit_narrator_policy_is_preserved_but_analysis_is_still_required(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "001.txt"
            source.write_text("An invented line.")
            with patch.object(project, "WORK", root / "work"):
                chapter = project.Chapter("Demo", source)
                settings = {"multi_voice":True,"unclear_policy":"narrator"}
                with patch.object(pipeline, "chapter_plan", return_value=([], [], [])):
                    self.assertFalse(pipeline.status(chapter, settings, [])[1]["text_ready"])
                    chapter.save_script({"source_hash":project.text_hash(chapter.text()),
                                         "rows":[["Unassigned",chapter.text(),False,0]]})
                    self.assertTrue(pipeline.status(chapter, settings, [])[1]["text_ready"])
                    settings["unclear_policy"] = "wait"
                    self.assertFalse(pipeline.status(chapter, settings, [])[1]["text_ready"])


if __name__ == "__main__":
    unittest.main()
