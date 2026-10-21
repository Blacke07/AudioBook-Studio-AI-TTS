"""Available local models and starting descriptions for narrator and character auditions."""
import model_profile

VOICE_DESIGN = "VoiceDesign — voice from description"
CUSTOM_VOICE = "CustomVoice — built-in Qwen speakers"
# Base clones an approved take (reference audio + its text) for every passage: the only mode in which a
# voice keeps the same identity across passages. It takes no delivery instructions.
BASE_CLONE = "Base — fixed reference voice"
# Acoustic detail sampling temperature used when cloning a fixed reference.
CLONE_TIMBRE = 0.6
_PROFILE_KEYS = {VOICE_DESIGN: "voice_design", CUSTOM_VOICE: "custom_voice", BASE_CLONE: "base"}
# The files of the installed model profile, and of Standard (the reference for existing audio caches).
MODEL_FILES = {mode: model_profile.CURRENT[key] for mode, key in _PROFILE_KEYS.items()}
STANDARD_MODEL_FILES = {mode: model_profile.STANDARD[key] for mode, key in _PROFILE_KEYS.items()}
# Short names used in the character glossary; each maps to one of the two models above.
MODEL_NAMES = {"VoiceDesign": VOICE_DESIGN, "CustomVoice": CUSTOM_VOICE}
# The speakers stored in the CustomVoice GGUF. Each one is a fixed identity; only Ryan and
# Aiden are native English speakers, the others may keep an accent in English.
CUSTOM_SPEAKERS = {
    "Ryan": "male, native English, expressive",
    "Aiden": "male, native English, midrange",
    "Eric": "male, native Chinese",
    "Dylan": "young male, native Chinese",
    "Uncle_Fu": "older male, native Chinese",
    "Serena": "female, native Chinese",
    "Vivian": "young female, native Chinese",
    "Sohee": "female, native Korean",
    "Ono_Anna": "female, native Japanese",
}
PROFILES = {
    "Narrator — mature American, understated": (
        "A male audiobook narrator around forty years old, speaking clear, natural American English. "
        "A warm, grounded middle-low register with a mature, lightly textured timbre. "
        "Slightly sober and reflective, with balanced, restrained expressiveness and natural sentence melody. "
        "The voice feels human and engaged rather than theatrical or flat."
    ),
    "Male — mature, warm, restrained": (
        "A mature male narrator with a warm middle-low baritone, a gently textured timbre "
        "and clear neutral British English. Intimate and grounded, with understated warmth "
        "and a thoughtful, slightly melancholic character."
    ),
    "Male — deep, serious": (
        "A middle-aged male narrator with a deep, rounded, resonant voice and subtle vocal grain. "
        "Clear British English, composed and serious, with quiet authority and an unhurried cadence."
    ),
    "Male — intimate, natural": (
        "An adult male narrator with a soft, warm midrange voice, a little breath in the texture "
        "and a neutral American English accent. Personal, natural and reflective, as though "
        "telling a story to one listener."
    ),
    "Female — mature, warm": (
        "A mature female narrator with a warm low contralto, a smooth, lightly textured timbre "
        "and clear neutral English. Reflective and emotionally perceptive, with quiet confidence."
    ),
    "Character — American, deep": (
        "An adult male character with a low, dry, lightly roughened voice and a clear American English accent. "
        "Matter-of-fact and contained, with short, natural conversational phrasing."
    ),
    "Character — American, midrange": (
        "An adult male character with a clear, smooth midrange voice and a natural American English accent. "
        "Responsive and conversational, with a lighter tone and flexible everyday phrase stress."
    ),
}
# Starting voices for characters found automatically. They differ in age, pitch and texture
# so that two new characters never receive the same recipe; every one stays editable.
CHARACTER_PROFILES = {
    "male": {
        "Mature male — rough, practical baritone": (
            "A man in his fifties with a weathered, slightly rough baritone and plain American English. "
            "Practical, firm and unhurried, with short, grounded phrasing."
        ),
        "Male — clear, reserved tenor": (
            "An adult man with a smooth, light tenor voice and precise, educated American English. "
            "Composed, courteous and guarded, with even, controlled phrasing."
        ),
        "Male — nasal, tense": (
            "An adult man with a slightly nasal, tense midrange voice and quick American English. "
            "Wary and clipped, speaking a little faster than the people around him."
        ),
        "Older male — thin, hoarse": (
            "An elderly man over sixty-five with a thin, slightly hoarse voice and American English. "
            "Slow, deliberate and a little tired, with soft sentence endings."
        ),
        "Young male — bright, energetic": (
            "A young man about twenty with a bright, light voice and casual American English. "
            "Energetic and open, with quick, lively phrase stress."
        ),
        "Male — deep, calm bass": (
            "A big man in his forties with a very deep, resonant bass voice and slow American English. "
            "Calm and heavy, with long pauses and few words."
        ),
    },
    "female": {
        "Mature female — warm contralto": (
            "A woman in her fifties with a warm, low contralto and clear American English. "
            "Kind but firm, with steady, unhurried phrasing."
        ),
        "Young female — bright soprano": (
            "A young woman about twenty with a bright, light soprano voice and casual American English. "
            "Lively and quick, with open, expressive intonation."
        ),
        "Older female — gentle, dry": (
            "An elderly woman over sixty-five with a soft, dry, slightly fragile voice and American English. "
            "Gentle and deliberate, with careful pauses."
        ),
        "Female — velvety, cool mezzo": (
            "A woman in her thirties with a smooth, velvety mezzo-soprano and polished American English. "
            "Cool, controlled and precise, with little warmth in her phrasing."
        ),
    },
    "unknown": {
        "Character — neutral midrange": (
            "An adult speaker with a clear, neutral midrange voice and plain American English. "
            "Natural and conversational, with restrained emotion."
        ),
    },
}
_VARIANT_PARTS = {
    "ages": ("in his forties", "in his thirties", "in his late fifties", "in his early twenties", "over seventy"),
    "pitches": ("a mid-range", "a low", "a high, light", "a very deep"),
    "textures": ("clear, smooth", "warm, rounded", "gravelly, rough", "breathy, soft", "nasal, sharp"),
    "manners": ("is curt and businesslike", "is friendly and talkative", "speaks slowly and deliberately",
                "speaks quickly and nervously"),
}


def character_variants(gender):
    """Endless distinct starting descriptions once the named profiles are used up."""
    person = {"male": ("A man", "his", "He"), "female": ("A woman", "her", "She")}.get(gender, ("An adult", "their",
                                                                                                    "They"))
    for manner in _VARIANT_PARTS["manners"]:
        for texture in _VARIANT_PARTS["textures"]:
            for pitch in _VARIANT_PARTS["pitches"]:
                for age in _VARIANT_PARTS["ages"]:
                    age = age.replace("his", person[1])
                    verb = manner if person[2] != "They" else manner.replace("speaks", "speak").replace("is ", "are ")
                    yield (f"{person[0]} {age} with {pitch}, {texture} voice and plain American English. "
                           f"{person[2]} {verb}.")


CUSTOM_POOLS = {
    "male": ["Eric", "Dylan", "Uncle_Fu", "Aiden", "Ryan"],
    "female": ["Serena", "Sohee", "Vivian", "Ono_Anna"],
    "unknown": ["Aiden"],
}
CUSTOM_PROFILE = "Custom description"
DEFAULT_PROFILE = next(iter(PROFILES))
AUTHOR_DELIVERY = (
    "Read literary prose with measured but flowing pacing and clear American English. "
    "Use subtle changes in emphasis and pitch to follow the meaning, with enough emotion to keep "
    "the story alive. Keep the delivery slightly sober, understated and conversational. "
    "Let the ends of sentences settle naturally. Do not perform an exaggerated announcer voice."
)
CHARACTER_DELIVERY = (
    "Speak this character's dialogue naturally to another person. Use conversational phrase stress "
    "and restrained emotion. Keep this character's vocal identity consistent."
)
CUSTOM_PRESETS = {
    f"{speaker} — {style}": (speaker, instruction)
    for speaker in ("Ryan", "Aiden")
    for style, instruction in (
        ("restrained narration", AUTHOR_DELIVERY),
        ("warm, intimate", "Read as a warm, mature storyteller speaking to one listener. Use relaxed, "
         "flowing phrasing, gentle emphasis and understated emotion. Keep the delivery natural and grounded."),
        ("subtle tension", "Read with quiet, controlled tension. Use deliberate phrase stress and subtle "
         "changes of pace, keeping the voice grounded and the emotion restrained. Avoid melodrama."),
    )
}


def describe(profile):
    """Resolve a profile name (narrator or character list) to its English description."""
    profile = str(profile or "").strip()
    if profile in PROFILES:
        return PROFILES[profile]
    for profiles in CHARACTER_PROFILES.values():
        if profile in profiles:
            return profiles[profile]
    return profile


def custom_speaker(name):
    """Return the canonical CustomVoice speaker name, accepting any letter case."""
    lookup = {speaker.lower(): speaker for speaker in CUSTOM_SPEAKERS}
    return lookup.get(str(name or "").strip().lower())


def voice_parameters(mode, speaker, description, delivery):
    if mode not in MODEL_FILES:
        raise ValueError("Choose one of the available models.")
    if mode == BASE_CLONE:
        if not str(speaker).startswith("fix-"):
            raise ValueError("The fixed voice is missing. Approve and fix another reference.")
        return speaker, ""
    if mode == VOICE_DESIGN:
        if not description.strip():
            raise ValueError("Describe the voice in English before generating audio.")
        return "", description.strip() + "\nDelivery: " + delivery.strip()
    canonical = custom_speaker(speaker)
    if not canonical:
        raise ValueError(f"Voice CustomVoice «{speaker}» does not exist. Choose one of: {', '.join(CUSTOM_SPEAKERS)}.")
    return canonical.lower(), delivery.strip()
