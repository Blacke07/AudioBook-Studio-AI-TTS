"""The book as volumes of chapter files: settings, per-chapter scripts and states on disk.

Paths below are relative to Data/User (development checkout: app); source chapters are only read:
  settings.json                      narrator voice, pauses, export and automation settings
  volumes.json                      the registered volumes: name and source folder
  work/<volume>/<chapter>/        script.json (speakers per line), chapter.wav, audio.json
  work/passages/<key>.wav          every generated passage, named by what it contains (voice + text),
                                   so an interrupted chapter resumes and unchanged lines are never redone
  ../../Audiobooks/<volume>/       the finished files in the chosen format
"""
import hashlib
import json
import math
import ntpath
import re
from pathlib import Path

from layout import Layout, check_path_length
LAYOUT = Layout.for_program(Path(__file__).resolve().parent)
PROGRAM = LAYOUT.program
ROOT = LAYOUT.user
from text_input import read_text_file, split_passages  # noqa: E402,F401
SETTINGS_FILE = ROOT / "settings.json"
VOLUMES_FILE = ROOT / "volumes.json"
WORK = ROOT / "work"
PASSAGES = WORK / "passages"
PROBES = WORK / "previews"
EXPORT = LAYOUT.audiobooks
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
    "voice_variation": {},          # voice name -> own performance variation; a voice without one follows the narrator's
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


def backups_folder():
    return LAYOUT.backups/'Projects' if LAYOUT.installed else ROOT/'projects-backup'


def media_roots():
    import fixed_voices, presets
    return {'work': WORK, 'export': EXPORT, 'voices': fixed_voices.FOLDER, 'presets': presets.FOLDER}


def media_token(path):
    path = Path(path).resolve()
    for label, folder in media_roots().items():
        if path.is_relative_to(folder.resolve()):
            return label + '/' + path.relative_to(folder.resolve()).as_posix()
    raise ValueError('File is outside the application media folders.')


def media_path(token):
    path = Path(token)
    if path.is_absolute() or ':' in token or '\\' in token or '..' in path.parts or len(path.parts) < 2:
        raise ValueError('Invalid media path.')
    folder = media_roots().get(path.parts[0])
    if folder is None:
        raise ValueError('File is outside the application media folders.')
    result = folder.joinpath(*path.parts[1:]).resolve()
    if not result.is_relative_to(folder.resolve()):
        raise ValueError('Invalid media path.')
    return result


def write_json(path, data):
    """Atomic write: a crash never leaves half a settings or script file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def load_settings():
    from dataclasses import asdict
    from video import VideoSettings
    from voices import AUTHOR_DELIVERY, PROFILES
    saved = _read_json(SETTINGS_FILE, {})
    settings = {**DEFAULT_SETTINGS, **saved, "narrator": {**DEFAULT_SETTINGS["narrator"], **saved.get("narrator", {})}}
    narrator = settings["narrator"]
    narrator["description"] = narrator["description"] or PROFILES.get(narrator["profile"], "")
    narrator["instructions"] = narrator["instructions"] or AUTHOR_DELIVERY
    settings["video"] = asdict(VideoSettings.from_dict(saved.get("video", {})))
    return settings


def clean_variation(value):
    """The per-voice performance variations; anything that is not a number above 0 up to 2 is dropped."""
    result = {}
    for name, number in (value if isinstance(value, dict) else {}).items():
        if type(number) in (int, float) and math.isfinite(number) and 0 < number <= 2 and isinstance(name, str):
            result[name] = float(number)
    return result


def save_settings(settings):
    from dataclasses import asdict
    from video import VideoSettings
    clean = {**DEFAULT_SETTINGS, **settings}
    clean["narrator"] = {**DEFAULT_SETTINGS["narrator"], **settings.get("narrator", {})}
    clean["video"] = asdict(VideoSettings.from_dict(settings.get("video", {})))
    clean["voice_variation"] = clean_variation(settings.get("voice_variation"))
    write_json(SETTINGS_FILE, clean)
    return load_settings()


def safe_name(name, limit=90):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", str(name)).strip(" .")[:limit]
    if not name:
        raise ValueError("Name cannot be empty.")
    return name


def volumes():
    return _read_json(VOLUMES_FILE, [])


def volume_id(volume):
    """Stable volume identity; the display name may change without losing associations."""
    return volume.get("id") or "volume-" + hashlib.sha1(volume["name"].casefold().encode("utf-8")).hexdigest()[:12]


def ensure_volume_ids():
    """Give every registered volume its stable ID once; existing IDs are never rewritten."""
    items = volumes()
    changed = False
    for volume in items:
        key = volume_id(volume)
        if volume.get("id") != key:
            volume["id"] = key
            changed = True
    if changed:
        write_json(VOLUMES_FILE, items)
    return items


def find_volume(name):
    for volume in volumes():
        if volume["name"] == name:
            return volume
    return None


def get_volume(name):
    volume = find_volume(name)
    if volume is None:
        raise ValueError(f"Volume «{name}» does not exist.")
    return volume


def add_volume(name, source):
    source = str(source).strip().strip('"')
    if not is_local_source(source):
        raise ValueError('Choose an absolute local drive path for the chapter folder.')
    source = Path(source)
    if not source.is_dir():
        raise ValueError(f"Folder does not exist: {source}")
    if not chapter_files(source):
        raise ValueError("The folder contains no TXT or DOCX chapters.")
    name = safe_name(name or source.name)
    if any(volume["name"].casefold() == name.casefold() for volume in volumes()):
        raise ValueError("This volume already exists. Use Edit volume to change its folder.")
    items = volumes()
    record = {"name": name, "source": str(source)}
    record["id"] = volume_id(record)
    items.append(record)
    write_json(VOLUMES_FILE, items)
    return name


def update_volume(name, source):
    """Relink the active source; the stable name preserves cached work and exports."""
    get_volume(name)
    source = str(source).strip().strip('"')
    if not is_local_source(source) or not Path(source).is_dir() or not chapter_files(source):
        raise ValueError('Choose an existing local folder containing TXT or DOCX chapters.')
    items = [{**volume, 'source':str(Path(source))} if volume['name']==name else volume for volume in volumes()]
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
        check_path_length(self.path)
        check_path_length(self.work/'script.json.project-tmp')
        check_path_length(EXPORT/safe_name(volume)/'video'/f'{safe_name(self.stem)}.mp4')

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
    if not is_local_source(volume['source']):
        raise ValueError('The volume requires an absolute local drive path. Locate its chapter folder again.')
    source = Path(volume["source"])
    if not source.is_dir():
        raise ValueError(f"The volume folder is no longer available: {source}")
    return [Chapter(volume_name, path) for path in chapter_files(source)]


def is_local_source(source):
    """Syntax check only: never resolve or probe a path supplied by an imported project."""
    if not isinstance(source, str) or any(ord(char)<32 for char in source):
        return False
    drive, tail = ntpath.splitdrive(source)
    return bool(re.fullmatch('[A-Za-z]:', drive) and tail.startswith(('\\','/'))
                and not tail.startswith(('\\\\','//')) and ':' not in tail)


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
