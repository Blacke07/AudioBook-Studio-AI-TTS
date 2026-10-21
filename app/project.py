"""The book as volumes of chapter files: settings, per-chapter scripts and states on disk.

Layout (all inside the app folder; the author's chapter files are only read):
  settings.json                      narrator voice, pauses, export and automation settings
  volumes.json                      the registered volumes: name and source folder
  work/<volume>/<chapter>/        script.json (speakers per line), chapter.wav, audio.json
  work/passages/<key>.wav          every generated passage, named by what it contains (voice + text),
                                   so an interrupted chapter resumes and unchanged lines are never redone
  export/<volume>/                 the finished files in the chosen format
"""
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
from text_input import read_text_file, split_passages  # noqa: E402,F401
SETTINGS_FILE = ROOT / "settings.json"
VOLUMES_FILE = ROOT / "volumes.json"
WORK = ROOT / "work"
PASSAGES = WORK / "passages"
PROBES = WORK / "previews"
EXPORT = ROOT / "export"
CHAPTER_RE = re.compile(r"^\s*(\d+)\s*[-–—.]?\s*(.*)$")

DEFAULT_SETTINGS = {
    "narrator": {
        "mode": "VoiceDesign",
        "speaker": "Ryan",
        "profile": "Narrator — mature American, understated",
        "description": "",
        "instructions": "",
        "seed": 42,
        "temperature": 0.55,
    },
    "multi_voice": True,
    "dialogue_pause": 0.6,
    "announce_titles": True,
    "speech_tags": "omit_fixed",    # omit_fixed = leave out "Morgan said." when Morgan's voice is fixed; all = read
    "unclear_policy": "wait",       # wait = the chapter waits for the author; narrator = narrator reads them
    "export_format": "mp3",
    "export_quality": "standard",
    "volume_format": "m4b",
    "author": "",
}


def _read_json(path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, data):
    """Atomic write: a crash never leaves half a settings or script file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def load_settings():
    from voices import AUTHOR_DELIVERY, PROFILES
    saved = _read_json(SETTINGS_FILE, {})
    settings = {**DEFAULT_SETTINGS, **saved, "narrator": {**DEFAULT_SETTINGS["narrator"], **saved.get("narrator", {})}}
    narrator = settings["narrator"]
    narrator["description"] = narrator["description"] or PROFILES.get(narrator["profile"], "")
    narrator["instructions"] = narrator["instructions"] or AUTHOR_DELIVERY
    return settings


def save_settings(settings):
    clean = {**DEFAULT_SETTINGS, **settings}
    clean["narrator"] = {**DEFAULT_SETTINGS["narrator"], **settings.get("narrator", {})}
    write_json(SETTINGS_FILE, clean)
    return load_settings()


def safe_name(name):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", str(name)).strip(" .")[:90]
    if not name:
        raise ValueError("Name cannot be empty.")
    return name


def volumes():
    return _read_json(VOLUMES_FILE, [])


def get_volume(name):
    for volume in volumes():
        if volume["name"] == name:
            return volume
    raise ValueError(f"Volume «{name}» does not exist.")


def add_volume(name, source):
    source = Path(str(source).strip().strip('"'))
    if not source.is_dir():
        raise ValueError(f"Folder does not exist: {source}")
    if not chapter_files(source):
        raise ValueError("The folder contains no TXT or DOCX chapters.")
    name = safe_name(name or source.name)
    items = [volume for volume in volumes() if volume["name"] != name]
    items.append({"name": name, "source": str(source)})
    write_json(VOLUMES_FILE, items)
    return name


def remove_volume(name):
    """Only forgets the volume; generated audio and exports stay on disk."""
    write_json(VOLUMES_FILE, [volume for volume in volumes() if volume["name"] != name])


def _natural(path):
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", path.stem)]


def chapter_files(source):
    return sorted((path for path in Path(source).iterdir()
                   if path.is_file() and path.suffix.lower() in (".txt", ".docx") and not path.name.startswith(("~", "!"))),
                  key=_natural)


def title_of(stem):
    """'262 - North' -> (262, 'North')."""
    match = CHAPTER_RE.match(stem)
    return (int(match.group(1)), match.group(2).strip() or stem) if match else (None, stem)


def announcement(stem):
    number, title = title_of(stem)
    return f"Chapter {number}. {title}." if number is not None else f"{title}."


def text_hash(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


class Chapter:
    def __init__(self, volume, path):
        self.volume = volume
        self.path = Path(path)
        self.stem = self.path.stem
        self.number, self.title = title_of(self.stem)
        self.work = WORK / safe_name(volume) / safe_name(self.stem)

    @property
    def script_file(self):
        return self.work / "script.json"

    @property
    def audio_file(self):
        return self.work / "chapter.wav"

    @property
    def audio_meta(self):
        return self.work / "audio.json"

    @property
    def error_file(self):
        return self.work / "error.txt"

    def text(self):
        return read_text_file(self.path)

    def script(self):
        return _read_json(self.script_file, None)

    def save_script(self, data):
        write_json(self.script_file, data)

    def export_path(self, extension):
        return EXPORT / safe_name(self.volume) / f"{safe_name(self.stem)}.{extension}"


def chapters(volume_name):
    volume = get_volume(volume_name)
    source = Path(volume["source"])
    if not source.is_dir():
        raise ValueError(f"The volume folder is no longer available: {source}")
    return [Chapter(volume_name, path) for path in chapter_files(source)]


def get_chapter(volume_name, stem):
    for chapter in chapters(volume_name):
        if chapter.stem == stem:
            return chapter
    raise ValueError(f"Chapter «{stem}» does not exist in {volume_name}.")


def export_extension(settings):
    return {"m4a": "m4a", "ogg": "ogg", "opus": "opus", "flac": "flac", "wav": "wav"}.get(settings["export_format"], "mp3")


def unclear_count(script):
    from dialogue import UNASSIGNED
    return sum(1 for row in script["rows"] if row[0] == UNASSIGNED)
