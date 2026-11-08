"""Turn a chapter script into audio: bounded passages, content-addressed on disk, then one chapter WAV."""
import hashlib
import io
import json
import re
from dataclasses import dataclass, replace
from threading import Lock

import numpy as np
import soundfile as sf

import emotions
import engine_client
import fixed_voices
import glossary
import project
import voice_check
from dialogue import (HEADING_RE, NARRATOR, PAUSE, SCENE_PAUSE, TAG_START_RE, UNASSIGNED, WITHIN_PASSAGE_PAUSE, Voice,
                      boundary_pause, drop_simple_tags, read_cast, read_script)
from engine_client import synthesize
from project import split_passages
from voices import (BASE_CLONE, CLONE_TIMBRE, MODEL_FILES, MODEL_NAMES, STANDARD_MODEL_FILES, VOX_CLONE, describe,
                    voice_parameters)
# Engines that clone an approved take: the voice keeps one identity and is checked against that take.
FIXED_MODES = (BASE_CLONE, VOX_CLONE)

# One GPU user at a time: Qwen passages, previews and Gemma analysis all take this lock.
LOCK = Lock()
RATE = 24000
# Long enough (15–20 s) to become a good reference take when the author fixes the voice.
PREVIEW_TEXT = (
    "The library opened a little after sunrise. A narrow beam of light crossed the floor, "
    "touching the row of books beside the window. For a moment, the room seemed exactly as it "
    "had the night before. Then she noticed the envelope waiting on the empty desk."
)
CHARACTER_SAMPLE = (
    "I checked the route twice before we left, which seemed sensible at the time. The map is perfectly clear. "
    "Unfortunately, the road has apparently decided to disagree with it. We can wait here and debate the "
    "matter, or take the bridge before the rain starts."
)
# Silence Qwen leaves around a clip (measured: median 0.08 s before, 0.10 s after, up to 0.77 s).
EDGE_KEEP = 0.05
NUMBERS = {"I": "One", "II": "Two", "III": "Three", "IV": "Four", "V": "Five", "VI": "Six", "VII": "Seven",
           "VIII": "Eight", "IX": "Nine", "X": "Ten", "XI": "Eleven", "XII": "Twelve"}


def speakable(text):
    """What Qwen should read: webnovel markup (`thought`, <voice>, [message], *emphasis*) without its
    symbols, episode markers as words. The script and the source keep the original characters."""
    text = text.strip()
    if HEADING_RE.match(text):
        words = text.strip("—– ").split()
        return " ".join(NUMBERS.get(word, word) for word in words) + "."
    text = re.sub(r"^[—–-]\s+", "", text)
    text = re.sub(r"[`<>\[\]*_]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def spelled_out(lines, settings):
    """With "Spell out numbers" on, numbers, money, times and titles are written in words before they are read.
    The source and the script keep the digits; an edit made in Spoken text replaces this later and so still wins."""
    if not settings.get("spell_out"):
        return lines
    from text_normalize import normalize
    return [line if line.role == PAUSE else replace(line, text=normalize(line.text)) for line in lines]


def decode_audio(data):
    audio, rate = sf.read(io.BytesIO(data), dtype="float32")
    if rate != RATE or audio.ndim != 1 or not audio.size or not np.isfinite(audio).all():
        raise RuntimeError("The engine returned invalid audio.")
    return audio, rate


def trim_edges(audio, rate=RATE):
    """Remove Qwen's own leading/trailing silence, keeping a short margin so soft consonants survive."""
    frame = int(rate * 0.01)
    if audio.size < frame * 4:
        return audio
    energy = np.sqrt(np.mean(audio[:audio.size // frame * frame].reshape(-1, frame) ** 2, axis=1))
    voiced = np.flatnonzero(energy > max(energy.max() * 0.01, 1e-4))
    if not voiced.size:
        return audio
    keep = int(rate * EDGE_KEEP)
    return audio[max(0, voiced[0] * frame - keep):min(audio.size, (voiced[-1] + 1) * frame + keep)]


def suspicious(text, seconds):
    """Speaking rates far outside English narration (about 14 characters per second) usually mean a
    skipped phrase, a long hesitation or a repeated word."""
    # A digit is spoken as several letters ("262" -> "two hundred sixty-two").
    rate = (len(text) + 4 * sum(c.isdigit() for c in text)) / max(seconds, 0.01)
    return seconds > 0.6 and (rate < 6 or rate > 28)


def narrator_voice(settings):
    narrator = settings["narrator"]
    fixed = fixed_voices.get(NARRATOR)
    if fixed:  # the approved take, cloned by Base (or VoxCPM2, with delivery): one identity for the whole book
        mode = VOX_CLONE if narrator.get("engine") == "voxcpm" else BASE_CLONE
        return Voice(fixed["id"], "", "", int(narrator["seed"]), mode)
    return narrator_recipe(settings)


def narrator_recipe(settings):
    """The narrator's description voice, also when a take is fixed (to audition new takes)."""
    narrator = settings["narrator"]
    mode = MODEL_NAMES[narrator["mode"]]
    description = narrator["description"] or describe(narrator["profile"])
    voice_parameters(mode, narrator["speaker"], description, narrator["instructions"])
    return Voice(narrator["speaker"], description, narrator["instructions"], int(narrator["seed"]), mode)


def temperature_for(settings, role):
    """The performance variation of a voice: its own when the author set one, else the narrator's."""
    return float(settings.get("voice_variation", {}).get(role, settings["narrator"]["temperature"]))


def generate(text, voice, temperature, variant=0):
    """One trimmed clip for `text` in `voice`. Callers hold LOCK."""
    data = synthesize(speakable(text), voice.mode, voice.speaker, voice.description, voice.instructions,
                      voice.seed + int(variant), temperature)
    return trim_edges(decode_audio(data)[0])


@dataclass(frozen=True)
class Chunk:
    role: str
    text: str
    pause_after: float
    line: int = -1
    variant: int = 0
    voice_role: str = ""
    emotion: str = ""
    joined_rows: tuple[int, ...] = ()


def plan_chunks(lines, voices, dialogue_pause, *, join_narrated_tags=False):
    planned = []
    for line in lines:
        if join_narrated_tags and planned and line.role == NARRATOR and line.joined and TAG_START_RE.fullmatch(line.text):
            before, joined_rows = planned[-1]
            if (before.role not in (NARRATOR, PAUSE) and not joined_rows and before.variant == line.variant
                    and (before.emotion or emotions.NEUTRAL) == (line.emotion or emotions.NEUTRAL)):
                combined = f"{before.text} {line.text}"
                if len(split_passages(combined)) == 1:
                    planned[-1] = (replace(before, text=combined), (line.row,))
                    continue
        planned.append((line, ()))
    chunks = []
    for index, (line, joined_rows) in enumerate(planned):
        if line.role == PAUSE:
            continue
        if (line.voice_role or line.role) not in voices:
            raise ValueError(f"Character «{line.role}» has no voice in the glossary.")
        passages = split_passages(line.text)
        for part, (passage, _) in enumerate(passages):
            if part < len(passages) - 1:
                pause = WITHIN_PASSAGE_PAUSE
            elif index + 1 < len(planned):
                pause = boundary_pause(line, planned[index + 1][0], dialogue_pause)
            else:
                pause = 0.0
            chunks.append(Chunk(line.role, passage, pause, line.row if line.row >= 0 else index, line.variant,
                                line.voice_role, line.emotion, joined_rows))
    return chunks


def generation_order(chunks, voices):
    """Indices grouped by model, the already loaded model first: at most one model switch per chapter."""
    modes = list(dict.fromkeys(voices[chunk.voice_role or chunk.role].mode for chunk in chunks))
    if engine_client._current_model in modes:
        modes.remove(engine_client._current_model)
        modes.insert(0, engine_client._current_model)
    return [index for mode in modes for index, chunk in enumerate(chunks) if voices[chunk.voice_role or chunk.role].mode == mode]


def delivered(chunk, voice):
    """The voice as it reads this chunk, and whether the chunk's emotion is heard. A recipe voice adds the
    emotion's instruction to its delivery; a fixed voice clones the role's approved take for that emotion, or
    its neutral take when there is none (Base takes no instructions). VoxCPM2 keeps the neutral take's timbre
    and hears the emotion as a style hint."""
    emotion = chunk.emotion or emotions.NEUTRAL
    if emotion == emotions.NEUTRAL:
        return voice, False
    if voice.mode == VOX_CLONE:
        return replace(voice, instructions=emotions.style(emotion)), True
    if voice.mode == BASE_CLONE:
        take = fixed_voices.take(chunk.voice_role or chunk.role, emotion)
        return (replace(voice, speaker=take["id"]), True) if take else (voice, False)
    return replace(voice, instructions=f"{voice.instructions} {emotions.instruction(emotion)}".strip()), True


def missing_takes(chunks, voices):
    """{(role, emotion)} of fixed voices asked for an emotion they have no approved take for."""
    return {(chunk.voice_role or chunk.role, chunk.emotion) for chunk in chunks
            if chunk.emotion and chunk.emotion != emotions.NEUTRAL
            and voices[chunk.voice_role or chunk.role].mode == BASE_CLONE
            and not delivered(chunk, voices[chunk.voice_role or chunk.role])[1]}


def passage_key(chunk, voice, temperature):
    """Everything that changes the sound of a passage; equal keys can reuse the same file. An emotion counts
    only where it is heard (its instruction or its own take); neutral passages keep their earlier keys."""
    voice, heard = delivered(chunk, voice)
    data = [voice.mode, voice.speaker, voice.description, voice.instructions, voice.seed + chunk.variant,
            round(float(temperature), 3), speakable(chunk.text)]
    if heard:
        data.append({"emotion": chunk.emotion})
    if voice.mode == BASE_CLONE:
        data.append(CLONE_TIMBRE)
    if voice.mode in MODEL_FILES and MODEL_FILES[voice.mode] != STANDARD_MODEL_FILES[voice.mode]:
        data.append(MODEL_FILES[voice.mode])  # another model file sounds different; Standard keys stay as they were
    return hashlib.sha1(json.dumps(data, ensure_ascii=False).encode("utf-8")).hexdigest()[:20]


def passage_file(key):
    return project.PASSAGES / f"{key}.wav"


class NotReady(ValueError):
    """The chapter needs the author (analysis missing, text changed or lines to attribute)."""


def chapter_plan(chapter, settings, glossary_rows=None, text=None, *, routing_rules=None, script_override=None, registry_document=None, enforce_status=True):
    """The ordered passages of a chapter with their voices and keys, from its saved script."""
    text = chapter.text() if text is None else text
    narrator = narrator_voice(settings)
    if settings["multi_voice"]:
        script = script_override if script_override is not None else chapter.script()
        if script is None:
            raise NotReady("This chapter has not been analyzed.")
        if script["source_hash"] != project.text_hash(text):
            raise NotReady("The chapter text changed after analysis. Analyze it again.")
        from character_registry import check_reading
        try:
            check_reading(script, registry_document, enforce=enforce_status)
        except ValueError as error:
            raise NotReady(str(error)) from error
        rows = [list(row) for row in script["rows"]]
        if settings["unclear_policy"] == "narrator":
            rows = [[NARRATOR, *row[1:]] if row[0] == UNASSIGNED else row for row in rows]
        elif any(row[0] == UNASSIGNED for row in rows):
            raise NotReady(f"{sum(row[0] == UNASSIGNED for row in rows)} lines need you to choose a speaker.")
        lines = read_script(text, True, rows, text)
        rows_glossary = glossary.load() if glossary_rows is None else glossary_rows
        from voice_rules import resolve
        lines = resolve(lines, script, rows_glossary, routing_rules)
        from character_registry import check_category_references
        check_category_references(lines, registry_document)
        from spoken_text import apply_lines
        lines = apply_lines(spelled_out(lines, settings), script)
        import delivery
        lines = delivery.apply_lines(lines, script)
        if settings.get("speech_tags", "omit_fixed") == "omit_fixed":
            fixed = set(fixed_voices.load())
            lines, _ = drop_simple_tags(lines, lambda line: line.role in fixed and line.voice_role == line.role)
        speakers = {line.voice_role or line.role for line in lines if line.role != PAUSE and (line.voice_role or line.role) != NARRATOR}
        # "same as narrator" means the narrator's recipe model, not his fixed clone.
        voices = read_cast(rows_glossary, MODEL_NAMES[settings["narrator"]["mode"]], narrator, speakers)
    else:
        script = script_override if script_override is not None else chapter.script()
        if script:
            if script['source_hash'] != project.text_hash(text):
                raise NotReady('The source changed after analysis. Prepare the chapter again.')
            from spoken_text import apply_lines
            # Keep the saved script's row anchors even when every row is read by Narrator.
            # Resegmenting the source here used to shift playback after split speech tags.
            rows = [[PAUSE if row[0] == PAUSE else NARRATOR, *row[1:]] for row in script['rows']]
            lines = apply_lines(spelled_out(read_script(text, True, rows, text), settings), script)
            import delivery
            lines = delivery.apply_lines(lines, script)
            lines = [replace(line, voice_role=NARRATOR) for line in lines]
        else:
            lines = read_script(text, False, None, "")
        voices = {NARRATOR: narrator}
    if script:
        # Narrator-only reading and unresolved-speaker fallback change the voice, not the identity.
        lines = [replace(line, role=script['rows'][line.row][0]) for line in lines]
    chunks = plan_chunks(lines, voices, settings["dialogue_pause"], join_narrated_tags=not settings["multi_voice"])
    if settings["announce_titles"]:
        chunks.insert(0, Chunk(NARRATOR, project.announcement(chapter.stem), SCENE_PAUSE))
    keys = [passage_key(chunk, voices[chunk.voice_role or chunk.role],
                        temperature_for(settings, chunk.voice_role or chunk.role)) for chunk in chunks]
    return chunks, voices, keys


VOICE_RETRIES = 2  # extra takes for a passage whose voice drifted towards another character
PACE_RETRIES = 2   # extra takes for a passage spoken far too fast or too slow (a skipped phrase, a long hesitation)
LEVEL_RANGE = (0.7, 1.4)  # a passage is brought towards the chapter's usual level by at most this factor (about 3 dB)
FADE = 0.006       # seconds of fade at the edges of an assembled passage: no clicks between clips


def fixed_references(voices):
    """Approved takes of the fixed voices taking part in a chapter, by speaker."""
    if not voice_check.available():
        return {}
    references = {}
    for name, voice in voices.items():
        entry = fixed_voices.get(name) if voice.mode in FIXED_MODES else None
        if entry:
            references[name] = fixed_voices.FOLDER / entry["file"]
    return references


def render_checked(chunk, voice, temperature, key, references, retry_pace=True):
    """Generate one passage. For a fixed voice, its fingerprint is compared with the approved take and with
    the other fixed voices of the chapter; a take closer to someone else is redone with another variant,
    keeping the best one. Writes the passage WAV and a .qc.json with the verdict."""
    target = passage_file(key)
    attempts = []
    checked = (chunk.voice_role or chunk.role) in references
    for attempt in range(1 + max(VOICE_RETRIES if checked else 0, PACE_RETRIES if retry_pace else 0)):
        with LOCK:
            audio = generate(chunk.text, voice, temperature, chunk.variant + 1000 * attempt)
        temporary = target.with_name(f"{key}.try{attempt}.wav")
        sf.write(temporary, audio, RATE, subtype="PCM_16")
        verdict = None
        if checked and audio.size / RATE >= voice_check.MIN_SECONDS:
            others = {name: path for name, path in references.items() if name != (chunk.voice_role or chunk.role)}
            verdict = voice_check.judge(temporary, references[chunk.voice_role or chunk.role], others)
        margin = verdict["margin"] if verdict else 1.0
        pace_ok = not (retry_pace and suspicious(speakable(chunk.text), audio.size / RATE))
        attempts.append(((pace_ok, margin), attempt, temporary, verdict))
        if pace_ok and (verdict is None or margin >= voice_check.MIN_MARGIN):
            break
    (_, margin), best, chosen, verdict = max(attempts, key=lambda item: item[0])
    chosen.replace(target)
    for _, _, path, _ in attempts:
        path.unlink(missing_ok=True)
    if verdict:
        project.write_json(target.with_suffix(".qc.json"), {
            **verdict, "attempts": len(attempts), "chosen": best,
            "drifting": margin < voice_check.MIN_MARGIN})


def voiced_level(audio, rate=RATE):
    """RMS of the speaking part of a clip (quiet frames ignored), or 0 for silence."""
    frame = int(rate * 0.02)
    if audio.size < frame * 2:
        return 0.0
    energy = np.sqrt(np.mean(audio[:audio.size // frame * frame].reshape(-1, frame) ** 2, axis=1))
    voiced = energy[energy > energy.max() * 0.1]
    return float(np.sqrt(np.mean(voiced ** 2))) if voiced.size else 0.0


def level_gains(levels):
    """One gain per passage: outliers move towards the chapter's median level, never by more than LEVEL_RANGE."""
    speaking = [level for level in levels if level > 1e-4]
    if not speaking:
        return [1.0] * len(levels)
    middle = float(np.median(speaking))
    low, high = LEVEL_RANGE
    return [min(max(middle / level, low), high) if level > 1e-4 else 1.0 for level in levels]


def smoothed(audio, gain, rate=RATE):
    """The passage at its gain (never past full scale) with a few milliseconds of fade at both edges."""
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    audio = audio * (min(gain, 0.98 / peak) if peak > 0 else 1.0)
    fade = min(int(rate * FADE), audio.size // 2)
    if fade:
        ramp = np.linspace(0.0, 1.0, fade, dtype=np.float32)
        audio = audio.copy()
        audio[:fade] *= ramp
        audio[-fade:] *= ramp[::-1]
    return audio.astype(np.float32, copy=False)


def render_chapter(chapter, settings, progress=lambda done, total, message: None, should_stop=lambda: False):
    """Generate the missing passages (resuming earlier work), then assemble chapter.wav.
    Returns the chapter metadata, or None when stopped before the end."""
    chunks, voices, keys = chapter_plan(chapter, settings)
    project.PASSAGES.mkdir(parents=True, exist_ok=True)
    order = [index for index in generation_order(chunks, voices) if not passage_file(keys[index]).exists()]
    references = fixed_references(voices)
    flagged = set()
    for done, index in enumerate(order):
        if should_stop():
            return None
        chunk = chunks[index]
        progress(len(chunks) - len(order) + done, len(chunks), f"{chunk.role}: {chunk.text[:60]}")
        role = chunk.voice_role or chunk.role
        voice, heard = delivered(chunk, voices[role])
        checked = references
        if heard and voice.mode == BASE_CLONE and role in references:
            # an emotion take is checked against itself: a whisper is not a drift from the neutral take
            checked = {**references, role: fixed_voices.FOLDER / fixed_voices.take(role, chunk.emotion)["file"]}
        render_checked(chunk, voice, temperature_for(settings, role), keys[index], checked,
                       *(() if settings.get("retry_pace", True) else (False,)))
    progress(len(chunks), len(chunks), "Assembling the chapter")
    chapter.work.mkdir(parents=True, exist_ok=True)
    temporary = chapter.audio_file.with_suffix(".tmp.wav")
    seconds = 0.0
    passages = []
    checks = {"checked": 0, "redone": 0, "drifting": 0}
    clips = [sf.read(passage_file(key), dtype="float32")[0] for key in keys]
    gains = level_gains([voiced_level(clip) for clip in clips]) if settings.get("level_passages", True) else [1.0] * len(clips)
    with sf.SoundFile(temporary, mode="w", samplerate=RATE, channels=1, subtype="PCM_16") as output:
        for chunk, key, clip, gain in zip(chunks, keys, clips, gains):
            audio = smoothed(clip, gain) if settings.get("level_passages", True) else clip
            length = audio.size / RATE
            check = project._read_json(passage_file(key).with_suffix(".qc.json"), {})
            if check:
                checks["checked"] += 1
                checks["redone"] += check["attempts"] > 1
                checks["drifting"] += check["drifting"]
            if suspicious(speakable(chunk.text), length) or check.get("drifting"):
                flagged.add(chunk.line)
            passages.append({"role": chunk.role, "text": chunk.text, "line": chunk.line, "key": key,
                             "voice_role": chunk.voice_role or chunk.role, "start": round(seconds, 3), "seconds": round(length, 3),
                             **({"joined_rows": list(chunk.joined_rows)} if chunk.joined_rows else {}),
                             **({"emotion": chunk.emotion} if chunk.emotion else {})})
            output.write(audio)
            seconds += length
            if chunk.pause_after:
                output.write(np.zeros(int(RATE * chunk.pause_after), dtype=np.float32))
                seconds += chunk.pause_after
    temporary.replace(chapter.audio_file)
    missing = sorted(missing_takes(chunks, voices))
    meta = {"keys": keys, "seconds": round(seconds, 2), "flagged_lines": sorted(flagged), "passages": passages,
            **({"missing_takes": [{"role": role, "emotion": emotion} for role, emotion in missing]} if missing else {}),
            "voice_checks": checks, "voices": {name: voice.__dict__ for name, voice in voices.items()}}
    project.write_json(chapter.audio_meta, meta)
    return meta


def preview_voice(voice, text, temperature, variant=0):
    """A probe WAV for the GUI, cached by its content in work/_probe."""
    chunk = Chunk(NARRATOR, text[:600], 0, variant=variant)
    key = passage_key(chunk, voice, temperature)
    target = project.PROBES / f"{key}.wav"
    if not target.exists():
        with LOCK:
            audio = generate(text[:600], voice, temperature, variant)
        project.PROBES.mkdir(parents=True, exist_ok=True)
        sf.write(target, audio, RATE, subtype="PCM_16")
    return target
