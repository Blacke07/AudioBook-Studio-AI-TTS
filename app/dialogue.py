"""Reviewable speaker assignments and timing; never infer alternating identities."""
from dataclasses import dataclass, replace
import re

import fixed_voices
from glossary import INNER_VOICE, SAME_AS_NARRATOR, load_voices, normalize
from voices import BASE_CLONE, CHARACTER_DELIVERY, CUSTOM_PRESETS, MODEL_NAMES, describe, voice_parameters

NARRATOR = "Narrator"
UNASSIGNED = "Unassigned"
PAUSE = "Scene break"
SEPARATORS = ("❦", "***", "* * *")
SCRIPT_COLUMNS = ["Speaker", "Text", "Continues the paragraph"]
DIALOGUE_RE = re.compile(r'^(?:[—–-]\s+|["“])')
# Episode markers of the book: "— I —", "— Fire II —", "— Round I —". Read as headings, never as speech.
HEADING_RE = re.compile(r"^[—–]\s+(?:[A-Z][a-z]+\s+)?[IVXLC]+\s+[—–]$")
# A whole line in angle brackets: one of the voices heard inside the head (the past lives).
INNER_RE = re.compile(r"^<[^<>]+>$")
# Words between backticks, on one line, are a thought. They are read by the inner voice wherever they stand in
# a narration paragraph; the backticks stay in the script and are dropped only when the text is spoken.
THOUGHT_RE = re.compile(r"`[^`\n]*\w[^`\n]*`")

# Speech tags ("Morgan said", "she asked quietly", "said the conductor"). The tag runs to the end of
# its sentence; in dash-style dialogue whatever follows it is the same character speaking again.
_VERBS = (r"(?:said|says|asked|asks|replied|answered|added|whispered|muttered|murmured|called|shouted|yelled|"
          r"snapped|continued|began|repeated|admitted|agreed|insisted|explained|warned|offered|suggested|told|"
          r"corrected|interrupted|protested|remarked|observed|noted|sighed|laughed|grunted|breathed|hissed|"
          r"growled|demanded|conceded|finished|echoed|retorted|countered|announced|declared|went on|cut in|"
          r"put in|pointed out|called out)")
# Only third-person pronouns: "you said" / "I said" inside speech are far more often quoted talk.
_PRONOUN = r"(?:[Hh]e|[Ss]he)"
_NAME = r"(?:(?:Mr|Mrs|Ms|Dr)\.\s)?[A-Z][\w’'-]+(?:\s[A-Z][\w’'-]+){0,2}"
_DESCRIPTION = r"(?:[Tt]he|[Aa]n?|[Hh]is|[Hh]er|[Tt]heir|[Mm]y|[Oo]ur)(?:\s[a-z][\w’'-]+){1,3}?"
_SUBJECT = rf"(?:{_PRONOUN}|[Ss]ome(?:one|body)|{_DESCRIPTION}|{_NAME})"
# Words that turn "she said that…" or "Morgan said you'd come" into ordinary speech rather than a tag.
_NOT_TAG = (r"(?!\s+(?:that|it|so|this|those|these|nothing|something|anything|everything|to|if|whether|"
            r"you|you'd|you're|we|we'd|they|they'd|I|I'd|I'm|he'd|she'd|there)\b)")
_TAG = (rf"(?:(?P<subject>{_SUBJECT})\s+(?:\w+ly\s+)?{_VERBS}|{_VERBS}\s+(?P<inverted>{_NAME}|{_DESCRIPTION}))"
        rf"\b{_NOT_TAG}[^.!?…]*[.!?…]?")
DASH_TAG_RE = re.compile(rf"(?<=[,?!…—–])\s+(?P<tag>{_TAG})")
TAG_START_RE = re.compile(rf"^\s*{_TAG}")
QUOTE_RE = re.compile(r'“[^”\n]*(?:”|$)|"[^"\n]*(?:"|$)', re.M)
ANGLE_RE = re.compile(r'<[^<>\n]+>')
PRONOUNS = {"he": "male", "she": "female"}


@dataclass(frozen=True)
class Segment:
    kind: str          # narration, dialogue, tag or pause
    text: str
    joined: bool       # continues the previous segment's paragraph
    subject: str = ""  # speech-tag subject, e.g. "Morgan" or "she"
    after_blank: bool = False  # a blank line precedes it: a new exchange rather than a reply to the line above


@dataclass(frozen=True)
class Line:
    role: str
    text: str
    dialogue: bool
    joined: bool = False
    variant: int = 0   # added to the speaker's variant number when the author asks for another take
    row: int = -1      # index of the script row it comes from (for the editor)
    voice_role: str = ""  # reading identity; role remains the actual speaker
    emotion: str = ""     # delivery key from emotions.py; empty is neutral


@dataclass(frozen=True)
class Voice:
    speaker: str
    description: str
    instructions: str
    seed: int
    mode: str = ""


def _tag_subject(match):
    return (match.group("subject") or match.group("inverted") or "").strip()


def _split_dash_line(line):
    """'— It is green, Morgan said. Not a warning.' -> speech, tag, speech."""
    segments, rest, joined = [], line, False
    # The opening dash itself is never followed by a tag: "— Morgan said you'd come" is speech.
    start = DIALOGUE_RE.match(line).end()
    while True:
        match = DASH_TAG_RE.search(rest, start)
        if not match or not re.search(r"\w", rest[:match.start("tag")]):
            break
        segments.append(Segment("dialogue", rest[:match.start("tag")].strip(), joined))
        segments.append(Segment("tag", match.group("tag").strip(), True, _tag_subject(match)))
        joined, start = True, 0
        rest = rest[match.end("tag"):]
    if rest.strip():
        segments.append(Segment("dialogue", rest.strip(), joined))
    return segments


def _is_speech(span, before, after):
    """Quoted words in narration count as speech unless they look like a title or a scare quote."""
    words = span.strip('"“”').split()
    if len(words) >= 3:
        return True
    punctuated = re.search(r'[,.!?…—–-]["”]?$', span.strip()) is not None
    sentence_start = not before.strip() or re.search(r'[.!?:…]["”]?\s*$', before) is not None
    return punctuated and (sentence_start or TAG_START_RE.match(after) is not None)


def _split_quotes(text, starts_with_quote):
    spans = list(QUOTE_RE.finditer(text))
    if not spans:
        return None
    pieces, position = [], 0
    for match in spans:
        after = text[match.end():]
        if starts_with_quote or _is_speech(match.group(), text[:match.start()], after):
            pieces.append(("narration", text[position:match.start()]))
            pieces.append(("dialogue", match.group()))
            position = match.end()
    if not any(kind == "dialogue" for kind, _ in pieces):
        return None
    pieces.append(("narration", text[position:]))
    segments = []
    for kind, piece in pieces:
        if not piece.strip():
            continue
        tag = TAG_START_RE.match(piece) if kind == "narration" else None
        segments.append(Segment("tag" if tag else kind, piece.strip(), bool(segments),
                                _tag_subject(tag) if tag else ""))
    return segments


def _split_thoughts(text):
    """Narration with `thoughts` -> narration / inner / narration segments, or None when there is no thought.
    A backtick span inside a quoted speech is part of that speech, not a thought."""
    quoted = [match.span() for match in QUOTE_RE.finditer(text)]
    spans = [match.span() for match in THOUGHT_RE.finditer(text)
             if not any(start <= match.start() and match.end() <= end for start, end in quoted)]
    if not spans:
        return None
    segments, position = [], 0

    def narration(piece):
        stop = re.match(r"[.,;:!?…]+", piece)
        if segments and segments[-1].kind == "inner" and stop:  # `thought`. keeps its full stop
            segments[-1] = replace(segments[-1], text=segments[-1].text + stop.group())
            piece = piece[stop.end():]
        if piece.strip():
            segments.extend(_split_quotes(piece, False) or [Segment("narration", piece.strip(), False)])

    for start, end in spans:
        narration(text[position:start])
        segments.append(Segment("inner", text[start:end], False))
        position = end
    narration(text[position:])
    return [replace(item, joined=index > 0) for index, item in enumerate(segments)]


def _split_attributed_angles(text):
    """An angle-bracket utterance with an explicit speech tag is speech, not an unattributed thought."""
    match = ANGLE_RE.match(text)
    if not match or not TAG_START_RE.match(text[match.end():]):
        return None
    tail = text[match.end():].strip()
    tag = TAG_START_RE.match(tail)
    result = [Segment('dialogue', match.group(), False),
              Segment('tag', tag.group().strip(), True, _tag_subject(tag))]
    rest = tail[tag.end():].strip()
    if rest:
        result.append(Segment('narration', rest, True))
    return result


def split_points(text):
    """Code-point offsets for a visual split editor. Suggestions never change the source text."""
    points = {}
    for match in re.finditer(r'[.!?…]+["”’\)\]>]*\s+', text):
        position = match.end()
        before = text[:position].rstrip(' \t\n"”’)]>')
        if re.search(r'\b(?:Mr|Mrs|Ms|Dr|Prof|Capt|St|vs|etc)\.$', before, re.I):
            continue
        if re.search(r'\b[A-Z]\.$', before):
            continue
        if position < len(text):
            points[position] = 'Sentence end'
    for match in re.finditer(rf'(?<=[,?!…—–>”"])\s+(?={_TAG})', text):
        points[match.end()] = 'Speech tag'
    return [{'position':position, 'kind':kind} for position,kind in sorted(points.items())]


def segment(text, split_inline=True):
    """Narration, dialogue and pauses in reading order. The concatenated texts equal the source words."""
    segments, narrative = [], []
    blank = [True, True]  # [before the next line, before the pending narrative block]

    def add(items, after_blank):
        items = list(items)
        if items:
            items[0] = replace(items[0], after_blank=after_blank)
        segments.extend(items)

    def flush():
        if narrative:
            block = "\n".join(narrative)
            add((split_inline and (_split_thoughts(block) or _split_quotes(block, False)))
                or [Segment("narration", block, False)], blank[1])
            narrative.clear()

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            flush()
            blank[0] = True
            continue
        if line in SEPARATORS:
            flush()
            add([Segment("pause", line, False)], blank[0])
        elif HEADING_RE.match(line):
            flush()
            add([Segment("heading", line, False)], blank[0])
        elif split_inline and (attributed := _split_attributed_angles(line)):
            flush()
            add(attributed, blank[0])
        elif INNER_RE.match(line) and split_inline:
            flush()
            add([Segment("inner", line, False)], blank[0])
        elif DIALOGUE_RE.match(line):
            flush()
            if not split_inline:
                add([Segment("dialogue", line, False)], blank[0])
            elif line[0] in '"“':
                add(_split_quotes(line, True) or [Segment("dialogue", line, False)], blank[0])
            else:
                add(_split_dash_line(line), blank[0])
        else:
            if not narrative:
                blank[1] = blank[0]
            narrative.append(raw)
        blank[0] = False
    flush()
    return segments


def paragraph_of(segments, index):
    """Indices of the segments that share a paragraph with segments[index]."""
    start = index
    while start > 0 and segments[start].joined:
        start -= 1
    end = index + 1
    while end < len(segments) and segments[end].joined:
        end += 1
    return range(start, end)


def tag_subject(segments, index):
    """The single speech-tag subject in this dialogue segment's paragraph, if there is exactly one."""
    subjects = {segments[i].subject for i in paragraph_of(segments, index) if segments[i].kind == "tag"}
    return subjects.pop() if len(subjects) == 1 else ""


def resolve_name(subject, aliases):
    """Canonical character for an explicit named tag. Pronouns stay unresolved; a described role resolves
    only when the author defined it as an alias in the active context."""
    if not subject:
        return ""
    known = aliases.get(subject.lower())
    if known:
        return known
    if subject.split()[0].lower() in {"he", "she", "they", "i", "we", "you", "the", "a", "an",
                                      "his", "her", "their", "my", "our", "someone", "somebody"}:
        return ""
    return subject


def prepare_script(text, assign_dialogue=True, aliases=None):
    """Rows [speaker, text, continues paragraph]; explicitly tagged lines get their named speaker.
    `aliases` is one map, or a function of the scene number when alias scope depends on the context."""
    segments = segment(text)
    resolve = aliases if callable(aliases) else (lambda scene: aliases or {})
    rows, scene = [], 0
    for index, item in enumerate(segments):
        if item.kind == "pause":
            role = PAUSE
        elif item.kind == "inner" and assign_dialogue:
            role = INNER_VOICE
        elif item.kind != "dialogue" or not assign_dialogue:
            role = NARRATOR
        else:
            role = resolve_name(tag_subject(segments, index), resolve(scene)) or UNASSIGNED
        rows.append([role, item.text, item.joined])
        if item.kind == "pause":
            scene += 1
    return rows


def _joined(value):
    return value is True or str(value).strip().lower() in ("true", "da", "1", "↳")


def read_script(text, multi, rows, prepared_source):
    if multi:
        if prepared_source != text or not rows:
            raise ValueError("Analyze or split the dialogue again after the latest text change.")
    else:
        rows = [[NARRATOR if item.kind != "pause" else PAUSE, item.text, False]
                for item in segment(text, split_inline=False)]
    result = []
    for index, row in enumerate(rows, 1):
        if len(row) not in (2, 3, 4):
            raise ValueError(f"Line {index} must contain a speaker and text.")
        role, content = (str(value).strip() if value is not None else "" for value in row[:2])
        if not role and not content:
            continue
        if not role or not content:
            raise ValueError(f"Enter a speaker and text on line {index}.")
        if role == UNASSIGNED:
            raise ValueError(f"Assign a character to the dialogue on line {index}.")
        if role == PAUSE and content not in SEPARATORS:
            raise ValueError(f"Line {index}: a scene break may only replace a decorative separator.")
        joined = len(row) >= 3 and _joined(row[2]) and bool(result)
        dialogue = role != NARRATOR or (bool(DIALOGUE_RE.match(content)) and not HEADING_RE.match(content))
        variant = int(row[3] or 0) if len(row) == 4 else 0
        result.append(Line(role, content, dialogue, joined, variant, index - 1))
    if not result or not any(line.role != PAUSE for line in result):
        raise ValueError("Enter the text to read.")
    return result


# A tag that only says who speaks: "Morgan said.", "she asked.", "said Riley." — nothing about how or where.
SIMPLE_TAG_RE = re.compile(rf"^(?:{_SUBJECT}\s+(?:said|says|asked|asks|replied|answered)|"
                           rf"(?:said|asked|replied|answered)\s+(?:{_NAME}|{_DESCRIPTION}))[.,]?$")


def drop_simple_tags(lines, fixed_roles):
    """Leave out plain speech tags after a character whose fixed voice already tells the listener who speaks.
    The speech on both sides of the tag becomes one line, so it is read in one breath. Returns the new
    lines and the script rows that are no longer read."""
    def take_id(line):
        role = line.voice_role or line.role
        take = fixed_voices.take(role, line.emotion or 'neutral') or fixed_voices.get(role)
        return take['id'] if take else None

    result, dropped = [], set()
    index = 0
    while index < len(lines):
        line = lines[index]
        before = result[-1] if result else None
        if (before and line.role == NARRATOR and line.joined and SIMPLE_TAG_RE.match(line.text)
                and (fixed_roles(before) if callable(fixed_roles) else before.role in fixed_roles) and before.role != NARRATOR):
            dropped.add(line.row)
            after = lines[index + 1] if index + 1 < len(lines) else None
            if (after and after.joined and after.role == before.role and take_id(after) == take_id(before)
                    and (after.voice_role or after.role) == (before.voice_role or before.role)):
                first = before.text
                if first.endswith(",") and after.text[:1].isupper():
                    first = first[:-1] + "."  # "It is green," + "Not a warning." reads as two sentences
                result[-1] = replace(before, text=f"{first} {after.text}")
                index += 2
                continue
            index += 1
            continue
        result.append(line)
        index += 1
    return result, dropped


def default_cast():
    return [["Character 1", "", "unknown", "", SAME_AS_NARRATOR, "Ryan", "Character — American, deep", 41]]


def read_cast(rows, mode, narrator, names=None, use_fixed=True):
    """Voices by name: the narrator's, the characters' own and the shared ones; `names` limits checking to the
    voices actually heard. use_fixed=False gives the description recipe even for a fixed voice (to audition
    new takes). A character without a recipe or an approved take owns no voice and reads with another one."""
    voices = {NARRATOR: narrator}
    rows = normalize(rows)
    own = {row[0] for row in rows}
    fixed_roles = fixed_voices.load()
    for name, _aliases, _gender, _note, model, custom, design, seed in [*rows, *(row for row in load_voices() if row[0] not in own)]:
        if name in (NARRATOR, UNASSIGNED, PAUSE):
            raise ValueError(f"Reserved character name: {name}")
        if names is not None and name not in names or not (custom or design or name in fixed_roles):
            continue
        character_mode = mode if model == SAME_AS_NARRATOR else MODEL_NAMES[model]
        instruction = CHARACTER_DELIVERY
        if custom in CUSTOM_PRESETS:
            custom, preset_instruction = CUSTOM_PRESETS[custom]
            instruction += " " + preset_instruction
        fixed = fixed_voices.get(name) if use_fixed else None
        if fixed:  # an approved take wins over the recipe: same identity in every passage
            voice = Voice(fixed["id"], "", "", seed, BASE_CLONE)
        else:
            voice = Voice(custom, describe(design), instruction, seed, character_mode)
        try:
            voice_parameters(voice.mode, voice.speaker, voice.description, voice.instructions)
        except ValueError as error:
            raise ValueError(f"{name}: {error}") from error
        voices[name] = voice
    return voices


# Qwen's own leading/trailing silence is trimmed before assembly, so these are the real gaps.
WITHIN_PASSAGE_PAUSE = 0.3
JOINED_PAUSE = 0.25
NARRATION_PAUSE = 0.6
SCENE_PAUSE = 1.2


def boundary_pause(current, following, dialogue_pause):
    if current.role == PAUSE or following.role == PAUSE or HEADING_RE.match(current.text) \
            or HEADING_RE.match(following.text):
        return SCENE_PAUSE
    if following.joined:
        return JOINED_PAUSE
    if current.role != following.role or current.dialogue or following.dialogue:
        return float(dialogue_pause)
    return NARRATION_PAUSE
