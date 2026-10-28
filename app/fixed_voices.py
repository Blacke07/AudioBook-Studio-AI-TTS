"""Voices fixed from an approved take. The Base model clones the take (audio + its exact text) for every
passage, so the narrator or a character keeps one identity across the whole book.

  voices/registry.json             role -> {"id", "file", "text", "seconds", "origin", "date", "takes"?}
  voices/<role>-<hash>.wav     the approved take, copied (the probe cache may be cleaned)

The main take is the neutral delivery. `takes` (optional) maps an emotion to another approved take of the same
role, {"id", "file", "text", "seconds", "origin", "date"}: Base clones how a take is spoken, so an angry line
needs an angry reference. A role without that take falls back to the neutral one.
"""
from datetime import datetime
import hashlib
import json
import re
import shutil
from threading import RLock

import soundfile as sf

from emotions import EMOTIONS, NEUTRAL, check as check_emotion
from project import ROOT, write_json

FOLDER = ROOT / "voices"
REGISTRY = FOLDER / "registry.json"
# Per role: the line the voice is auditioned and fixed on. It carries the personality (the clone copies how
# the take is spoken), so it is written in the character's own way of talking (author's voice sheets).
SAMPLES = FOLDER / "samples.json"
MIN_SECONDS = 4.0
_LOCK = RLock()


def load():
    if not REGISTRY.exists():
        return {}
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def get(role):
    return load().get(role)


def take(role, emotion=NEUTRAL):
    """The approved take of `role` for `emotion`; the neutral one is the role's main entry."""
    entry = get(role)
    if not entry or emotion == NEUTRAL:
        return entry
    return (entry.get("takes") or {}).get(emotion)


def files(entry):
    """Every WAV a registry entry refers to: the neutral take and the emotion takes."""
    return [entry["file"], *(item["file"] for item in (entry.get("takes") or {}).values())]


def fix(role, take, text, origin, emotion=NEUTRAL):
    """Keep `take` (a WAV) and its text as the reference voice of `role`. A neutral take replaces the voice
    and drops the emotion takes of the previous one (they belong to another identity); an emotion take needs
    the neutral voice first and is added beside it."""
    check_emotion(emotion)
    text = " ".join(str(text).split())
    if len(text) < 20:
        raise ValueError("The reference text is too short to fix a voice.")
    seconds = sf.info(take).duration
    if seconds < MIN_SECONDS:
        raise ValueError(f"The sample is {seconds:.1f} s. Use a reference of at least "
                         f"{MIN_SECONDS:.0f} seconds (ideally 10–20 s).")
    digest = hashlib.sha1(take.read_bytes() + text.encode("utf-8")).hexdigest()[:10]
    slug = re.sub(r"[^A-Za-z0-9]+", "-", role).strip("-").lower() or "voice"
    if emotion != NEUTRAL:
        slug += "-" + emotion
    with _LOCK:
        registry = load()
        if emotion != NEUTRAL and role not in registry:
            raise ValueError(f"Fix the neutral voice of {role} before approving a {emotion} take.")
        FOLDER.mkdir(exist_ok=True)
        target = FOLDER / f"{slug}-{digest}.wav"
        shutil.copyfile(take, target)
        entry = {"id": f"fix-{digest}", "file": target.name, "text": text, "seconds": round(seconds, 2),
                 "origin": origin, "date": datetime.now().isoformat(timespec="seconds")}
        if emotion == NEUTRAL:
            registry[role] = entry
        else:
            registry[role].setdefault("takes", {})[emotion] = entry
        write_json(REGISTRY, registry)
    return entry


def unfix(role, emotion=NEUTRAL):
    """Remove the voice of `role`, or only its take for `emotion`."""
    with _LOCK:
        registry = load()
        if emotion == NEUTRAL:
            registry.pop(role, None)
        elif role in registry:
            takes = registry[role].get("takes") or {}
            takes.pop(emotion, None)
            if takes:
                registry[role]["takes"] = takes
            else:
                registry[role].pop("takes", None)
        write_json(REGISTRY, registry)


def samples():
    """role -> {"sample": line, "serious": line, "real": [lines from the book], "emotions": {emotion: line}}."""
    return json.loads(SAMPLES.read_text(encoding="utf-8")) if SAMPLES.exists() else {}


def sample_for(role):
    return samples().get(role, {}).get("sample", "")


def set_sample(role, line):
    with _LOCK:
        data = samples()
        entry = data.setdefault(role, {})
        if entry.get("sample") != line:
            entry["sample"] = line
            write_json(SAMPLES, data)


def emotion_sample(role, emotion):
    """The line an emotion take of `role` is auditioned on: the author's own, or the vocabulary's."""
    return samples().get(role, {}).get("emotions", {}).get(emotion) or EMOTIONS[check_emotion(emotion)]["sample"]


def set_emotion_sample(role, emotion, line):
    """Keep the author's audition line for an emotion; the vocabulary's own line is not stored."""
    check_emotion(emotion)
    line = " ".join(str(line).split())
    with _LOCK:
        data = samples()
        before = data.get(role, {}).get("emotions", {})
        lines = dict(before)
        if line and line != EMOTIONS[emotion]["sample"]:
            lines[emotion] = line
        else:
            lines.pop(emotion, None)
        if lines == before:
            return
        entry = data.setdefault(role, {})
        if lines:
            entry["emotions"] = lines
        else:
            entry.pop("emotions", None)
        write_json(SAMPLES, data)


def reference(voice_id):
    """(WAV path, text) for a fixed voice id, neutral or emotion take, as the engine needs to register it."""
    for role in load().values():
        for entry in [role, *(role.get("takes") or {}).values()]:
            if entry["id"] == voice_id:
                return FOLDER / entry["file"], entry["text"]
    raise ValueError("The fixed voice is no longer available. Approve and fix another preview.")
