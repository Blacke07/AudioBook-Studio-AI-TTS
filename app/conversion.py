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
from dialogue import (HEADING_RE, NARRATOR, PAUSE, SCENE_PAUSE, UNASSIGNED, WITHIN_PASSAGE_PAUSE, Voice,
                      boundary_pause, drop_simple_tags, read_cast, read_script)
from engine_client import synthesize
from project import split_passages
from voices import (BASE_CLONE, CLONE_TIMBRE, MODEL_FILES, MODEL_NAMES, STANDARD_MODEL_FILES, describe,
                    voice_parameters)

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
    if fixed:  # the approved take, cloned by Base: one identity for the whole book
        return Voice(fixed["id"], "", "", int(narrator["seed"]), BASE_CLONE)
    return narrator_recipe(settings)


def narrator_recipe(settings):
    """The narrator's description voice, also when a take is fixed (to audition new takes)."""
    narrator = settings["narrator"]
    mode = MODEL_NAMES[narrator["mode"]]
    description = narrator["description"] or describe(narrator["profile"])
    voice_parameters(mode, narrator["speaker"], description, narrator["instructions"])
    return Voice(narrator["speaker"], description, narrator["instructions"], int(narrator["seed"]), mode)


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


def plan_chunks(lines, voices, dialogue_pause):
    chunks = []
    for index, line in enumerate(lines):
        if line.role == PAUSE:
            continue
        if (line.voice_role or line.role) not in voices:
            raise ValueError(f"Character «{line.role}» has no voice in the glossary.")
        passages = split_passages(line.text)
        for part, (passage, _) in enumerate(passages):
            if part < len(passages) - 1:
                pause = WITHIN_PASSAGE_PAUSE
            elif index + 1 < len(lines):
                pause = boundary_pause(line, lines[index + 1], dialogue_pause)
            else:
                pause = 0.0
            chunks.append(Chunk(line.role, passage, pause, line.row if line.row >= 0 else index, line.variant,
                                line.voice_role, line.emotion))
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
    its neutral take when there is none (Base takes no instructions)."""
    emotion = chunk.emotion or emotions.NEUTRAL
    if emotion == emotions.NEUTRAL:
        return voice, False
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
    if MODEL_FILES[voice.mode] != STANDARD_MODEL_FILES[voice.mode]:
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
        lines = apply_lines(lines, script)
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
        if script and script.get('spoken_text'):
            if script['source_hash'] != project.text_hash(text):
                raise NotReady('The source changed after spoken-text editing. Prepare the chapter again.')
            from spoken_text import apply_lines
            rows = [[PAUSE if row[0] == PAUSE else NARRATOR, *row[1:]] for row in script['rows']]
            lines = apply_lines(read_script(text, True, rows, text), script)
            import delivery
            lines = delivery.apply_lines(lines, script)
        else:
            lines = read_script(text, False, None, "")
        voices = {NARRATOR: narrator}
    chunks = plan_chunks(lines, voices, settings["dialogue_pause"])
    if settings["announce_titles"]:
        chunks.insert(0, Chunk(NARRATOR, project.announcement(chapter.stem), SCENE_PAUSE))
    temperature = settings["narrator"]["temperature"]
    keys = [passage_key(chunk, voices[chunk.voice_role or chunk.role], temperature) for chunk in chunks]
    return chunks, voices, keys


VOICE_RETRIES = 2  # extra takes for a passage whose voice drifted towards another character


def fixed_references(voices):
    """Approved takes of the fixed voices taking part in a chapter, by speaker."""
    if not voice_check.available():
        return {}
    references = {}
    for name, voice in voices.items():
        entry = fixed_voices.get(name) if voice.mode == BASE_CLONE else None
        if entry:
            references[name] = fixed_voices.FOLDER / entry["file"]
    return references


def render_checked(chunk, voice, temperature, key, references):
    """Generate one passage. For a fixed voice, its fingerprint is compared with the approved take and with
    the other fixed voices of the chapter; a take closer to someone else is redone with another variant,
    keeping the best one. Writes the passage WAV and a .qc.json with the verdict."""
    target = passage_file(key)
    attempts = []
    for attempt in range(1 + (VOICE_RETRIES if (chunk.voice_role or chunk.role) in references else 0)):
        with LOCK:
            audio = generate(chunk.text, voice, temperature, chunk.variant + 1000 * attempt)
        temporary = target.with_name(f"{key}.try{attempt}.wav")
        sf.write(temporary, audio, RATE, subtype="PCM_16")
        verdict = None
        if (chunk.voice_role or chunk.role) in references and audio.size / RATE >= voice_check.MIN_SECONDS:
            others = {name: path for name, path in references.items() if name != (chunk.voice_role or chunk.role)}
            verdict = voice_check.judge(temporary, references[chunk.voice_role or chunk.role], others)
        attempts.append((verdict["margin"] if verdict else 1.0, attempt, temporary, verdict))
        if verdict is None or verdict["margin"] >= voice_check.MIN_MARGIN:
            break
    margin, best, chosen, verdict = max(attempts, key=lambda item: item[0])
    chosen.replace(target)
    for _, _, path, _ in attempts:
        path.unlink(missing_ok=True)
    if verdict:
        project.write_json(target.with_suffix(".qc.json"), {
            **verdict, "attempts": len(attempts), "chosen": best,
            "drifting": margin < voice_check.MIN_MARGIN})


def render_chapter(chapter, settings, progress=lambda done, total, message: None, should_stop=lambda: False):
    """Generate the missing passages (resuming earlier work), then assemble chapter.wav.
    Returns the chapter metadata, or None when stopped before the end."""
    chunks, voices, keys = chapter_plan(chapter, settings)
    temperature = settings["narrator"]["temperature"]
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
        render_checked(chunk, voice, temperature, keys[index], checked)
    progress(len(chunks), len(chunks), "Assembling the chapter")
    chapter.work.mkdir(parents=True, exist_ok=True)
    temporary = chapter.audio_file.with_suffix(".tmp.wav")
    seconds = 0.0
    passages = []
    checks = {"checked": 0, "redone": 0, "drifting": 0}
    with sf.SoundFile(temporary, mode="w", samplerate=RATE, channels=1, subtype="PCM_16") as output:
        for chunk, key in zip(chunks, keys):
            audio, _ = sf.read(passage_file(key), dtype="float32")
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
