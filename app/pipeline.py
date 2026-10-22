"""What each chapter needs next, and the analysis step that produces its script."""
from datetime import datetime

import glossary
import model_profile
import project
from auto_speakers import AnalysisError, BATCH, REPAIR_BATCH, attribute
from conversion import LOCK, NotReady, chapter_plan, passage_file
from dialogue import NARRATOR, PAUSE, UNASSIGNED, prepare_script
from engine_client import close_engine

CHARS_PER_SECOND = 14.5      # rough speech-duration estimate
# GPU seconds per audio second, one passage at a time. Standard (F32): RTF 0.42 + overhead, measured.
RENDER_FACTOR = model_profile.CURRENT["render_factor"]
FIXED_RENDER_FACTOR = 0.25   # rough fixed-reference rendering estimate


def render_factor():
    import fixed_voices
    return FIXED_RENDER_FACTOR if fixed_voices.get(NARRATOR) else RENDER_FACTOR

# Chapter states shown in the GUI, in the order a chapter goes through them.
STATES = {
    "new": "Not analyzed",
    "modified": "Text changed",
    "needs_review": "Needs review",
    "analyzed": "Ready to generate",
    "partial": "Partly generated",
    "outdated": "Outdated",
    "generated": "Generated",
    "exported": "Exported",
    "error": "Error",
}


def analyze(chapter, use_ai, settings, progress=lambda fraction, desc="": None, release=True, repair=False):
    """Split the chapter, attribute its lines (Gemma when use_ai) and store the script."""
    text = chapter.text()
    (chapter.work / "analysis-error.json").unlink(missing_ok=True)
    entries = glossary.load()
    from character_registry import scoped_rows, register_analysis
    entries = scoped_rows(entries, chapter.volume)
    proposals = {}
    if use_ai and settings["multi_voice"]:
        with LOCK:
            close_engine()  # Gemma needs the GPU memory Qwen holds
            try:
                rows, _, entries, report, speakers = attribute(text, entries, settings["narrator"]["mode"],
                                                               progress, release,
                                                               batch_size=REPAIR_BATCH if repair else BATCH, proposals=proposals)
            except AnalysisError as error:
                project.write_json(chapter.work / "analysis-error.json",
                                   {**error.diagnostic, "source_hash": project.text_hash(text)})
                raise
    else:
        rows = manual_script(chapter, entries)["rows"]
        speakers = list(dict.fromkeys(row[0] for row in rows if row[0] not in (NARRATOR, PAUSE, UNASSIGNED)))
        for name in speakers:
            if name not in {row[0] for row in entries}:
                entries.append(glossary.propose(name, "unknown", entries))
        report = "Split without AI. Dialogue without explicit speaker tags remains unassigned."
    rows, added = register_analysis(rows, entries, chapter.volume, proposals) if use_ai and settings['multi_voice'] else (rows, glossary.add_missing(entries))
    speakers = list(dict.fromkeys(row[0] for row in rows if row[0] not in (NARRATOR, PAUSE, UNASSIGNED)))
    rows = [[*row[:3], 0] for row in rows]
    from voice_rules import reconcile
    from spoken_text import reconcile as reconcile_spoken
    chapter.save_script(reconcile_spoken(chapter.script(), reconcile(chapter.script(), {"source_hash": project.text_hash(text), "rows": rows, "report": report,
                         "speakers": speakers, "added": added, "ai": bool(use_ai and settings["multi_voice"]),
                         "analyzed": datetime.now().isoformat(timespec="seconds")})))
    chapter.error_file.unlink(missing_ok=True)
    (chapter.work / "analysis-error.json").unlink(missing_ok=True)
    return rows, report, added


def manual_script(chapter, entries):
    """A text-preserving draft, available even when the model is unavailable. This never writes files."""
    text = chapter.text()
    rows = prepare_script(text, aliases=glossary.alias_map(entries))
    return {"source_hash": project.text_hash(text), "rows": [[*row[:3], 0] for row in rows],
            "report": "Prepared without AI. Assign unresolved speakers manually; the source text is unchanged.",
            "speakers": list(dict.fromkeys(row[0] for row in rows if row[0] not in (NARRATOR, PAUSE, UNASSIGNED))),
            "added": [], "ai": False, "analyzed": datetime.now().isoformat(timespec="seconds")}


def status(chapter, settings, glossary_rows):
    """(state, details) for one chapter, computed from the files on disk."""
    details = {}
    try:
        text = chapter.text()
    except (OSError, ValueError) as error:
        return "error", {"error": str(error)}
    details["chars"] = len(text)
    details["estimated_seconds"] = round(len(text) / CHARS_PER_SECOND)
    script = chapter.script()
    details["narrator_fallback"] = bool(settings["multi_voice"] and script and project.unclear_count(script)
                                        and settings.get("unclear_policy") == "narrator")
    details["text_ready"] = bool(script and script["source_hash"] == project.text_hash(text)
                                 and (not settings["multi_voice"] or not project.unclear_count(script)
                                      or details["narrator_fallback"]))
    if script is not None:
        details["unclear"] = project.unclear_count(script)
    if chapter.error_file.exists():
        details["error"] = chapter.error_file.read_text(encoding="utf-8")
        if details["error"].startswith("analysis:"):
            details["text_ready"] = False
            details["analysis_problem"] = analysis_problem(chapter, text)
    meta = project._read_json(chapter.audio_meta, None)
    if meta:
        details["seconds"] = meta["seconds"]
        details["flagged"] = len(meta.get("flagged_lines", []))
    if "analysis_problem" in details:
        return "error", details
    if settings["multi_voice"] and script is None:
        return ("error" if "error" in details else "new"), details
    try:
        _, _, keys = chapter_plan(chapter, settings, glossary_rows, text)
    except NotReady as reason:
        details["reason"] = str(reason)
        if script is not None and script["source_hash"] != project.text_hash(text):
            return "modified", details
        return ("error" if "error" in details else "needs_review"), details
    except ValueError as error:
        details["reason"] = str(error)
        return "error", details
    identity_matches = not script or all(p.get('line', -1) < 0 or
        p['line'] < len(script['rows']) and script['rows'][p['line']][0] == p.get('role') for p in (meta or {}).get('passages', []))
    if meta and meta["keys"] == keys and identity_matches and chapter.audio_file.exists():
        extension = project.export_extension(settings)
        exported = chapter.export_path(extension)
        if exported.exists() and exported.stat().st_mtime >= chapter.audio_file.stat().st_mtime:
            details["export"] = str(exported)
            return "exported", details
        return "generated", details
    done = sum(1 for key in keys if passage_file(key).exists())
    details["progress"] = round(done / len(keys), 3) if keys else 0
    details["remaining_seconds"] = round(details["estimated_seconds"] * (1 - details["progress"]))
    if "error" in details:
        return "error", details
    if meta:
        details["changed"] = sum(1 for key in keys if key not in set(meta["keys"]))
        return "outdated", details
    return ("partial" if done else "analyzed"), details


def analysis_problem(chapter, text):
    """Explain old and new errors without retaining model output or story text in diagnostics."""
    diagnostic = project._read_json(chapter.work / "analysis-error.json", {})
    if diagnostic.get("source_hash") != project.text_hash(text):
        diagnostic = {}
    return {**diagnostic,
            "explanation": "The speaker analysis failed. No replacement script was saved; existing assignments are kept.",
            "repair": "Reanalyze this chapter in smaller batches of three dialogue lines. "
                      "This uses the local model and can take longer. Uncertain speakers still need your review.",
            "manual": "Prepare the text without AI, then assign unresolved speakers in the chapter editor."}


def readiness(state, details):
    return {"can_generate": bool(details.get("text_ready") and not details.get("reason")
                                 and state != "needs_review"),
            "can_export": bool(details.get("text_ready") and state in ("generated", "exported"))}


def require_ready(chapters, settings, step):
    """All chapters in this batch must meet the previous stage; never silently process a subset."""
    rows = glossary.load()
    blocked = []
    key = "can_generate" if step == "render" else "can_export"
    for chapter in chapters:
        state, details = status(chapter, settings, rows)
        if not readiness(state, details)[key]:
            blocked.append(f"{chapter.stem}: {details.get('error') or details.get('reason') or STATES[state]}")
    if blocked:
        requirement = "Finish text analysis and resolve every unassigned speaker" if step == "render" else "Generate current audio"
        raise ValueError(f"{requirement} for all chapters in this batch before continuing.\n" + "\n".join(blocked))
