"""Encode chapters and whole volumes with ffmpeg: speech-friendly, fast settings, tags and chapter marks."""
import shutil
import subprocess

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
    _run(["-i", str(chapter.audio_file), *_tags(settings, title, chapter.volume, chapter.number),
          *_codec(spec, settings["export_quality"], spec["ext"]), str(temporary)])
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
    _run(["-f", "concat", "-safe", "0", "-i", str(work / "_concat.txt"), "-i", str(work / "_chapters.txt"),
          "-map", "0:a", "-map_metadata", "1", "-map_chapters", "1",
          *_tags(settings, volume, volume), *_codec(spec, settings["export_quality"], spec["ext"]),
          *extra, str(temporary)])
    _replace(temporary, target)
    return target, len(chapters), position


def formats():
    return {"chapter": {key: value["label"] for key, value in FORMATS.items()},
            "volume": {key: value["label"] for key, value in VOLUME_FORMATS.items()}}


def available():
    return shutil.which("ffmpeg") is not None
