"""Ready-made voices: approved synthetic reference takes with the parameters that produced them.

  presets/presets.json      [{"id", "name", "kind", "gender", "summary", "description", "reference_description",
                              "seed", "temperature", "file", "text", "seconds", "sha256"}]
  presets/<id>.wav          the reference take (never modified)

Applying a preset fixes it for the narrator or a character exactly like fixing an auditioned take: the WAV is
copied into voices/ and its text becomes the reference, so caches, voice checks and unfixing work the same way.
"""
import json

import fixed_voices
import glossary
import project
from dialogue import NARRATOR

FOLDER = project.PROGRAM / "presets"
CATALOG = FOLDER / "presets.json"


def load():
    return json.loads(CATALOG.read_text(encoding="utf-8")) if CATALOG.exists() else []


def get(preset_id):
    for preset in load():
        if preset["id"] == preset_id:
            return preset
    raise ValueError("This voice preset is not available.")


def apply(preset_id, role):
    """Fix the preset's reference voice for `role` and take over its description and seed for new auditions."""
    preset = get(preset_id)
    take = (FOLDER / preset["file"]).resolve()
    if not take.is_relative_to(FOLDER.resolve()) or not take.is_file():
        raise ValueError("The preset's reference recording is missing. Reinstall the application to restore it.")
    origin = {"preset": preset["id"], "seed": preset["seed"], "temperature": preset["temperature"],
              "design": preset["description"]}
    if role == NARRATOR:
        entry = fixed_voices.fix(NARRATOR, take, preset["text"], origin)
        settings = project.load_settings()
        settings["narrator"]["description"] = preset["description"]  # seed and temperature stay the user's
        project.save_settings(settings)
        fixed_voices.set_sample(NARRATOR, preset["text"])
        return entry
    rows = glossary.load()
    row = next((row for row in rows if row[0] == role), None)
    if row is None:
        raise ValueError(f"{role} is not in the character glossary.")
    entry = fixed_voices.fix(role, take, preset["text"], origin)
    row[6], row[7] = preset["description"], int(preset["seed"])
    if row[2] == "unknown":
        row[2] = preset["gender"]
    glossary.save(rows)
    fixed_voices.set_sample(role, preset["text"])
    return entry
