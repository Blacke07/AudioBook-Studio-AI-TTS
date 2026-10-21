"""What each chapter needs next, and the analysis step that produces its script."""
from datetime import datetime

import glossary
import model_profile
import project
from auto_speakers import attribute
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


def analyze(chapter, use_ai, settings, progress=lambda fraction, desc="": None, release=True):
    """Split the chapter, attribute its lines (Gemma when use_ai) and store the script."""
    text = chapter.text()
    entries = glossary.load()
    if use_ai and settings["multi_voice"]:
        with LOCK:
            close_engine()  # Gemma needs the GPU memory Qwen holds
            rows, _, entries, report, speakers = attribute(text, entries, settings["narrator"]["mode"],
                                                           progress, release)
    else:
        rows = prepare_script(text, aliases=glossary.alias_map(entries))
        speakers = list(dict.fromkeys(row[0] for row in rows if row[0] not in (NARRATOR, PAUSE, UNASSIGNED)))
        for name in speakers:
            if name not in {row[0] for row in entries}:
                entries.append(glossary.propose(name, "unknown", entries))
        report = "Split without AI. Dialogue without explicit speaker tags remains unassigned."
    added = glossary.add_missing(entries)
    rows = [[*row[:3], 0] for row in rows]
    chapter.save_script({"source_hash": project.text_hash(text), "rows": rows, "report": report,
                         "speakers": speakers, "added": added, "ai": bool(use_ai),
                         "analyzed": datetime.now().isoformat(timespec="seconds")})
    chapter.error_file.unlink(missing_ok=True)
    return rows, report, added


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
    if script is not None:
        details["unclear"] = project.unclear_count(script)
    if chapter.error_file.exists():
        details["error"] = chapter.error_file.read_text(encoding="utf-8")
    meta = project._read_json(chapter.audio_meta, None)
    if meta:
        details["seconds"] = meta["seconds"]
        details["flagged"] = len(meta.get("flagged_lines", []))
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
    if meta and meta["keys"] == keys and chapter.audio_file.exists():
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


def needs_analysis(state):
    return state in ("new", "modified") or state == "error"
