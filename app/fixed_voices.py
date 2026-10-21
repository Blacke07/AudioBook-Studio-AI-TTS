"""Voices fixed from an approved take. The Base model clones the take (audio + its exact text) for every
passage, so the narrator or a character keeps one identity across the whole book.

  voices/registry.json             role -> {"id", "file", "text", "seconds", "origin", "date"}
  voices/<role>-<hash>.wav     the approved take, copied (the probe cache may be cleaned)
"""
from datetime import datetime
import hashlib
import json
import re
import shutil
from threading import RLock

import soundfile as sf

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


def fix(role, take, text, origin):
    """Keep `take` (a WAV) and its text as the reference voice of `role`."""
    text = " ".join(str(text).split())
    if len(text) < 20:
        raise ValueError("The reference text is too short to fix a voice.")
    seconds = sf.info(take).duration
    if seconds < MIN_SECONDS:
        raise ValueError(f"The sample is {seconds:.1f} s. Use a reference of at least "
                         f"{MIN_SECONDS:.0f} seconds (ideally 10–20 s).")
    digest = hashlib.sha1(take.read_bytes() + text.encode("utf-8")).hexdigest()[:10]
    slug = re.sub(r"[^A-Za-z0-9]+", "-", role).strip("-").lower() or "voice"
    FOLDER.mkdir(exist_ok=True)
    target = FOLDER / f"{slug}-{digest}.wav"
    shutil.copyfile(take, target)
    entry = {"id": f"fix-{digest}", "file": target.name, "text": text, "seconds": round(seconds, 2),
             "origin": origin, "date": datetime.now().isoformat(timespec="seconds")}
    with _LOCK:
        registry = load()
        registry[role] = entry
        write_json(REGISTRY, registry)
    return entry


def unfix(role):
    with _LOCK:
        registry = load()
        registry.pop(role, None)
        write_json(REGISTRY, registry)


def samples():
    """role -> {"sample": line, "serious": line, "real": [lines from the book]}."""
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


def reference(voice_id):
    """(WAV path, text) for a fixed voice id, as the engine needs to register it."""
    for entry in load().values():
        if entry["id"] == voice_id:
            return FOLDER / entry["file"], entry["text"]
    raise ValueError("The fixed voice is no longer available. Approve and fix another preview.")
