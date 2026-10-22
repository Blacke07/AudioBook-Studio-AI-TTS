"""Category defaults and reviewed identities, stored with the existing character glossary."""
from copy import deepcopy
import hashlib
import json
import re

import glossary
import project

UNCATEGORIZED = {'id': 'uncategorized', 'name': 'Uncategorized', 'description': '', 'voice': 'own'}


def document():
    value = project._read_json(glossary.GLOSSARY_FILE, {'version': 2, 'characters': []})
    return glossary.to_data(glossary.normalize(value), read_as={}) if isinstance(value, list) else value


def organization(data=None):
    data = document() if data is None else data
    raw = data.get('organization', {})
    if not isinstance(raw, dict) or set(raw) - {'categories', 'characters', 'allow_provisional'}:
        raise ValueError('Invalid character organization.')
    cats = deepcopy(raw.get('categories', [UNCATEGORIZED]))
    people = deepcopy(raw.get('characters', {}))
    if not isinstance(cats, list) or len(cats) > 1000 or not isinstance(people, dict):
        raise ValueError('Invalid categories or character metadata.')
    names = {entry['name'] for entry in data.get('characters', [])}
    ids, titles = set(), set()
    for cat in cats:
        if not isinstance(cat, dict) or set(cat) != {'id', 'name', 'description', 'voice'}:
            raise ValueError('Invalid category record.')
        key = cat['id']
        if not isinstance(key, str) or not re.fullmatch('[a-zA-Z0-9_-]{1,80}', key) or key in ids:
            raise ValueError('Invalid or duplicate category ID.')
        glossary.speaker_name(cat['name'], allow_reserved=True)
        if len(cat['name']) > 160 or cat['name'].casefold() in titles:
            raise ValueError('Category names must be distinct and at most 160 characters.')
        if not isinstance(cat['description'], str) or len(cat['description']) > 2000:
            raise ValueError('Category description is too long.')
        if not isinstance(cat['voice'], str) or cat['voice'] not in names | {'own', 'Narrator'}:
            raise ValueError('Choose an existing shared voice or Narrator.')
        ids.add(key)
        titles.add(cat['name'].casefold())
    if 'uncategorized' not in ids:
        raise ValueError('Keep the Uncategorized category.')
    if type(raw.get('allow_provisional', False)) is not bool:
        raise ValueError('Invalid provisional reading switch.')
    if set(people) - names:
        raise ValueError('Character metadata refers to a missing character.')
    for name in names:
        item = people.setdefault(name, {})
        if not isinstance(item, dict) or set(item) - {'category', 'status', 'label', 'scope', 'reason'}:
            raise ValueError('Invalid character metadata.')
        defaults = dict(category='uncategorized', status='approved', label=name, scope='', reason='')
        for key, value in defaults.items():
            item.setdefault(key, value)
        if not isinstance(item['category'], str) or item['category'] not in ids or item['status'] not in ('approved', 'provisional', 'needs_review'):
            raise ValueError('Choose a valid category and approval status.')
        glossary.speaker_name(item['label'], allow_reserved=True)
        if any(not isinstance(item[k], str) or len(item[k]) > 2000 for k in ('scope', 'reason')):
            raise ValueError('Invalid character scope or evidence.')
    return dict(categories=cats, characters=people, allow_provisional=raw.get('allow_provisional', False))


def inherited(data=None):
    data = document() if data is None else data
    org = organization(data)
    cats = {cat['id']:cat for cat in org['categories']}
    return {name: cats[item['category']]['voice'] for name, item in org['characters'].items()
            if cats[item['category']]['voice'] != 'own'}


def labels(data=None):
    return {name:item['label'] for name,item in organization(data)['characters'].items() if item['label'] != name}


def check_reading(script, data=None):
    org = organization(data)
    used = {row[0] for row in script['rows']}
    for name, item in org['characters'].items():
        if name in used and (item['status'] == 'needs_review' or
                            item['status'] == 'provisional' and not org['allow_provisional']):
            raise ValueError(f'{item["label"]}: review this character in Characters before generating audio.')


def check_category_references(lines, data=None):
    """Only inherited policies require category references; chapter/line overrides win."""
    org = organization(data)
    import fixed_voices
    from voice_rules import explicit_rules
    explicit = explicit_rules(data)
    cats = {c['id']:c for c in org['categories']}
    for line in lines:
        name = line.role
        item = org['characters'].get(name)
        if not item or item['category'] == 'uncategorized' or name in explicit:
            continue
        policy = cats[item['category']]['voice']
        target = name if policy == 'own' else policy
        if target != 'Narrator' and line.voice_role == target and not fixed_voices.get(target):
            raise ValueError(f'{item["label"]}: the category reading voice has no fixed reference. Choose a reference in Voice studio or an explicit reading voice.')


def scoped_rows(rows, volume):
    people = organization()['characters']
    result = [row for row in rows if not people.get(row[0], {}).get('scope') or people[row[0]]['scope'] == volume]
    for index, row in enumerate(result):
        item = people.get(row[0], {})
        if item.get('scope') and item.get('label') != row[0]:
            row = list(row)
            row[1] = ', '.join([row[1], item['label']]).strip(', ')
            result[index] = row
    return result


def register_analysis(rows, entries, volume, proposals=None):
    """New identities are volume-scoped; approved recipes and references are never overwritten."""
    current = document()
    org = organization(current)
    existing = {row[0] for row in glossary.load()}
    replacements = {}
    added = []
    for entry in entries:
        name = entry[0]
        if name in existing:
            continue
        key = name + ' [' + hashlib.sha256(volume.encode('utf-8')).hexdigest()[:10] + ']'
        replacements[name] = key
        if key not in existing:
            entry = list(entry)
            entry[0] = key
            added.append(entry)
            proposal = (proposals or {}).get(name, {})
            category = proposal.get('category', 'uncategorized')
            if category not in {c['id'] for c in org['categories']}:
                category = 'uncategorized'
            org['characters'][key] = dict(category=category, status='provisional', label=name,
                                          scope=volume, reason=proposal.get('reason') or 'New speaker identified during analysis; review the passages.')
    if added:
        current = glossary.to_data(glossary.load() + added)
        for entry in current['characters']:
            if entry['name'] in {row[0] for row in added} and inherited({**current, 'organization': org}).get(entry['name']) is None:
                entry['read_as'] = 'Narrator'
        current['organization'] = org
        # Fill metadata for newly added entries and validate before committing.
        current['organization'] = organization(current)
        from project_transfer import transact
        from project_package import encoded
        transact({'characters.json': encoded(current)})
    return [[replacements.get(row[0], row[0]), *row[1:]] for row in rows], [entry[0] for entry in added]


def snapshot():
    data = document()
    from voice_rules import digest, global_rules
    import fixed_voices
    if 'organization' not in data:
        for entry in data['characters']:
            if 'read_as' not in entry and fixed_voices.get(entry['name']):
                entry['read_as'] = entry['name']
    data['organization'] = organization(data)
    return dict(document=data, revision=digest(data), reading=global_rules(data),
                fixed={entry['name']:bool(fixed_voices.get(entry['name'])) for entry in data['characters']})


def import_document(text, draft):
    from project_package import json_data, cast_rows
    if not isinstance(text, str) or len(text.encode('utf-8')) > 4*1024**2:
        raise ValueError('Character JSON must be under 4 MB.')
    incoming = json_data(text.encode('utf-8'))
    cast_rows(incoming)
    imported_org = organization(incoming)
    cast_rows(draft)
    result = deepcopy(draft)
    org = organization(result)
    known = {c['name'].casefold() for c in result['characters']}
    category_map = {}
    for cat in imported_org['categories']:
        match = next((c for c in org['categories'] if c['name'].casefold() == cat['name'].casefold()), None)
        if match:
            category_map[cat['id']] = match['id']
        else:
            key = 'import-' + hashlib.sha256(json.dumps(cat,sort_keys=True).encode('utf-8')).hexdigest()[:16]
            category_map[cat['id']] = key
            if key not in {c['id'] for c in org['categories']}:
                org['categories'].append({**cat, 'id':key})
    count = 0
    for entry in incoming['characters']:
        if entry['name'].casefold() in known:
            continue
        result['characters'].append(entry)
        known.add(entry['name'].casefold())
        meta = dict(imported_org['characters'][entry['name']])
        meta.update(category=category_map[meta['category']], status='needs_review',
                    reason='Imported JSON; no fixed reference recordings were transferred.')
        org['characters'][entry['name']] = meta
        count += 1
    result['organization'] = org
    organization(result)
    return dict(document=result, added=count)


def plan(request):
    from voice_rules import digest, global_rules, _sound
    from project_package import cast_rows, encoded
    before = snapshot()
    if not isinstance(request, dict) or request.get('revision') != before['revision']:
        raise ValueError('The character registry changed. Reload it before applying edits.')
    data = deepcopy(request.get('document'))
    cast_rows(data)
    data['organization'] = organization(data)
    old_names = {c['name'] for c in before['document']['characters']}
    if not old_names <= {c['name'] for c in data['characters']}:
        raise ValueError('Use New character or Merge for identity changes; edit Video label here.')
    # Quick view edits identity facts and policies, never voice recipes.
    new_by_name = {c['name']:c for c in data['characters']}
    for old in before['document']['characters']:
        new = new_by_name[old['name']]
        for key in ('model', 'custom_voice', 'voice_design', 'seed'):
            if new.get(key) != old.get(key):
                raise ValueError('Edit voice recipes in Voice studio.')
    rules = global_rules(data)
    effects = []
    settings = project.load_settings()
    rows = cast_rows(before['document'])
    old_labels = labels(before['document'])
    new_labels = labels(data)
    for volume in project.volumes():
        for chapter in project.chapters(volume['name']):
            script = chapter.script()
            if not script:
                continue
            used = {row[0] for row in script['rows']}
            changed_labels = any(old_labels.get(n,n) != new_labels.get(n,n) for n in used)
            try:
                audio = _sound(chapter, settings, rows, before['reading'], registry_document=before['document']) != _sound(chapter, settings, cast_rows(data), rules, registry_document=data)
                if audio or changed_labels:
                    effects.append(dict(volume=volume['name'], chapter=chapter.stem, audio=audio, video=audio or changed_labels))
            except ValueError as error:
                effects.append(dict(volume=volume['name'], chapter=chapter.stem, error=str(error)))
    normalized = dict(revision=before['revision'], document=data)
    return dict(request=normalized, plan_id=digest([normalized, effects]), effects=effects,
                writes={'characters.json': encoded(data)})


def merge_plan(request):
    from voice_rules import digest
    from project_package import encoded, clean_script
    before = snapshot()
    source, target = request.get('source'), request.get('target')
    names = {c['name'] for c in before['document']['characters']}
    rename = request.get('rename') is True
    glossary.speaker_name(target)
    if request.get('revision') != before['revision'] or source == target or source not in names or (target not in names and not rename):
        raise ValueError('Choose two existing characters and refresh the registry.')
    if rename and any(target.casefold() == name.casefold() for name in names):
        raise ValueError('That identity already exists. Use Merge instead.')
    data = deepcopy(before['document'])
    source_item = data['organization']['characters'][source]
    if rename:
        entry = deepcopy(next(c for c in data['characters'] if c['name'] == source))
        entry['name'] = target
        data['characters'].append(entry)
        data['organization']['characters'][target] = deepcopy(source_item)
    target_entry = next(c for c in data['characters'] if c['name'] == target)
    source_entry = next(c for c in data['characters'] if c['name'] == source)
    target_entry['aliases'] = list(dict.fromkeys([*target_entry['aliases'], source, source_item['label'], *source_entry['aliases']]))
    data['characters'] = [c for c in data['characters'] if c['name'] != source]
    data['organization']['characters'].pop(source)
    for c in data['characters']:
        if c.get('read_as') == source:
            c['read_as'] = target
    for cat in data['organization']['categories']:
        if cat['voice'] == source:
            cat['voice'] = target
    writes = {'characters.json':encoded(data)}
    if rename:
        import fixed_voices
        references = fixed_voices.load()
        samples = fixed_voices.samples()
        if source in references:
            references[target] = references[source]
            writes['voices/registry.json'] = encoded(references)
        if source in samples:
            samples[target] = samples[source]
            writes['voices/samples.json'] = encoded(samples)
    effects = []
    for volume in project.volumes():
        folder = project.WORK / project.safe_name(volume['name'])
        for path in sorted(folder.glob('*/script.json')):
            original = project._read_json(path, {})
            script = deepcopy(original)
            for row in script.get('rows', []):
                if row[0] == source:
                    row[0] = target
            local = script.get('voice_rules', {})
            chars = local.get('characters', {})
            if source in chars:
                if target in chars and chars[target] != chars[source]:
                    raise ValueError('Conflicting chapter voice rules in ' + path.parent.name + '. Resolve them before merging.')
                chars[target] = chars.pop(source)
            for name in chars:
                if chars[name] == source:
                    chars[name] = target
            for key in ('voice_rules','spoken_text'):
                for group in ('lines','conflicts'):
                    for entry in script.get(key, {}).get(group, []):
                        if entry.get('speaker') == source:
                            entry['speaker'] = target
                        if entry.get('read_as') == source:
                            entry['read_as'] = target
            for key in ('speakers','added'):
                if key in script:
                    script[key] = list(dict.fromkeys(target if n == source else n for n in script[key]))
            if script != original:
                clean_script(script)
                writes[path.relative_to(project.ROOT).as_posix()] = encoded(script)
                effects.append(dict(volume=volume['name'], chapter=path.parent.name, audio=True, video=True))
    organization(data)
    # Voice references are retained; the target's own reference always wins.
    return dict(request=request, effects=effects, plan_id=digest([request, {k:hashlib.sha256(v).hexdigest() for k,v in writes.items()}]), writes=writes)


def apply(request, plan_id):
    from project_transfer import transact
    result = plan(request)
    if result['plan_id'] != plan_id:
        raise ValueError('The preview changed. Preview your edits again.')
    transact(result['writes'])
    return snapshot()
