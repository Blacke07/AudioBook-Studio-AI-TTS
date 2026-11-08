"""The fixed vocabulary of line deliveries. Qwen hears emotion only through `instructions` (VoiceDesign and
CustomVoice); it ignores most punctuation as intonation and reads bracketed cues aloud, so the spoken text is
never changed. A fixed (Base) voice takes no instructions: its delivery comes from an approved take, one per
emotion, with the neutral take as the fallback."""

NEUTRAL = "neutral"
# key -> label, the instruction added to a recipe voice's delivery, and the line a fixed voice auditions it on
EMOTIONS = {
    NEUTRAL: {"label": "Neutral", "instruction": "", "sample": ""},
    "calm": {"label": "Calm",
             "instruction": "Say this line calmly and evenly, with a relaxed, steady voice.",
             "sample": "It's all right. There is no hurry now. We'll sit here for a while, let the kettle boil, "
                       "and think it through properly before anyone decides anything."},
    "dry": {"label": "Dry / sarcastic",
            "instruction": "Say this line dryly, with flat, understated sarcasm; the irony is in the timing, "
                           "not in exaggerated pitch.",
            "sample": "Oh, wonderful. Another meeting about the meeting. I can hardly wait to hear what we agreed "
                      "last time, since nobody seems to remember a single word of it."},
    "angry": {"label": "Angry",
              "instruction": "Say this line with controlled anger: tight, clipped and firm, without shouting.",
              "sample": "I told you not to touch it. I told you twice. And you went ahead anyway, as if my word "
                        "meant nothing at all in this house."},
    "shouting": {"label": "Shouting",
                 "instruction": "Shout this line: loud, forceful and urgent.",
                 "sample": "Get away from the edge! Now! Can't you hear it cracking? Run for the trees and don't "
                           "look back, whatever happens behind you!"},
    "weary": {"label": "Weary / sighing",
              "instruction": "Say this line wearily, on a tired exhale, with a heavy, sighing delivery and "
                             "fading endings.",
              "sample": "I've walked all day, and I still don't know where she went. I'm tired. I just want to "
                        "sit down somewhere quiet and stop thinking for a while."},
    "hesitant": {"label": "Hesitant",
                 "instruction": "Say this line hesitantly, with small pauses, as if searching for the words.",
                 "sample": "I'm not sure I... well, maybe it was the other road. Or maybe not. I think we "
                           "should... I don't know. Perhaps we ought to wait a little."},
    "whispered": {"label": "Whispered",
                  "instruction": "Whisper this line softly and closely, with a breathy, quiet voice.",
                  "sample": "Keep your voice down. They're right outside the door. If we stay very still, they "
                            "might walk past and never know that we were here."},
    "afraid": {"label": "Afraid",
               "instruction": "Say this line fearfully, with a tense, unsteady voice and quick breath.",
               "sample": "Did you hear that? Something moved behind the wall. Please don't open it. I'm begging "
                         "you, just leave it closed and come back to me."},
    "tender": {"label": "Tender",
               "instruction": "Say this line tenderly, warm and gentle, with a soft, intimate tone.",
               "sample": "Come here. You're shivering. It's all right now, I've got you. Rest your head and close "
                         "your eyes. I'll stay right here until morning."},
    "amused": {"label": "Amused",
               "instruction": "Say this line with quiet amusement, a smile audible in the voice, lightly teasing.",
               "sample": "You fell into the fountain? Fully dressed, in front of the whole town? Oh, I would have "
                         "paid good money to see that, truly."},
    # Moods of narration. A voice that follows a style hint (VoxCPM2) reads them directly; a Qwen recipe voice
    # gets the instruction; a fixed Qwen voice needs a take, like for any other emotion.
    "tense": {"label": "Tense",
              "instruction": "Say this line with held-back tension: low, controlled, slightly slower, every word placed carefully.",
              "sample": "He stopped at the gate. The latch was cold, and somewhere behind the hedge a branch "
                        "cracked. He did not turn around. He knew he was no longer alone."},
    "ominous": {"label": "Ominous",
                "instruction": "Say this line ominously: low and slow, with quiet menace and a long, heavy pause before the last words.",
                "sample": "The lamps along the road went out one by one, as if something were walking toward the "
                          "town and putting out each light it passed, without hurry and without a sound."},
    "wonder": {"label": "Wonder",
               "instruction": "Say this line with quiet wonder: open and slightly breathless, as if seeing it for the first time.",
               "sample": "The ceiling opened onto the sky. Thousands of pale lights hung in the dark above the "
                         "water, and for a long moment he forgot to breathe at all."},
    "sorrowful": {"label": "Sorrowful",
                  "instruction": "Say this line sorrowfully: soft and slow, heavy with grief, the voice nearly breaking at the end.",
                  "sample": "She held the small coat against her chest for a long time. It still smelled of rain "
                            "and woodsmoke and bread, and for a moment she let herself believe he would walk in."},
    "urgent": {"label": "Urgent",
               "instruction": "Say this line urgently: quick and driving, short breaths, rising pace without shouting.",
               "sample": "He ran. The bridge shook under his boots, the rope burned his palms, and behind him "
                         "the planks fell away into the river one after another, faster than he could climb."},
}
KEYS = tuple(EMOTIONS)
# The same deliveries as short style hints for VoxCPM2, which keeps the fixed take's timbre and follows the hint.
STYLES = {
    NEUTRAL: "",
    "calm": "calm, unhurried, gentle",
    "dry": "dry, understated, flat irony",
    "angry": "controlled anger, tight and clipped, not shouting",
    "shouting": "shouting, loud, forceful and urgent",
    "weary": "weary, tired, sighing, fading endings",
    "hesitant": "hesitant, with small pauses, searching for words",
    "whispered": "whispering, soft, breathy and close",
    "afraid": "afraid, tense and unsteady, quick breath",
    "tender": "tender, warm and soft, intimate",
    "amused": "quietly amused, smiling, lightly teasing",
    "tense": "tense, low and held back, slower",
    "ominous": "ominous, low and slow, quiet menace",
    "wonder": "full of quiet wonder, open and slightly breathless",
    "sorrowful": "sorrowful and tender, soft, voice almost breaking",
    "urgent": "urgent, quick and driving, rising pace",
}


def check(key):
    if key not in EMOTIONS:
        raise ValueError("Choose one of the listed emotions.")
    return key


def label(key):
    return EMOTIONS[key]["label"]


def instruction(key):
    return EMOTIONS[key]["instruction"]


def style(key):
    return STYLES[key]


def choices():
    """[{key, label}] in menu order, for the interface."""
    return [{"key": key, "label": value["label"]} for key, value in EMOTIONS.items()]
