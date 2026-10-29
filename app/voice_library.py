"""Shared voices are voices, not characters. Older versions kept them as characters of one category; this
moves them into the voice list (once, on start, and when an older package is imported) and drops the recipes
nobody reads with. Names, recipes, approved takes and variations stay as they were, so no passage changes."""
from copy import deepcopy
from datetime import datetime
import shutil

import fixed_voices
import glossary
import project

SHARED = 'shared-voices'   # the category the older versions kept the shared voices in
RECIPE = ('model', 'custom_voice', 'voice_design', 'seed')


def separate(data):
    """The members of the old shared-voices category leave the characters and become voices. Whoever read with
    them still does: a reading rule names a voice, and the voice keeps the name."""
    if not isinstance(data, dict) or not isinstance(data.get('organization'), dict):
        return data
    org = data['organization']
    people = org.get('characters', {}) if isinstance(org.get('characters'), dict) else {}
    members = {name for name, meta in people.items() if isinstance(meta, dict) and meta.get('category') == SHARED}
    categories = org.get('categories', [])
    if not members and not any(isinstance(cat, dict) and cat.get('id') == SHARED for cat in categories):
        return data
    data = deepcopy(data)
    org = data['organization']
    voices = data.setdefault('voices', [])
    for entry in data.get('characters', []):
        if isinstance(entry, dict) and entry.get('name') in members:
            voices.append({key: entry[key] for key in ('name', 'gender', 'note', *RECIPE) if key in entry})
    data['characters'] = [entry for entry in data.get('characters', [])
                          if not (isinstance(entry, dict) and entry.get('name') in members)]
    org['characters'] = {name: meta for name, meta in org.get('characters', {}).items() if name not in members}
    org['categories'] = [cat for cat in categories if not (isinstance(cat, dict) and cat.get('id') == SHARED)]
    return data


def chapter_targets():
    """Voices chosen by chapter and line rules in every analyzed chapter."""
    result = set()
    for volume in project.volumes():
        folder = project.WORK / project.safe_name(volume['name'])
        for file in folder.glob('*/script.json'):
            rules = project._read_json(file, {}).get('voice_rules', {})
            if not isinstance(rules, dict):
                continue
            result.update((rules.get('characters') or {}).values())
            result.update(entry.get('read_as') for entry in [*rules.get('lines', []), *rules.get('conflicts', [])]
                          if isinstance(entry, dict))
    return result


def drop_unused(data, targets):
    """A character that reads with another voice everywhere keeps no recipe of its own, unless something reads
    with that recipe: another character, a category, a chapter or line rule, or an approved take."""
    from voice_rules import global_rules
    reading = global_rules(data)
    used = set(reading.values()) | set(targets)
    used |= {cat['voice'] for cat in data.get('organization', {}).get('categories', []) if isinstance(cat, dict)}
    fixed = fixed_voices.load()
    data = deepcopy(data)
    for entry in data.get('characters', []):
        name = entry['name']
        if reading.get(name, name) != name and name not in used and name not in fixed:
            for key in RECIPE:
                entry.pop(key, None)
    return data


def backup():
    folder = project.backups_folder() / ('voice-library-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
    folder.mkdir(parents=True, exist_ok=True)
    for file in (glossary.GLOSSARY_FILE, fixed_voices.REGISTRY, fixed_voices.SAMPLES, project.SETTINGS_FILE):
        if file.exists():
            shutil.copy2(file, folder / file.name)
    return folder


def migrate():
    """Once: a glossary without a voice list gets one. Returns the backup folder, or None when nothing ran."""
    data = project._read_json(glossary.GLOSSARY_FILE, None)
    if not isinstance(data, dict) or 'voices' in data:
        return None
    result = drop_unused(separate(data), chapter_targets())
    result = {'version': 3, 'voices': result.get('voices', []), **{k: v for k, v in result.items() if k not in ('version', 'voices')}}
    from project_package import cast_rows, encoded
    from project_transfer import transact
    cast_rows(result)
    folder = backup()
    transact({'characters.json': encoded(result)})
    return folder
