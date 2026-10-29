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


def create_own_voice(request):
    """Create an explicitly requested recipe without replacing a reference or changing reading rules."""
    from character_registry import document, snapshot
    from project_package import cast_rows, encoded
    from project_transfer import transact
    from voice_rules import global_rules
    from voices import MODEL_NAMES, custom_speaker, voice_parameters

    fields = {'role', 'revision', 'model', 'design', 'custom', 'seed'}
    if not isinstance(request, dict) or set(request) != fields:
        raise ValueError('Invalid own voice request.')
    role = glossary.speaker_name(request['role'])
    if request['revision'] != snapshot()['revision']:
        raise ValueError('Characters changed. Close this dialog and reopen Create own voice.')
    data = deepcopy(document())
    entry = next((item for item in data['characters'] if item['name'] == role), None)
    if entry is None:
        raise ValueError('Choose an existing character, not a shared voice.')
    if entry.get('custom_voice') or entry.get('voice_design') or fixed_voices.get(role):
        raise ValueError('This character already has an own voice. Edit it in Voice creation.')
    model, seed = request['model'], request['seed']
    if not isinstance(model, str) or model not in MODEL_NAMES:
        raise ValueError('Choose VoiceDesign or CustomVoice.')
    if type(seed) is not int or not 0 <= seed <= 2147483647:
        raise ValueError('Enter a whole-number seed between 0 and 2147483647.')
    if not isinstance(request['design'], str) or not isinstance(request['custom'], str):
        raise ValueError('Enter a voice description or choose a built-in speaker.')
    design = request['design'].strip() if model == 'VoiceDesign' else ''
    custom = custom_speaker(request['custom']) if model == 'CustomVoice' else ''
    voice_parameters(MODEL_NAMES[model], custom or '', design, '')
    reading = global_rules(data)
    entry.update(model=model, custom_voice=custom, voice_design=design, seed=seed)
    cast_rows(data)
    if global_rules(data) != reading:
        raise ValueError('Creating a recipe must not change the reading rules.')
    transact({'characters.json': encoded(data)})
    return {'role': role, 'read_as': reading.get(role, role), 'created': True}
