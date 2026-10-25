"""Audiobook studio: a local web app (FastAPI + the page in web/) around the Qwen3-TTS pipeline."""
import os
import sys
import threading
import webbrowser
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import quote, urlsplit

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

import export
import fixed_voices
import glossary
import character_registry
import model_profile
import pipeline
import presets
import project
import project_transfer
from project_api import create_router
from project_access import ProjectAccess
import video_jobs
import voice_check
import voice_rules
import spoken_text
from voice_rules_api import create_router as voice_rules_router
from conversion import CHARACTER_SAMPLE, PREVIEW_TEXT, chapter_plan, narrator_voice, preview_voice, speakable
from dialogue import INNER_VOICE, NARRATOR, PAUSE, SIMPLE_TAG_RE, UNASSIGNED, Voice, read_cast
from voices import (AUTHOR_DELIVERY, BASE_CLONE, CHARACTER_PROFILES, CUSTOM_SPEAKERS, MODEL_NAMES, PROFILES,
                    describe, voice_parameters)
from worker import Worker

WEB = project.PROGRAM / "web"
PORT = 7863
app = FastAPI(title="AudioBook Studio")
project_transfer.recover()
worker = Worker()
project_access = ProjectAccess()
app.include_router(create_router(worker, lambda:project_access))
app.include_router(voice_rules_router(worker))
from character_registry_api import create_router as registry_router
app.include_router(registry_router(worker))


@app.exception_handler(ValueError)
async def value_error(_, error):
    return JSONResponse({"error": str(error)}, status_code=400)


@app.exception_handler(RuntimeError)
async def runtime_error(_, error):
    return JSONResponse({"error": str(error)}, status_code=500)


# Only this computer's own page may use the server. Another host name means DNS rebinding (a web page that
# re-pointed its domain at 127.0.0.1); another Origin means a different web page sending requests through the
# browser. Ports are not compared, so a test run on another port still works.
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _is_local(authority):
    """True for a Host/Origin authority naming this computer, such as 127.0.0.1:7863 or [::1]:7863."""
    if not authority or "@" in authority or any(char.isspace() for char in authority):
        return False
    try:
        return urlsplit("//" + authority).hostname in LOCAL_HOSTS
    except ValueError:
        return False


@app.middleware("http")
async def own_page_only(request, call_next):
    origin = request.headers.get("origin")
    foreign_origin = origin is not None and not (origin.startswith("http://") and _is_local(origin[7:]))
    if foreign_origin or not _is_local(request.headers.get("host", "")):
        return JSONResponse({"error": "Request refused: only the AudioBook Studio page on this computer can use "
                                      "this server."}, status_code=403)
    return await call_next(request)


@app.middleware("http")
async def revalidate_page_files(request, call_next):
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        # The page files change with updates. Without this, the window may keep showing a cached older copy;
        # the ETag keeps the check cheap.
        response.headers.setdefault("Cache-Control", "no-cache")
    return response


def _url(path):
    return "/api/audio?path=" + quote(project.media_token(path))


@app.middleware("http")
async def project_consistency(request, call_next):
    # Project routes acquire their gate after native dialogs. Slow auditions are concurrent readers;
    # only settings/cast/script/volume changes and import/Undo need exclusive access.
    path = request.url.path
    if (path.startswith('/api/') and not path.startswith('/api/project')
            and path not in ('/api/status','/api/stop','/api/audio','/api/pick-folder','/api/video/codecs')):
        write = request.method in ('PUT','DELETE') or path in (
            '/api/volumes','/api/characters/new','/api/voices/fix','/api/voices/unfix',
            '/api/presets/apply','/api/chapter/split')
        async with project_access.hold(write=write):
            return await call_next(request)
    return await call_next(request)


# -- overview, volumes, chapters ---------------------------------------------------------------------
def _chapter_info(chapter, settings, rows):
    state, details = pipeline.status(chapter, settings, rows)
    info = {"stem": chapter.stem, "number": chapter.number, "title": chapter.title, "state": state,
            "label": pipeline.STATES[state], **details, **pipeline.readiness(state, details)}
    if chapter.audio_file.exists():
        info["audio"] = _url(chapter.audio_file)
    try:
        info["video"] = video_jobs.video_status(chapter, settings, state in ("generated", "exported"))
    except (ValueError, OSError) as error:
        info["video"] = {"state": "outdated", "label": "Video outdated", "error": str(error)}
    if "file" in info["video"]:
        info["video"]["url"] = _url(info["video"].pop("file"))
    return info


@app.get("/api/overview")
def overview():
    settings = project.load_settings()
    rows = glossary.load()
    result = []
    for volume in project.volumes():
        entry = {"name": volume["name"], "source": volume["source"]}
        try:
            chapters = [_chapter_info(chapter, settings, rows) for chapter in project.chapters(volume["name"])]
        except ValueError as error:
            entry["error"] = str(error)
            chapters = []
        entry["chapters"] = len(chapters)
        entry["counts"] = {state: sum(1 for c in chapters if c["state"] == state) for state in pipeline.STATES}
        entry["estimated_seconds"] = sum(c["estimated_seconds"] for c in chapters if "estimated_seconds" in c)
        entry["generated_seconds"] = sum(c.get("seconds", 0) for c in chapters if c["state"] in ("generated",
                                                                                                 "exported"))
        result.append(entry)
    return {"volumes": result, "characters": len(rows), "ffmpeg": export.available(), "status": worker.status(),
            "render_factor": pipeline.render_factor()}


@app.post("/api/volumes")
def add_volume(data: dict = Body(...)):
    with worker.idle_guard("adding a volume"):
        return {"name": project.add_volume(data.get("name"), data["source"])}


@app.delete("/api/volumes/{name}")
def remove_volume(name: str):
    with worker.idle_guard("removing a volume"):
        project.get_volume(name)
        project.remove_volume(name)
    return {"ok": True}


@app.put("/api/volumes/{name}")
def edit_volume(name: str, data: dict = Body(...)):
    with worker.idle_guard("editing a volume"):
        return {"name":project.update_volume(name, data["source"])}


@app.post("/api/pick-folder")
def pick_folder():
    """A native Windows folder dialog, so nobody has to type a path."""
    result = {}

    def ask():
        import tkinter
        from tkinter import filedialog
        root = tkinter.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        result["path"] = filedialog.askdirectory(title="Choose the folder containing this volume's chapters", parent=root)
        root.destroy()

    thread = threading.Thread(target=ask)
    thread.start()
    thread.join()
    return {"path": str(Path(result["path"])) if result.get("path") else ""}


@app.get("/api/volumes/{name}")
def volume(name: str):
    settings = project.load_settings()
    rows = glossary.load()
    return {"volume": project.get_volume(name), "render_factor": pipeline.render_factor(),
            "video_factor": video_jobs.measurement(settings), "video_enabled": settings["video"]["enabled"],
            "chapters": [_chapter_info(chapter, settings, rows) for chapter in project.chapters(name)]}


@app.post("/api/run")
def run(data: dict = Body(...)):
    steps = data.get("steps", ["analyze", "render", "export"])
    if not isinstance(steps, list) or not steps or set(steps) - {"analyze", "render", "export", "volume", "video"}:
        raise ValueError("Unknown queue steps.")
    chapters = project.chapters(data["volume"])
    stems = data.get("stems") or [chapter.stem for chapter in chapters]
    if not isinstance(stems, list) or not all(isinstance(stem, str) for stem in stems) or len(set(stems)) != len(stems):
        raise ValueError("Select a valid chapter batch.")
    selected = [chapter for chapter in chapters if chapter.stem in stems]
    if not selected or len(selected) != len(stems):
        raise ValueError("The requested chapters no longer exist. Refresh the volume.")
    if "render" in steps and "analyze" not in steps:
        pipeline.require_ready(selected, project.load_settings(), "render")
    if any(step in steps for step in ("export", "video", "volume")) and not {"analyze", "render"}.intersection(steps):
        pipeline.require_ready(chapters if "volume" in steps else selected, project.load_settings(), "export")
    worker.submit(data["volume"], stems, steps, bool(data.get("force")), bool(data.get("automatic")))
    return worker.status()


@app.post("/api/stop")
def stop():
    worker.stop()
    return worker.status()


@app.get("/api/status")
def status():
    return worker.status()


@app.get("/api/chapter")
def chapter(volume: str, stem: str):
    settings = project.load_settings()
    rows = glossary.load()
    item = project.get_chapter(volume, stem)
    info = _chapter_info(item, settings, rows)
    script = item.script()
    manual_draft = script is None or script["source_hash"] != project.text_hash(item.text())
    if manual_draft:
        script = pipeline.manual_script(item, rows)
    meta = {} if manual_draft else project._read_json(item.audio_meta, None) or {}
    takes = {}
    for passage in meta.get("passages", []):
        takes.setdefault(passage["line"], []).append(passage)
    try:  # rows the current plan does not read (plain speech tags of fixed voices)
        chunks, _, _ = chapter_plan(item, settings, rows)
        spoken = {chunk.line for chunk in chunks}
    except ValueError:
        spoken = None
    registry_document = character_registry.document()
    registry = character_registry.organization(registry_document)
    lines = []
    try:
        reading = voice_rules.effective(script, rows)
        voice_error = ""
    except ValueError as error:
        reading, voice_error = {}, str(error)
    try:
        spoken_edits=spoken_text.effective(script)
        spoken_error=""
    except ValueError as error:
        spoken_edits={}; spoken_error=str(error)
    if script:
        scenes = character_registry.scene_indices(script["rows"])
        context_names = {context["id"]: context["name"] for context in registry["contexts"]}
        scene_contexts = {number: character_registry.contexts_for(volume, stem, number,
                                                                 registry_document, script["source_hash"])
                          for number in set(scenes)}
        for index, row in enumerate(script["rows"]):
            bound = scene_contexts[scenes[index]]
            line = {"speaker": row[0], "read_as":reading.get(index,row[0]), "text": row[1], "spoken_text":spoken_edits.get(index,row[1]), "joined": bool(row[2]),
                    "variant": int(row[3]) if len(row) > 3 else 0,
                    "flagged": index in meta.get("flagged_lines", []),
                    "scene": scenes[index],
                    "basis": (script.get("attribution") or {}).get(str(index), {}).get("basis",
                             "explicit" if row[0] != UNASSIGNED else "unclear"),
                    "context_ids": bound,
                    "contexts": [context_names[key] for key in bound],
                    "omitted": spoken is not None and row[0] == NARRATOR and index not in spoken
                               and SIMPLE_TAG_RE.match(str(row[1])) is not None}
            if index in takes:
                line["start"] = takes[index][0]["start"]
                line["seconds"] = round(sum(take["seconds"] for take in takes[index]), 2)
            lines.append(line)
    used = sorted({row[0] for row in script["rows"]}) if script else []
    blockers = []
    for name in used:
        metadata = registry["characters"].get(name)
        if not metadata:
            continue
        if metadata["status"] == "needs_review" or (metadata["status"] == "provisional"
                                                    and not registry["allow_provisional"]):
            blockers.append({"name": name, "label": metadata["label"], "status": metadata["status"]})
    return {"chapter": info, "lines": lines, "report": script["report"],
            "manual_draft": manual_draft, "source_hash": script["source_hash"],
            "voice_rules":script.get("voice_rules",{}), "voice_error":voice_error,
            "spoken_error":spoken_error, "spoken_conflicts":script.get("spoken_text",{}).get("conflicts",[]),
            "blockers": blockers, "unassigned": sum(1 for line in lines if line["speaker"] == UNASSIGNED),
            "contexts": [{"id": context["id"], "name": context["name"]} for context in registry["contexts"]
                         if context["volume"] == character_registry.volume_key(volume)],
            "speakers": [NARRATOR, *[row[0] for row in rows]]}


def _check_rows(item, rows=None, source_hash=None):
    script = item.script()
    if script is None or script["source_hash"] != project.text_hash(item.text()):
        script = pipeline.manual_script(item, glossary.load())
        if source_hash != script["source_hash"]:
            raise ValueError("The chapter text has changed. Refresh the manual editor before saving.")
    if rows is not None:
        original = " ".join(" ".join(str(row[1]).split()) for row in script["rows"])
        edited = " ".join(" ".join(str(row[1]).split()) for row in rows)
        if original != edited:
            raise ValueError("The line text has changed. Only speakers and paragraph boundaries can be edited here.")
    return script


def _carry_attribution(original, rows):
    """Analysis confidence notes by new row index. A note stays only on a row whose speaker and text are
    unchanged, so rows the author edited are settled while the others keep their review marks."""
    notes = original.get("attribution") or {}
    if not notes:
        return {}
    before = [(row[0], row[1]) for row in original["rows"]]
    after = [(row[0], row[1]) for row in rows]
    kept = {}
    for block in SequenceMatcher(None, before, after, autojunk=False).get_matching_blocks():
        for offset in range(block.size):
            note = notes.get(str(block.a + offset))
            if note:
                kept[str(block.b + offset)] = note
    return kept


def _save_rows(item, script, rows):
    clean = []
    for row in rows:
        speaker = str(row[0]).strip()
        if not speaker:
            raise ValueError("Every line needs a speaker.")
        clean.append([speaker, str(row[1]), bool(row[2]) if len(row) > 2 else False,
                      int(row[3]) if len(row) > 3 else 0])
    entries = glossary.load()
    new = [name for name in dict.fromkeys(row[0] for row in clean)
           if name not in (NARRATOR, PAUSE, UNASSIGNED) and name not in {entry[0] for entry in entries}]
    for name in new:
        entries.append(glossary.propose(name, "unknown", entries))
    added = glossary.add_missing(entries)
    from copy import deepcopy
    original_script = deepcopy(item.script() or script)
    script["rows"] = clean
    script = voice_rules.reconcile(original_script, script)
    script = spoken_text.reconcile(original_script, script)
    notes = _carry_attribution(original_script, clean)  # a line the author changed or split is settled
    if notes:
        script["attribution"] = notes
    else:
        script.pop("attribution", None)
    script["speakers"] = list(dict.fromkeys(row[0] for row in clean if row[0] not in (NARRATOR, PAUSE, UNASSIGNED)))
    item.save_script(script)
    if item.error_file.exists() and item.error_file.read_text(encoding="utf-8").startswith("analysis:"):
        item.error_file.unlink()
        (item.work / "analysis-error.json").unlink(missing_ok=True)
    return added


@app.put("/api/chapter/rows")
def save_rows(data: dict = Body(...)):
    with worker.idle_guard("saving speaker assignments"):
        item = project.get_chapter(data["volume"], data["stem"])
        script = _check_rows(item, data["rows"], data.get("source_hash"))
        return {"added": _save_rows(item, script, data["rows"])}


@app.post("/api/chapter/split")
def split_row(data: dict = Body(...)):
    with worker.idle_guard("saving speaker assignments"):
        item = project.get_chapter(data["volume"], data["stem"])
        script = _check_rows(item, source_hash=data.get("source_hash"))
        rows = [list(row) for row in script["rows"]]
        index, phrase = int(data["index"]), str(data["phrase"]).strip()
        text = str(rows[index][1])
        position = text.find(phrase) if phrase else -1
        if position <= 0:
            raise ValueError("Enter the exact words where the new segment begins, after the start of the line.")
        rows[index][1] = text[:position].rstrip()
        rows.insert(index + 1, [data.get("speaker") or NARRATOR, text[position:].strip(), True, 0])
        return {"added": _save_rows(item, script, rows)}


@app.post("/api/chapter/spoken-text/preview")
def preview_spoken_text(data: dict = Body(...)):
    return spoken_text.plan(data)[1]


@app.put("/api/chapter/spoken-text")
def save_spoken_text(data: dict = Body(...)):
    with worker.idle_guard("saving spoken text"):
        return spoken_text.save(data["request"], data["plan_id"])


@app.post("/api/chapter/analyze")
def analyze_one(data: dict = Body(...)):
    project.get_chapter(data["volume"], data["stem"])
    worker.submit(data["volume"], [data["stem"]], ["analyze"], True)
    return worker.status()


@app.post("/api/chapter/repair")
def repair_analysis(data: dict = Body(...)):
    item = project.get_chapter(data["volume"], data["stem"])
    if data.get("mode") != "small_batches":
        raise ValueError("Choose smaller-batch analysis. Manual assignments are saved in the chapter editor.")
    if not item.error_file.exists() or not item.error_file.read_text(encoding="utf-8").startswith("analysis:"):
        raise ValueError("This chapter has no analysis error. Refresh its status.")
    worker.submit(data["volume"], [data["stem"]], ["analyze"], True, analysis_mode=data["mode"])
    return worker.status()


# -- characters ---------------------------------------------------------------------------------------
FIELDS = ["name", "aliases", "gender", "note", "model", "custom", "design", "seed"]


def _fixed_info(role):
    entry = fixed_voices.get(role)
    if not entry:
        return None
    return {**entry, "url": _url(fixed_voices.FOLDER / entry["file"])}


@app.post("/api/voices/fix")
def fix_voice(data: dict = Body(...)):
    """Keep a probe the author approved as the fixed voice of the narrator or a character."""
    take = (project.ROOT / str(data["path"])).resolve()
    if not take.is_relative_to(project.PROBES.resolve()) or not take.is_file():
        raise ValueError("This preview is no longer available. Generate another one.")
    role = str(data["role"]).strip()
    if role != NARRATOR and role not in {row[0] for row in glossary.load()}:
        raise ValueError(f"{role} is not in the character glossary.")
    entry = fixed_voices.fix(role, take, speakable(str(data["text"])[:600]), data.get("origin", {}))
    return {"fixed": _fixed_info(role), "seconds": entry["seconds"]}


def _fixed_paths():
    return {role: fixed_voices.FOLDER / entry["file"] for role, entry in fixed_voices.load().items()}


@app.get("/api/voices/similarity")
def voice_similarity():
    """How alike the fixed voices are (centered fingerprints): pairs that listeners may confuse."""
    if not voice_check.available():
        return {"pairs": [], "available": False}
    paths = _fixed_paths()
    names = sorted(paths)
    pairs = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            score = voice_check.closeness(paths[a], paths[b])
            if score is not None:
                pairs.append({"a": a, "b": b, "score": round(score, 2)})
    pairs.sort(key=lambda pair: -pair["score"])
    return {"pairs": pairs, "available": True, "confusable": voice_check.CONFUSABLE}


@app.post("/api/characters/candidates")
def character_candidates(data: dict = Body(...)):
    """Several new takes from the character's description, ranked by how different they sound from the other
    fixed voices; the author listens and fixes one."""
    settings = project.load_settings()
    item = data["character"]
    row = [item.get(field, "") for field in FIELDS]
    recipe = read_cast([row], MODEL_NAMES[settings["narrator"]["mode"]], narrator_voice(settings), {row[0]},
                       use_fixed=False)[row[0]]
    text = str(data.get("text") or "").strip() or fixed_voices.sample_for(row[0]) or CHARACTER_SAMPLE
    others = {name: path for name, path in _fixed_paths().items() if name != row[0]}
    takes = []
    for step in range(int(data.get("count", 6))):
        seed = int(row[7]) + 7919 * step
        voice = Voice(recipe.speaker, recipe.description, recipe.instructions, seed, recipe.mode)
        target = preview_voice(voice, text, settings["narrator"]["temperature"])
        if not voice_check.pitch_fits(target, row[2]):
            continue  # e.g. a "husky alto" generated as a man's voice
        scores = [(voice_check.closeness(target, path), name) for name, path in others.items()]
        scores = [(score, name) for score, name in scores if score is not None]
        closest = max(scores) if scores else (None, "")
        takes.append({"seed": seed, "url": _url(target), "path": str(target.relative_to(project.ROOT)).replace("\\", "/"),
                      "closest": closest[1], "score": None if closest[0] is None else round(closest[0], 2)})
    takes.sort(key=lambda take: take["score"] if take["score"] is not None else 9)
    current = None
    if fixed_voices.get(row[0]) and others:
        mine = fixed_voices.FOLDER / fixed_voices.get(row[0])["file"]
        current = max((round(voice_check.closeness(mine, path), 2), name) for name, path in others.items())
    return {"takes": takes[:3], "text": text, "current": current}


@app.get("/api/presets")
def voice_presets():
    """Ready-made voices to start from; listening uses the preset's own reference take."""
    keys = ("id", "name", "kind", "gender", "summary", "description", "seed", "temperature", "seconds", "text")
    return {"presets": [{**{key: preset[key] for key in keys}, "url": _url(presets.FOLDER / preset["file"])}
                        for preset in presets.load()]}


@app.post("/api/presets/apply")
def apply_preset(data: dict = Body(...)):
    role = str(data["role"]).strip()
    entry = presets.apply(str(data["id"]), role)
    return {"fixed": _fixed_info(role), "seconds": entry["seconds"]}


@app.post("/api/voices/unfix")
def unfix_voice(data: dict = Body(...)):
    fixed_voices.unfix(str(data["role"]))
    return {"ok": True}


@app.get("/api/characters")
def characters():
    settings = project.load_settings()
    rows = glossary.load()
    return {"default_sample": CHARACTER_SAMPLE, "characters": [{**dict(zip(FIELDS, row)), "read_as":voice_rules.global_rules().get(row[0],row[0]), "fixed": _fixed_info(row[0]),
                            "sample": fixed_voices.sample_for(row[0])} for row in rows],
            "duplicates": glossary.duplicate_voices(rows, settings["narrator"]["mode"]),
            "profiles": {"narrator": list(PROFILES),
                         **{gender: list(profiles) for gender, profiles in CHARACTER_PROFILES.items()}},
            "profile_texts": {**PROFILES, **{name: text for profiles in CHARACTER_PROFILES.values()
                                             for name, text in profiles.items()}},
            "custom_speakers": CUSTOM_SPEAKERS, "inner_voice": INNER_VOICE}


@app.put("/api/characters")
def save_characters(data: dict = Body(...)):
    rows = glossary.save([[item.get(field, "") for field in FIELDS] for item in data["characters"]])
    for item in data["characters"]:
        if str(item.get("sample", "")).strip():
            fixed_voices.set_sample(str(item["name"]), " ".join(str(item["sample"]).split()))
    for role in set(fixed_voices.load()) - {row[0] for row in rows} - {NARRATOR}:
        fixed_voices.unfix(role)  # a deleted character takes its fixed voice with it
    return {"count": len(rows)}


@app.post("/api/characters/new")
def new_character(data: dict = Body(...)):
    name = str(data.get("name", "")).strip()
    if not name or name in (NARRATOR, UNASSIGNED, PAUSE):
        raise ValueError("Enter a character name.")
    gender = {"male": "male", "female": "female"}.get(data.get("gender"), "unknown")
    rows = glossary.load()
    if name in {row[0] for row in rows}:
        raise ValueError(f"{name} is already in the character glossary.")
    glossary.add_missing([glossary.propose(name, gender, rows)])
    return characters()


@app.post("/api/characters/preview")
def character_preview(data: dict = Body(...)):
    settings = project.load_settings()
    item = data["character"]
    row = [item.get(field, "") for field in FIELDS]
    voices = read_cast([row], MODEL_NAMES[settings["narrator"]["mode"]], narrator_voice(settings), {row[0]})
    text = str(data.get("text") or "").strip() or fixed_voices.sample_for(row[0]) or CHARACTER_SAMPLE
    target = preview_voice(voices[row[0]], text, settings["narrator"]["temperature"])
    return {"url": _url(target), "path": str(target.relative_to(project.ROOT)).replace("\\", "/"), "text": text,
            "fixed": voices[row[0]].mode == BASE_CLONE}


# -- narrator and settings ----------------------------------------------------------------------------
@app.get("/api/video/codecs")
def video_codecs():
    from video import codec_capabilities
    return {"codecs": codec_capabilities()}


@app.get("/api/settings")
def get_settings():
    return {"settings": project.load_settings(), "formats": export.formats(), "ffmpeg": export.available(),
            "profiles": PROFILES, "custom_speakers": CUSTOM_SPEAKERS, "author_delivery": AUTHOR_DELIVERY,
            "preview_text": fixed_voices.sample_for(NARRATOR) or PREVIEW_TEXT, "fixed": _fixed_info(NARRATOR),
            "model_profile": {key: model_profile.CURRENT[key] for key in ("name", "label", "gemma")},
            "video_factor": video_jobs.measurement(project.load_settings())}


@app.put("/api/settings")
def put_settings(data: dict = Body(...)):
    settings = data["settings"]
    narrator = settings["narrator"]
    voice_parameters(MODEL_NAMES[narrator["mode"]], narrator["speaker"],
                     narrator["description"] or describe(narrator["profile"]), narrator["instructions"])
    return {"settings": project.save_settings(settings)}


@app.post("/api/narrator/preview")
def narrator_preview(data: dict = Body(...)):
    """The same text in up to three variants, so takes can be compared side by side."""
    narrator = data["narrator"]
    text = str(data.get("text") or "").strip() or PREVIEW_TEXT
    if data.get("fixed"):  # the fixed voice reading the probe text, to hear how the book will sound
        voice = narrator_voice({"narrator": narrator})
        target = preview_voice(voice, text, float(narrator["temperature"]))
        return {"takes": [{"seed": voice.seed, "url": _url(target), "fixed": True}]}
    mode = MODEL_NAMES[narrator["mode"]]
    description = narrator["description"] or describe(narrator["profile"])
    voice_parameters(mode, narrator["speaker"], description, narrator["instructions"])
    urls = []
    for seed in data.get("seeds") or [narrator["seed"]]:
        voice = Voice(narrator["speaker"], description, narrator["instructions"], int(seed), mode)
        target = preview_voice(voice, text, float(narrator["temperature"]))
        urls.append({"seed": int(seed), "url": _url(target),
                     "path": str(target.relative_to(project.ROOT)).replace("\\", "/")})
    return {"takes": urls, "text": text}


# -- files ----------------------------------------------------------------------------------------------
@app.post("/api/video/youtube")
def youtube_list(data: dict = Body(...)):
    target = video_jobs.youtube_chapters(data["volume"], data.get("stems"), project.load_settings())
    return {"url": _url(target), "file": target.name}


@app.post("/api/video/show")
def show_video(data: dict = Body(...)):
    import subprocess
    chapter = project.get_chapter(data["volume"], data["stem"])
    target = video_jobs.video_path(chapter)
    if not target.is_file():
        raise ValueError("No video exists for this chapter.")
    subprocess.Popen(["explorer.exe", "/select,", str(target)], creationflags=subprocess.CREATE_NO_WINDOW)
    return {"ok": True}


@app.get("/api/audio")
def audio(path: str):
    try:
        target = project.media_path(path)
    except ValueError:
        raise HTTPException(404)
    if not target.is_file():
        raise HTTPException(404)
    return FileResponse(target)


@app.post("/api/open")
def open_folder(data: dict = Body(...)):
    """Show a folder in Windows Explorer."""
    what = data.get("what")
    if what == "export":
        folder = project.EXPORT / project.safe_name(data["volume"]) if data.get("volume") else project.EXPORT
    elif what == "source":
        folder = Path(project.get_volume(data["volume"])["source"])
    elif what == "chapter":
        folder = project.get_chapter(data["volume"], data["stem"]).work
    else:
        raise ValueError("Folder unknown.")
    folder.mkdir(parents=True, exist_ok=True)
    os.startfile(folder)
    return {"ok": True}


app.mount("/", StaticFiles(directory=WEB, html=True), name="web")


if __name__ == "__main__":
    character_registry.migrate()
    if "--no-browser" not in sys.argv:
        threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{PORT}/")).start()
    print(f"AudioBook Studio: http://127.0.0.1:{PORT}/  (close this window to stop)")
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
