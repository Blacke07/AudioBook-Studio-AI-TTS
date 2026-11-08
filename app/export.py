"""Encode chapters and whole volumes with ffmpeg: speech-friendly, fast settings, tags and chapter marks."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

import project

# Mono speech at 24 kHz. "standard" is transparent for a voice; "high" leaves extra headroom.
FORMATS = {
    "mp3": {"label": "MP3", "ext": "mp3", "standard": ["-c:a", "libmp3lame", "-b:a", "64k"],
            "high": ["-c:a", "libmp3lame", "-b:a", "96k"]},
    "m4a": {"label": "M4A (AAC)", "ext": "m4a", "standard": ["-c:a", "aac", "-b:a", "64k", "-movflags", "+faststart"],
            "high": ["-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart"]},
    "ogg": {"label": "OGG (Vorbis)", "ext": "ogg", "standard": ["-c:a", "libvorbis", "-q:a", "3"],
            "high": ["-c:a", "libvorbis", "-q:a", "5"]},
    "opus": {"label": "Opus", "ext": "opus", "standard": ["-c:a", "libopus", "-b:a", "32k", "-application", "voip"],
             "high": ["-c:a", "libopus", "-b:a", "48k", "-application", "audio"]},
    "flac": {"label": "FLAC (lossless)", "ext": "flac", "standard": ["-c:a", "flac", "-compression_level", "5"],
             "high": ["-c:a", "flac", "-compression_level", "8"]},
    "wav": {"label": "WAV (uncompressed)", "ext": "wav", "standard": ["-c:a", "pcm_s16le"],
            "high": ["-c:a", "pcm_s16le"]},
}
VOLUME_FORMATS = {"m4b": {"label": "M4B — audiobook with chapter markers", "ext": "m4b",
                          "standard": FORMATS["m4a"]["standard"], "high": FORMATS["m4a"]["high"]},
                  **{key: value for key, value in FORMATS.items() if key in ("mp3", "m4a", "ogg", "opus", "flac")}}
GAP_BETWEEN_CHAPTERS = 2.0
LOUDNESS = {"I": -19.0, "TP": -2.0, "LRA": 11.0}  # integrated LUFS: audiobook speech, clear and not too quiet
COVER_FORMATS = ("mp3", "m4a", "m4b", "flac")     # containers that carry a picture without extra work
COVER_NAMES = ("cover.jpg", "cover.jpeg", "cover.png")
COVER_SIDE = 1400                                 # pixels; larger pictures only bloat every file


def ffmpeg():
    path = shutil.which("ffmpeg")
    if not path:
        raise RuntimeError("FFmpeg was not found. Exporting formats other than WAV requires FFmpeg.")
    return path


def _run(arguments):
    result = subprocess.run([ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", *arguments],
                            capture_output=True, text=True, encoding="utf-8", errors="replace",
                            creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError("FFmpeg failed: " + result.stderr.strip()[-600:])


def _loudnorm(measured=None):
    """The loudnorm filter at the audiobook target. With a measurement it is linear (one gain, no pumping)."""
    parts = f"I={LOUDNESS['I']}:TP={LOUDNESS['TP']}:LRA={LOUDNESS['LRA']}"
    if measured:
        parts += (f":measured_I={measured['input_i']}:measured_TP={measured['input_tp']}"
                  f":measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}"
                  f":offset={measured['target_offset']}:linear=true")
    return "loudnorm=" + parts


def _measure(input_arguments):
    """Loudness of the audio as ffmpeg measures it, or None when it cannot be measured (then one pass is used)."""
    result = subprocess.run([ffmpeg(), "-hide_banner", "-nostats", "-loglevel", "info", *input_arguments, "-vn",
                             "-af", _loudnorm() + ":print_format=json", "-f", "null", "-"],
                            capture_output=True, text=True, encoding="utf-8", errors="replace",
                            creationflags=subprocess.CREATE_NO_WINDOW)
    block = re.findall(r"\{[^{}]*\}", result.stderr)
    try:
        values = json.loads(block[-1])
        if all(values.get(key) not in (None, "-inf", "inf") for key in ("input_i", "input_tp", "input_lra", "input_thresh",
                                                                         "target_offset")):
            return values
    except (IndexError, ValueError):
        pass
    return None


def _audio_filter(settings, extension, input_arguments):
    """Even out the loudness of every export, except WAV that is meant for editing. Opus is 48 kHz, the rest 24 kHz."""
    if not settings.get("loudness", True) or extension == "wav":
        return []
    rate = 48000 if extension == "opus" else 24000
    return ["-af", f"{_loudnorm(_measure(input_arguments))},aresample={rate}"]


def find_cover(settings, folder=None):
    """The cover picture: the file named in the settings, else cover.jpg/.jpeg/.png in the chapter folder."""
    chosen = str(settings.get("cover", "")).strip().strip('"')
    if chosen:
        path = Path(chosen)
        return path if path.is_file() and path.suffix.lower() in (".jpg", ".jpeg", ".png") else None
    if folder:
        for name in COVER_NAMES:
            if (Path(folder) / name).is_file():
                return Path(folder) / name
    return None


def _cover_arguments(cover, extension, picture_input):
    """Map the picture as an attached cover, re-encoded to a plain JPEG of sensible size."""
    if not cover or extension not in COVER_FORMATS:
        return []
    return ["-map", f"{picture_input}:v", "-c:v", "mjpeg", "-q:v", "3", "-pix_fmt", "yuvj420p",
            "-vf", f"scale='min({COVER_SIDE},iw)':-2", "-disposition:v:0", "attached_pic"]


def _tags(settings, title, album, track=None):
    tags = {"title": title, "album": album, "genre": "Audiobook"}
    if settings.get("author"):
        tags["artist"] = tags["album_artist"] = settings["author"]
    if track is not None:
        tags["track"] = str(track)
    return [item for key, value in tags.items() for item in ("-metadata", f"{key}={value}")]


def _codec(spec, quality, extension):
    arguments = list(spec["high" if quality == "high" else "standard"])
    # Opus works at 48 kHz; the others keep the 24 kHz of the model (no pointless resampling).
    return arguments + ["-ac", "1"] + ([] if extension == "opus" else ["-ar", "24000"])


def export_chapter(chapter, settings):
    if not chapter.audio_file.exists():
        raise ValueError(f"{chapter.stem}: the chapter has not been generated.")
    spec = FORMATS[settings["export_format"]]
    target = chapter.export_path(spec["ext"])
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.stem + ".tmp." + spec["ext"])
    title = f"{chapter.number} - {chapter.title}" if chapter.number is not None else chapter.title
    source = ["-i", str(chapter.audio_file)]
    cover = find_cover(settings, project.get_volume(chapter.volume)["source"])
    pictured = ["-i", str(cover)] if cover and spec["ext"] in COVER_FORMATS else []
    _run([*source, *pictured, "-map", "0:a", *_cover_arguments(cover, spec["ext"], 1),
          *_tags(settings, title, chapter.volume, chapter.number),
          *_audio_filter(settings, spec["ext"], source), *_codec(spec, settings["export_quality"], spec["ext"]),
          str(temporary)])
    _replace(temporary, target)
    return target


def _replace(temporary, target):
    try:
        temporary.replace(target)
    except PermissionError:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"{target.name} is open in another program. "
                           "Close it and export again.") from None


def _escape(value):
    return str(value).replace("\\", "\\\\").replace("=", "\\=").replace(";", "\\;").replace("#", "\\#") \
        .replace("\n", " ")


def export_volume(volume, settings, progress=lambda message: None):
    """One file for the whole volume, chapter after chapter with a short gap and a chapter mark for each."""
    chapters = [chapter for chapter in project.chapters(volume) if chapter.audio_file.exists()]
    if not chapters:
        raise ValueError("No generated chapters are available in this volume.")
    spec = VOLUME_FORMATS[settings["volume_format"]]
    folder = project.EXPORT / project.safe_name(volume)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{project.safe_name(volume)} - complete volume.{spec['ext']}"
    work = project.WORK / project.safe_name(volume)
    work.mkdir(parents=True, exist_ok=True)
    gap = work / "_chapter-gap.wav"
    sf.write(gap, np.zeros(int(24000 * GAP_BETWEEN_CHAPTERS), dtype=np.float32), 24000, subtype="PCM_16")
    listing, metadata, position = [], [";FFMETADATA1", f"title={_escape(volume)}", f"album={_escape(volume)}"], 0.0
    for index, chapter in enumerate(chapters):
        seconds = sf.info(chapter.audio_file).duration
        listing.append("file '" + str(chapter.audio_file).replace("'", "'\\''") + "'")
        title = f"{chapter.number} - {chapter.title}" if chapter.number is not None else chapter.title
        metadata += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={int(position * 1000)}",
                     f"END={int((position + seconds) * 1000)}", f"title={_escape(title)}"]
        position += seconds
        if index + 1 < len(chapters):
            listing.append("file '" + str(gap).replace("'", "'\\''") + "'")
            position += GAP_BETWEEN_CHAPTERS
    (work / "_concat.txt").write_text("\n".join(listing), encoding="utf-8")
    (work / "_chapters.txt").write_text("\n".join(metadata), encoding="utf-8")
    progress(f"Encoding the volume ({len(chapters)} chapters, {position / 3600:.1f} hours)")
    temporary = target.with_name(target.stem + ".tmp." + spec["ext"])
    extra = ["-f", "mp4"] if spec["ext"] == "m4b" else []
    source = ["-f", "concat", "-safe", "0", "-i", str(work / "_concat.txt")]
    cover = find_cover(settings, project.get_volume(volume)["source"])
    pictured = ["-i", str(cover)] if cover and spec["ext"] in COVER_FORMATS else []
    _run([*source, "-i", str(work / "_chapters.txt"), *pictured,
          "-map", "0:a", *_cover_arguments(cover, spec["ext"], 2), "-map_metadata", "1", "-map_chapters", "1",
          *_tags(settings, volume, volume), *_audio_filter(settings, spec["ext"], source),
          *_codec(spec, settings["export_quality"], spec["ext"]), *extra, str(temporary)])
    _replace(temporary, target)
    return target, len(chapters), position


def formats():
    return {"chapter": {key: value["label"] for key, value in FORMATS.items()},
            "volume": {key: value["label"] for key, value in VOLUME_FORMATS.items()}}


def available():
    return shutil.which("ffmpeg") is not None
