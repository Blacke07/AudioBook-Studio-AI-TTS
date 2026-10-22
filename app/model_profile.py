"""The model set chosen at installation: Standard (F32 audition models, Gemma 12B) or Compact (Q8 audition
models, a smaller Gemma). Setup records it in installation-manifest.json; a source checkout uses Standard.

Fixed reference voices are cloned with the same Base Q8 model in every profile, so a book read with fixed
voices sounds the same in both. Only auditions of new voices and the dialogue model differ."""
import json
import re

from project import LAYOUT

KEYS = ("voice_design", "custom_voice", "base", "codec", "gemma", "render_factor")
STANDARD = {
    "name": "standard",
    "label": "Standard",
    "voice_design": "qwen-talker-1.7b-voicedesign-F32.gguf",
    "custom_voice": "qwen-talker-1.7b-customvoice-F32.gguf",
    "base": "qwen-talker-1.7b-base-Q8_0.gguf",
    "codec": "qwen-tokenizer-12hz-F32.gguf",
    "gemma": "gemma4:12b",
    "render_factor": 0.45,
}
SAFE_FILE = re.compile(r"^[A-Za-z0-9._-]+\.gguf$")
SAFE_TAG = re.compile(r"^[a-z0-9._-]+:[A-Za-z0-9._-]+$")


def load(root=None):
    """The installed profile, checked so a damaged manifest cannot point the engine at another file."""
    manifest = (LAYOUT.state if root is None else root) / "installation-manifest.json"
    if not manifest.is_file():
        return dict(STANDARD)
    profile = json.loads(manifest.read_text(encoding="utf-8")).get("model_profile")
    if profile is None:
        return dict(STANDARD)
    missing = [key for key in KEYS if key not in profile]
    if missing:
        raise ValueError("The installed model profile is incomplete: " + ", ".join(missing))
    for key in ("voice_design", "custom_voice", "base", "codec"):
        if not SAFE_FILE.match(str(profile[key])):
            raise ValueError(f"The installed model profile names an invalid file: {profile[key]}")
    if not SAFE_TAG.match(str(profile["gemma"])):
        raise ValueError(f"The installed model profile names an invalid dialogue model: {profile['gemma']}")
    return {"name": str(profile.get("name", "custom")), "label": str(profile.get("label", "Custom")),
            **{key: profile[key] for key in KEYS[:5]}, "render_factor": float(profile["render_factor"])}


CURRENT = load()
