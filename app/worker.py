"""One background worker that runs the queue: analyze all, then generate, then export.

Analysis of every queued chapter happens first so Gemma loads once; then Qwen generates chapter after
chapter. A chapter that still needs the author (lines to attribute) is skipped and reported, never guessed.
"""
from collections import deque
from contextlib import contextmanager
from datetime import datetime
import threading
import time
import traceback

import export
import glossary
import pipeline
import project
import video_jobs
from video import VideoCancelled
from auto_speakers import release_model
from conversion import NotReady, render_chapter


class Worker:
    def __init__(self):
        self._jobs = deque()
        self._wake = threading.Condition()
        self._transfers = 0
        self._stop = threading.Event()
        self._state = {"running": False, "log": []}
        video_jobs.cleanup_scratch(self._log)
        threading.Thread(target=self._loop, name="audiobook-worker", daemon=True).start()

    # -- interface for the web server -------------------------------------------------------------
    def submit(self, volume, stems, steps, force_analysis=False, automatic=False):
        with self._wake:
            if self._transfers:
                raise ValueError('A project transfer is in progress. Start the job after it finishes.')
            self._jobs.append({"volume": volume, "stems": list(stems), "steps": list(steps),
                               "force": force_analysis, "automatic": automatic})
            self._wake.notify()
        self._log(f"Queued: {volume} · {len(stems)} chapters · {', '.join(steps)}")

    def stop(self):
        with self._wake:
            self._jobs.clear()
        self._stop.set()
        self._log("Stop requested. Audio stops after its current passage; video cancels. Completed work is kept.")

    def status(self):
        with self._wake:
            state = dict(self._state)
            state["log"] = list(self._state["log"][-40:])
            state["queued"] = len(self._jobs)
        return state

    # -- internals ---------------------------------------------------------------------------------
    @contextmanager
    def idle_guard(self):
        with self._wake:
            if self._state.get("running") or self._jobs:
                raise ValueError("Stop the queue and wait for it to finish before transferring a project.")
            self._transfers += 1
        try:
            yield
        finally:
            with self._wake:
                self._transfers -= 1

    def _log(self, message):
        line = f"{datetime.now():%H:%M:%S}  {message}"
        with self._wake:
            self._state["log"] = (self._state["log"] + [line])[-200:]

    def _set(self, **values):
        with self._wake:
            self._state.update(values)

    def _loop(self):
        while True:
            with self._wake:
                while not self._jobs:
                    self._wake.wait()
                job = self._jobs.popleft()
                self._state["running"] = True
            self._stop.clear()
            self._set(running=True, volume=job["volume"], phase="", chapter="", fraction=0.0, message="",
                      started=time.time(), done=0, total=0, eta_seconds=None)
            try:
                self._run(job)
            except Exception as error:  # the worker must survive any single failure
                self._log(f"Unexpected error: {error}")
                traceback.print_exc()
            finally:
                self._set(running=False, phase="", chapter="", fraction=0.0, message="", eta_seconds=None)

    def _run(self, job):
        settings = project.load_settings()
        volume = job["volume"]
        chapters = {chapter.stem: chapter for chapter in project.chapters(volume)}
        selected = [chapters[stem] for stem in job["stems"] if stem in chapters]
        steps = list(job["steps"])
        if job.get("automatic") and settings["video"]["enabled"] and "video" not in steps:
            steps.append("video")

        if "analyze" in steps and settings["multi_voice"]:
            rows = glossary.load()
            todo = [chapter for chapter in selected
                    if job["force"] or pipeline.needs_analysis(pipeline.status(chapter, settings, rows)[0])]
            self._set(phase="Analyzing dialogue", total=len(todo), done=0)
            try:
                for index, chapter in enumerate(todo):
                    if self._stop.is_set():
                        return
                    self._set(chapter=chapter.stem, done=index, fraction=index / max(len(todo), 1),
                              message="Gemma is identifying speakers")
                    try:
                        _, _, added = pipeline.analyze(chapter, True, settings, release=False)
                        script = chapter.script()
                        unclear = project.unclear_count(script)
                        self._log(f"Analyzed {chapter.stem}: {unclear} needs review"
                                  + (f"; new characters: {', '.join(added)}" if added else ""))
                    except Exception as error:
                        self._fail(chapter, "analysis", error)
            finally:
                release_model()

        if "render" in steps:
            rows = glossary.load()
            todo = []
            for chapter in selected:
                state, details = pipeline.status(chapter, settings, rows)
                if state in ("generated", "exported"):
                    continue
                if state in ("new", "modified", "needs_review"):
                    self._log(f"Skipped {chapter.stem}: {details.get('reason', pipeline.STATES[state])}")
                    continue
                todo.append((chapter, details.get("remaining_seconds", details["estimated_seconds"])))
            remaining = sum(seconds for _, seconds in todo)
            spent, produced = 0.0, 0.0
            self._set(phase="Generating audio", total=len(todo), done=0)
            for index, (chapter, audio_estimate) in enumerate(todo):
                if self._stop.is_set():
                    return
                self._set(chapter=chapter.stem, done=index)
                started = time.time()

                def progress(done, total, message, base=index, count=len(todo)):
                    fraction = done / max(total, 1)
                    self._set(fraction=(base + fraction) / max(count, 1), message=message,
                              chapter_fraction=fraction)
                    factor = spent / produced if produced > 30 else pipeline.render_factor()
                    left = remaining - audio_estimate * fraction
                    self._set(eta_seconds=round(left * factor))

                try:
                    meta = render_chapter(chapter, settings, progress, self._stop.is_set)
                except NotReady as reason:
                    self._log(f"Skipped {chapter.stem}: {reason}")
                    continue
                except Exception as error:
                    self._fail(chapter, "generation", error)
                    continue
                if meta is None:
                    self._log(f"Stopped in {chapter.stem}; generated passages are kept for resuming.")
                    return
                spent += time.time() - started
                produced += audio_estimate
                remaining -= audio_estimate
                chapter.error_file.unlink(missing_ok=True)
                flagged = len(meta["flagged_lines"])
                checks = meta.get("voice_checks", {})
                self._log(f"Generated {chapter.stem}: {meta['seconds'] / 60:.1f} min"
                          + (f", {flagged} lines to review by listening" if flagged else "")
                          + (f"; voices checked {checks['checked']}, regenerated {checks['redone']}"
                             if checks.get("checked") else ""))
                if "export" in steps:
                    self._export(chapter, settings)

        if "export" in steps:
            for chapter in selected:
                if self._stop.is_set():
                    return
                if pipeline.status(chapter, settings, glossary.load())[0] == "generated":
                    self._export(chapter, settings)

        if "volume" in steps:
            self._set(phase="Exporting the volume", chapter="", message="Preparing the complete audiobook")
            try:
                target, count, seconds = export.export_volume(volume, settings,
                                                              lambda message: self._set(message=message))
                self._log(f"Volume exported: {target.name} · {count} chapters · {seconds / 3600:.1f} hours")
            except Exception as error:
                self._log(f"Volume export failed: {error}")

        if "video" in steps:
            rows = glossary.load()
            todo = []
            for chapter in selected:
                if self._stop.is_set():
                    return
                try:
                    state, details = pipeline.status(chapter, settings, rows)
                    if state not in ("generated", "exported"):
                        self._log(f"Skipped video for {chapter.stem}: generate current audio first.")
                        continue
                    if video_jobs.video_status(chapter, settings, True)["state"] == "ready":
                        self._log(f"Video already current: {chapter.stem}")
                        continue
                    todo.append((chapter, details["seconds"]))
                except Exception as error:
                    self._fail(chapter, "video", error)
            durations = [seconds for _, seconds in todo]
            self._set(phase="Creating video", total=len(todo), done=0, eta_seconds=None)
            for index, (chapter, seconds) in enumerate(todo):
                if self._stop.is_set():
                    return
                self._set(chapter=chapter.stem, done=index, fraction=index/max(1, len(todo)),
                          message="Preparing video", eta_seconds=None)
                factor = video_jobs.measurement(settings)

                def video_progress(fraction, message):
                    remaining = seconds*(1-fraction) + sum(durations[index+1:])
                    self._set(fraction=(index+fraction)/max(1, len(todo)), message=message,
                              eta_seconds=round(remaining*factor) if factor else None)

                try:
                    video_jobs.create_chapter(chapter, settings, self._stop.is_set, video_progress, self._log)
                except VideoCancelled:
                    self._log("Video stopped; completed chapters are kept. Queue it again to resume.")
                    return
                except Exception as error:
                    self._fail(chapter, "video", error)

        self._log("Done." if not self._stop.is_set() else "Stopped.")

    def _export(self, chapter, settings):
        self._set(message=f"Export {settings['export_format'].upper()}")
        try:
            target = export.export_chapter(chapter, settings)
            self._log(f"Exported {target.name}")
        except Exception as error:
            self._fail(chapter, "export", error)

    def _fail(self, chapter, step, error):
        chapter.work.mkdir(parents=True, exist_ok=True)
        target = chapter.work/"video-error.txt" if step == "video" else chapter.error_file
        target.write_text(f"{step}: {error}", encoding="utf-8")
        self._log(f"Error during {step} in {chapter.stem}: {error}")
