"""The emotion of each line, kept beside the speaker assignments and never in the spoken text.

  script["delivery"] = {"lines": [{"row", "text_hash", "emotion", "source"}]}

`source` is "ai" for Gemma's proposal (shown for review, like a context speaker) or "manual" for the author's
choice. A manual choice wins over Gemma and survives a new analysis; a row without an entry is neutral.
"""
from copy import deepcopy
from dataclasses import replace
from difflib import SequenceMatcher

import emotions
import project
import project_package as package
import project_transfer as transfer
from emotions import NEUTRAL
from voice_rules import digest

SOURCES = ("ai", "manual")


def validate(script):
    data = script.get("delivery", {})
    if not isinstance(data, dict) or set(data) - {"lines"} or not isinstance(data.get("lines", []), list):
        raise ValueError("Invalid line emotions.")
    seen = set()
    for entry in data.get("lines", []):
        if (not isinstance(entry, dict) or set(entry) != {"row", "text_hash", "emotion", "source"}
                or type(entry["row"]) is not int or not 0 <= entry["row"] < len(script["rows"])
                or entry["row"] in seen or entry["emotion"] not in emotions.EMOTIONS or entry["source"] not in SOURCES):
            raise ValueError("Invalid or duplicate line emotion.")
        seen.add(entry["row"])
        if entry["text_hash"] != digest(script["rows"][entry["row"]][1]):
            raise ValueError("A line emotion no longer matches its line. Review the chapter.")
    return data


def entries(script):
    """row -> entry, for the rows that carry an emotion."""
    return {entry["row"]: entry for entry in validate(script or {"rows": []}).get("lines", [])}


def effective(script):
    """row -> emotion key, neutral rows left out."""
    return {row: entry["emotion"] for row, entry in entries(script).items() if entry["emotion"] != NEUTRAL}


def apply_lines(lines, script):
    chosen = effective(script)
    return [replace(line, emotion=chosen.get(line.row, "")) for line in lines]


def proposals(rows, proposed):
    """Gemma's emotions ({row: key}) as entries; neutral needs no entry."""
    return {"lines": [{"row": row, "text_hash": digest(rows[row][1]), "emotion": key, "source": "ai"}
                      for row, key in sorted(proposed.items()) if key != NEUTRAL and 0 <= row < len(rows)]}


def carry(old, rows, keep=SOURCES):
    """The entries of script `old` whose line text is still present in `rows`, at the new row numbers."""
    previous = entries(old) if old else {}
    if not previous:
        return []
    before = [digest(row[1]) for row in old["rows"]]
    after = [digest(row[1]) for row in rows]
    kept = []
    for block in SequenceMatcher(None, before, after, autojunk=False).get_matching_blocks():
        for offset in range(block.size):
            entry = previous.get(block.a + offset)
            if entry and entry["source"] in keep:
                kept.append({**entry, "row": block.b + offset})
    return kept


def reconcile(old, new):
    """After a new analysis: Gemma's new proposals, overridden by the author's earlier manual choices."""
    try:
        manual = {entry["row"]: entry for entry in carry(old, new["rows"], keep=("manual",))}
    except ValueError:
        manual = {}  # stale entries of an earlier script are not carried
    lines = {entry["row"]: entry for entry in new.get("delivery", {}).get("lines", [])}
    lines.update(manual)
    if lines:
        new["delivery"] = {"lines": [lines[row] for row in sorted(lines)]}
    else:
        new.pop("delivery", None)
    return new


def plan(request):
    """Set the author's emotion for one line. Returns the writes and a report."""
    if not isinstance(request, dict) or set(request) - {"volume", "stem", "row", "emotion", "source_hash"}:
        raise ValueError("Invalid line emotion request.")
    chapter = project.get_chapter(request["volume"], request["stem"])
    script = chapter.script()
    if (not script or script["source_hash"] != project.text_hash(chapter.text())
            or request.get("source_hash") != script["source_hash"]):
        raise ValueError("Analyze the current chapter text and refresh before choosing line emotions.")
    row = request.get("row")
    if type(row) is not int or not 0 <= row < len(script["rows"]) or script["rows"][row][0] == "Scene break":
        raise ValueError("Choose a text line, not a scene break.")
    emotion = emotions.check(request.get("emotion"))
    current = entries(script)
    after = deepcopy(script)
    current[row] = {"row": row, "text_hash": digest(script["rows"][row][1]), "emotion": emotion, "source": "manual"}
    after["delivery"] = {"lines": [current[key] for key in sorted(current)]}
    name = chapter.script_file.relative_to(project.ROOT).as_posix()
    writes = {name: package.encoded(after)} if after != script else {}
    return writes, {"row": row, "emotion": emotion, "changed": bool(writes)}


def save(request):
    writes, report = plan(request)
    if writes:
        transfer.transact(writes)
    return report
