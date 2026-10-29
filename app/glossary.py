"""Character glossary: identity facts for attribution, and the voices they read with.

A character may own a voice (its recipe is stored with it, its approved take under its name). A shared voice
belongs to nobody: it lives in the `voices` list next to the characters and is never a speaker. Both kinds use
the same row shape here: name, aliases, gender, note, model, CustomVoice speaker, description, seed."""
import json
from pathlib import Path
import re
import unicodedata
from threading import RLock

import fixed_voices
from voices import CHARACTER_PROFILES, CUSTOM_POOLS, character_variants, custom_speaker, describe

from project import ROOT
GLOSSARY_FILE = ROOT / 'characters.json'
COLUMNS = ["Character", "Aliases", "Gender", "Context for speaker detection", "Model", "CustomVoice speaker",
           "VoiceDesign profile or description", "Variation"]
GENDERS = {"male": "male", "female": "female", "unknown": "unknown"}
GENDER_LABELS = {value: key for key, value in GENDERS.items()}
SAME_AS_NARRATOR = "same as narrator"
MODEL_CHOICES = (SAME_AS_NARRATOR, "VoiceDesign", "CustomVoice")
PLACEHOLDER = re.compile(r"Character \d+")
INNER_VOICE = "Inner voice"
INNER_DESCRIPTION = ("A soft, close, intimate voice speaking just above a whisper, as if heard inside one's own head. "
                     "Calm, slightly distant and timeless, with neutral American English and no clear age.")
_LOCK = RLock()


def _text(value):
    return str(value).strip() if value is not None else ""


def speaker_name(value, allow_reserved=False):
    """Display identities live in JSON, not filesystem path components."""
    if (not isinstance(value,str) or not value or value!=value.strip() or len(value)>1024
            or any(unicodedata.category(char)=='Cc' for char in value)
            or not allow_reserved and value.casefold() in ('narrator','unassigned','scene break')):
        raise ValueError('Invalid speaker name: use 1–1024 characters, without controls or reserved roles.')
    return value


def normalize_row(row, index=0):
    """Validate one table row; old four-column rows (name, CustomVoice, VoiceDesign, seed) are accepted."""
    row = list(row)
    if len(row) == 4:
        row = [row[0], "", "unknown", "", SAME_AS_NARRATOR, row[1], row[2], row[3]]
    if len(row) != len(COLUMNS):
        raise ValueError(f"The glossary has {len(COLUMNS)} columns; row {index} has {len(row)}.")
    name, aliases, gender, note, model, custom, design, seed = row
    name = _text(name)
    if not name:
        if any(_text(value) for value in row[1:]):
            raise ValueError(f"Enter a character name in the glossary on row {index}.")
        return None
    speaker_name(name)
    gender = _text(gender).lower() or "unknown"
    if gender not in GENDERS:
        raise ValueError(f"{name}: gender must be male, female or unknown.")
    model = _text(model) or SAME_AS_NARRATOR
    if model not in MODEL_CHOICES:
        raise ValueError(f"{name}: model must be {', '.join(MODEL_CHOICES)}.")
    try:
        number = float(seed)
    except (TypeError, ValueError):
        raise ValueError(f"Invalid variation number for {name}.") from None
    if number != int(number) or not 0 <= int(number) <= 2147483647:
        raise ValueError(f"Invalid variation number for {name}.")
    return [name, _text(aliases), gender, _text(note), model, _text(custom), _text(design), int(number)]


def normalize(rows):
    result, seen = [], set()
    for index, row in enumerate(rows or [], 1):
        checked = normalize_row(row, index)
        if checked is None:
            continue
        if checked[0].casefold() in seen:
            raise ValueError(f"Character {checked[0]} appears twice (ignoring letter case).")
        seen.add(checked[0].casefold())
        result.append(checked)
    return result


def load():
    if not GLOSSARY_FILE.exists():
        return []
    data = json.loads(GLOSSARY_FILE.read_text(encoding="utf-8"))
    if isinstance(data, list):  # first format: [name, CustomVoice, VoiceDesign, seed]
        return normalize(data)
    if not isinstance(data, dict) or not isinstance(data.get("characters"), list):
        raise ValueError("characters.json is not a valid character glossary.")
    return normalize([[item.get("name"), ", ".join(item.get("aliases", [])), GENDER_LABELS.get(item.get("gender"),
                       "unknown"), item.get("note", ""), item.get("model", SAME_AS_NARRATOR),
                       item.get("custom_voice", ""), item.get("voice_design", ""), item.get("seed", 0)]
                      for item in data["characters"]])


def library_rows(data):
    """The shared voices of a characters.json document, as glossary rows (no aliases)."""
    items = data.get("voices", []) if isinstance(data, dict) else []
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        raise ValueError("Invalid shared voice list.")
    return normalize([[item.get("name"), "", GENDER_LABELS.get(item.get("gender"), "unknown"), item.get("note", ""),
                       item.get("model", SAME_AS_NARRATOR), item.get("custom_voice", ""), item.get("voice_design", ""),
                       item.get("seed", 0)] for item in items])


def load_voices():
    if not GLOSSARY_FILE.exists():
        return []
    return library_rows(json.loads(GLOSSARY_FILE.read_text(encoding="utf-8")))


def has_recipe(row):
    return bool(row[5] or row[6])


def own_voices(rows):
    """Characters that own a voice: a recipe, or an approved take kept under their name."""
    fixed = fixed_voices.load()
    return [row for row in normalize(rows) if has_recipe(row) or row[0] in fixed]


def voice_names(rows, library=None):
    """Every voice a character can read with, except the narrator: own voices first, then the shared ones."""
    library = load_voices() if library is None else library
    return [*(row[0] for row in own_voices(rows)), *(row[0] for row in library)]


def document_voices(data):
    """voice_names() for a characters.json document that may not be saved yet."""
    if not isinstance(data, dict):
        return []
    fixed = fixed_voices.load()
    own = [entry["name"] for entry in data.get("characters", [])
           if entry.get("custom_voice") or entry.get("voice_design") or entry["name"] in fixed]
    return [*own, *(row[0] for row in library_rows(data))]


def check_library(rows, library):
    taken = {row[0].casefold() for row in rows}
    for row in library:
        if row[0].casefold() in taken:
            raise ValueError(f"{row[0]} is both a character and a shared voice. Rename one of them.")


def save(rows, voices=None):
    """Write the whole glossary as shown in the table; placeholders are never stored. `voices` replaces the
    shared voices; by default they are kept."""
    rows = [row for row in normalize(rows) if not PLACEHOLDER.fullmatch(row[0])]
    with _LOCK:
        _write(rows, voices)
    return rows


def to_data(rows, read_as=None, voices=None):
    from voice_rules import explicit_rules, validate_targets
    source = json.loads(GLOSSARY_FILE.read_text(encoding='utf-8')) if GLOSSARY_FILE.exists() else {}
    library = library_rows(source) if voices is None else normalize(voices)
    check_library(rows, library)
    rules = explicit_rules() if read_as is None else read_as
    names = {row[0] for row in rows}
    rules = {name:target for name,target in rules.items() if name in names}
    validate_targets(rules, names, set(voice_names(rows, library)))

    def recipe(model, custom, design, seed):
        return {"model": model, "custom_voice": custom, "voice_design": design, "seed": seed}

    result = {"version": 3, "voices": [{
        "name": name, "gender": GENDERS[gender], "note": note, **recipe(model, custom, design, seed),
    } for name, _aliases, gender, note, model, custom, design, seed in library], "characters": [{
        "name": name, "aliases": aliases_of(aliases), "gender": GENDERS[gender], "note": note,
        # a character without a recipe owns no voice: it reads with a shared voice or the narrator's
        **(recipe(model, custom, design, seed) if custom or design else {}),
        **({"read_as":rules[name]} if name in rules else {}),
    } for name, aliases, gender, note, model, custom, design, seed in rows]}
    if isinstance(source, dict) and 'organization' in source:
        from character_registry import organization
        metadata = source['organization']
        result['organization'] = {**metadata, 'characters': {k:v for k,v in metadata.get('characters', {}).items() if k in names}}
        result['organization'] = organization(result)
    return result


def _write(rows, voices=None):
    data = to_data(rows, voices=voices)
    temporary = GLOSSARY_FILE.with_suffix(".tmp")
    try:
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(GLOSSARY_FILE)
    finally:
        if temporary.exists():
            temporary.unlink()


def aliases_of(value):
    return [alias.strip() for alias in str(value or "").split(",") if alias.strip()]


def alias_map(rows):
    """Lower-case name or alias -> canonical glossary name."""
    result = {}
    for row in normalize(rows):
        for alias in [row[0], *aliases_of(row[1])]:
            result.setdefault(alias.lower(), row[0])
    return result


def gender_of(rows, name):
    for row in normalize(rows):
        if row[0] == name:
            return GENDERS[row[2]]
    return "unknown"


def voice_key(row, narrator_mode_name):
    """What a listener actually hears: the model plus the speaker or the resolved description."""
    model = narrator_mode_name if row[4] == SAME_AS_NARRATOR else row[4]
    if model == "CustomVoice":
        return model, (custom_speaker(row[5]) or row[5]).lower()
    return model, " ".join(describe(row[6]).lower().split())


def duplicate_voices(rows, narrator_mode_name, names=None):
    """Pairs of characters (optionally limited to `names`) that would sound like the same recipe."""
    groups = {}
    for row in normalize(rows):
        if has_recipe(row) and (names is None or row[0] in names):
            groups.setdefault(voice_key(row, narrator_mode_name), []).append(row[0])
    return [group for group in groups.values() if len(group) > 1]


def add_missing(new_rows):
    """Add characters found by an analysis without touching the rest of the glossary (which the author may
    be editing at the same moment). Returns the names actually added."""
    with _LOCK:
        rows = load()
        known = {row[0] for row in rows}
        added = [row for row in normalize(new_rows) if row[0] not in known]
        if added:
            save(rows + added)
        return [row[0] for row in added]


def propose(name, gender, rows):
    """A starting voice for a new character, different from every recipe already in the glossary."""
    rows = normalize(rows)
    if name == INNER_VOICE:
        return [name, "", "unknown", "Text enclosed in angle brackets or backticks: a thought or inner voice heard in the mind.",
                SAME_AS_NARRATOR, "Vivian", INNER_DESCRIPTION, 777]
    gender = gender if gender in CHARACTER_PROFILES else "unknown"
    used_designs = {" ".join(describe(row[6]).lower().split()) for row in rows}
    used_custom = {(custom_speaker(row[5]) or row[5]).lower() for row in rows}
    candidates = [*CHARACTER_PROFILES[gender], *character_variants(gender)]
    design = next(profile for profile in candidates if " ".join(describe(profile).lower().split()) not in used_designs)
    pool = CUSTOM_POOLS[gender]
    custom = next((speaker for speaker in pool if speaker.lower() not in used_custom), pool[len(rows) % len(pool)])
    seed = 1000 + sum((i + 1) * ord(c) for i, c in enumerate(name))
    return [name, "", GENDER_LABELS[gender], "", SAME_AS_NARRATOR, custom, design, seed]
