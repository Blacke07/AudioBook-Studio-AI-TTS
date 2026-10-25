"""Category defaults and reviewed identities, stored with the existing character glossary."""
from copy import deepcopy
import hashlib
import json
import re

import glossary
import project

UNCATEGORIZED = {'id': 'uncategorized', 'name': 'Uncategorized', 'description': '', 'voice': 'own'}
IDENTIFIER = re.compile('[a-zA-Z0-9_-]{1,80}')
SOURCE_HASH = re.compile('[0-9a-f]{16}')
STATUSES = ('approved', 'provisional', 'needs_review')


def document():
    value = project._read_json(glossary.GLOSSARY_FILE, {'version': 2, 'characters': []})
    return glossary.to_data(glossary.normalize(value), read_as={}) if isinstance(value, list) else value


def volume_key(volume):
    """Stable ID of a registered volume, or None when the name is unknown here."""
    found = project.find_volume(volume)
    return project.volume_id(found) if found else None


def _identifier_list(value, label):
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 200 or len(set(value)) != len(value):
        raise ValueError(f'Invalid {label}.')
    for item in value:
        if not isinstance(item, str) or not IDENTIFIER.fullmatch(item):
            raise ValueError(f'Invalid {label}.')
    return value


def _contexts(value):
    """Narrative contexts: named blocks bound to scenes inside chapters of one volume."""
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 500:
        raise ValueError('Invalid narrative contexts.')
    result, ids, titles = [], set(), set()
    for context in value:
        if not isinstance(context, dict) or set(context) - {'id', 'name', 'volume', 'description', 'scenes'}:
            raise ValueError('Invalid narrative context record.')
        key = context.get('id')
        if not isinstance(key, str) or not IDENTIFIER.fullmatch(key) or key in ids:
            raise ValueError('Invalid or duplicate narrative context ID.')
        name = context.get('name')
        glossary.speaker_name(name, allow_reserved=True)
        if len(name) > 160 or name.casefold() in titles:
            raise ValueError('Context names must be distinct and at most 160 characters.')
        if not isinstance(context.get('volume'), str) or not IDENTIFIER.fullmatch(context['volume']):
            raise ValueError('A narrative context needs a registered volume.')
        if not isinstance(context.get('description', ''), str) or len(context['description']) > 2000:
            raise ValueError('Narrative context description is too long.')
        scenes = context.get('scenes', [])
        if not isinstance(scenes, list) or len(scenes) > 5000:
            raise ValueError('Invalid narrative context scenes.')
        checked = []
        for scene in scenes:
            if not isinstance(scene, dict) or set(scene) - {'chapter', 'first', 'last', 'source_hash'}:
                raise ValueError('Invalid narrative context scene.')
            chapter = scene.get('chapter')
            if not isinstance(chapter, str) or not chapter or len(chapter) > 300:
                raise ValueError('Invalid or missing chapter name.')
            first, last = scene.get('first'), scene.get('last')
            if type(first) is not int or type(last) is not int or first < 0 or last < first:
                raise ValueError('Invalid or missing scene range.')
            digest = scene.get('source_hash')
            if digest is not None and (not isinstance(digest, str) or not SOURCE_HASH.fullmatch(digest)):
                raise ValueError('Invalid narrative context source hash.')
            checked.append(dict(scene, chapter=chapter, first=first, last=last))
        ids.add(key)
        titles.add(name.casefold())
        result.append(dict(context, scenes=checked, description=context.get('description', '')))
    return result


def organization(data=None):
    data = document() if data is None else data
    raw = data.get('organization', {})
    if not isinstance(raw, dict) or set(raw) - {'categories', 'characters', 'allow_provisional', 'contexts'}:
        raise ValueError('Invalid character organization.')
    cats = deepcopy(raw.get('categories', [UNCATEGORIZED]))
    people = deepcopy(raw.get('characters', {}))
    contexts = _contexts(raw.get('contexts'))
    context_ids = {context['id'] for context in contexts}
    if not isinstance(cats, list) or len(cats) > 1000 or not isinstance(people, dict):
        raise ValueError('Invalid categories or character metadata.')
    names = {entry['name'] for entry in data.get('characters', [])}
    aliases = {entry['name']: [str(alias) for alias in entry.get('aliases', [])] for entry in data.get('characters', [])}
    ids, titles = set(), set()
    for cat in cats:
        if not isinstance(cat, dict) or set(cat) != {'id', 'name', 'description', 'voice'}:
            raise ValueError('Invalid category record.')
        key = cat['id']
        if not isinstance(key, str) or not IDENTIFIER.fullmatch(key) or key in ids:
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
        if not isinstance(item, dict) or set(item) - {'category', 'status', 'label', 'scope', 'reason',
                                                      'volumes', 'contexts', 'alias_scopes', 'labels'}:
            raise ValueError('Invalid character metadata.')
        defaults = dict(category='uncategorized', status='approved', label=name, reason='')
        for key, value in defaults.items():
            item.setdefault(key, value)
        if not isinstance(item['category'], str) or item['category'] not in ids or item['status'] not in STATUSES:
            raise ValueError('Choose a valid category and approval status.')
        glossary.speaker_name(item['label'], allow_reserved=True)
        if not isinstance(item['reason'], str) or len(item['reason']) > 2000:
            raise ValueError('Invalid character evidence.')
        if 'scope' in item and (not isinstance(item['scope'], str) or len(item['scope']) > 2000):
            raise ValueError('Invalid character scope.')
        if 'volumes' in item:
            item['volumes'] = _identifier_list(item['volumes'], 'volume membership')
        if 'contexts' in item:
            selected = _identifier_list(item['contexts'], 'narrative contexts')
            if set(selected) - context_ids:
                raise ValueError('A character refers to a missing narrative context.')
            item['contexts'] = selected
        if 'alias_scopes' in item:
            scopes = item['alias_scopes']
            if not isinstance(scopes, dict) or len(scopes) > 500:
                raise ValueError('Invalid alias scopes.')
            known = {alias.casefold() for alias in aliases.get(name, [])}
            checked = {}
            for alias, scope in scopes.items():
                if not isinstance(alias, str) or alias.casefold() not in known:
                    raise ValueError(f'{name}: alias scope for an alias that is not listed.')
                if not isinstance(scope, dict) or set(scope) - {'volumes', 'contexts'}:
                    raise ValueError('Invalid alias scope.')
                volumes = _identifier_list(scope.get('volumes'), 'alias volumes')
                chosen = _identifier_list(scope.get('contexts'), 'alias contexts')
                if set(chosen) - context_ids:
                    raise ValueError('An alias refers to a missing narrative context.')
                checked[alias] = dict(volumes=volumes, contexts=chosen)
            item['alias_scopes'] = checked
        if 'labels' in item:
            labels = item['labels']
            if not isinstance(labels, list) or len(labels) > 200:
                raise ValueError('Invalid display labels.')
            for label in labels:
                if not isinstance(label, dict) or set(label) - {'label', 'volumes', 'contexts'}:
                    raise ValueError('Invalid display label.')
                if not isinstance(label.get('label'), str):
                    raise ValueError('Invalid display label.')
                glossary.speaker_name(label['label'], allow_reserved=True)
                _identifier_list(label.get('volumes'), 'display label volumes')
                chosen = _identifier_list(label.get('contexts'), 'display label contexts')
                if set(chosen) - context_ids:
                    raise ValueError('A display label refers to a missing narrative context.')
    return dict(categories=cats, characters=people, allow_provisional=raw.get('allow_provisional', False),
                contexts=contexts)


def migrate():
    """One-time: stable volume IDs and legacy single-volume scope as explicit membership."""
    project.ensure_volume_ids()
    data = project._read_json(glossary.GLOSSARY_FILE, None)
    if not isinstance(data, dict) or not isinstance(data.get('organization'), dict):
        return False
    by_name = {volume['name']: project.volume_id(volume) for volume in project.volumes()}
    aliases = {entry['name']: entry.get('aliases', []) for entry in data.get('characters', [])
               if isinstance(entry, dict)}
    changed = False
    for name, item in data['organization'].get('characters', {}).items():
        if not isinstance(item, dict):
            continue
        scope = item.get('scope')
        if scope and 'volumes' not in item and scope in by_name:
            item['volumes'] = [by_name[scope]]
            item.pop('scope', None)
            # The old scope kept this character, aliases included, out of other volumes. Membership alone
            # does not restrict analysis, so the aliases keep that limit explicitly.
            scopes = item.setdefault('alias_scopes', {})
            for alias in aliases.get(name, []):
                scopes.setdefault(alias, dict(volumes=[by_name[scope]], contexts=[]))
            if not scopes:
                del item['alias_scopes']
            changed = True
    if changed:
        data['organization'] = organization(data)
        from project_package import encoded
        from project_transfer import transact
        transact({'characters.json': encoded(data)})
    return changed


def inherited(data=None):
    data = document() if data is None else data
    org = organization(data)
    cats = {cat['id']:cat for cat in org['categories']}
    return {name: cats[item['category']]['voice'] for name, item in org['characters'].items()
            if cats[item['category']]['voice'] != 'own'}


def labels(data=None):
    return {name:item['label'] for name,item in organization(data)['characters'].items() if item['label'] != name}


def _scope_matches(scope, volume, context_ids):
    volumes = scope.get('volumes') or []
    contexts = scope.get('contexts') or []
    if volumes and volume not in volumes:
        return False
    if contexts and not set(contexts).intersection(context_ids):
        return False
    return True


def scene_indices(rows):
    """Scene number of every row; a scene break ends the scene it belongs to."""
    from dialogue import PAUSE
    result, scene = [], 0
    for row in rows:
        result.append(scene)
        if row[0] == PAUSE:
            scene += 1
    return result


def _contexts_for(org, volume, chapter, scene, source_hash=None):
    result = []
    if volume is None:
        return result
    for context in org['contexts']:
        if context['volume'] != volume:
            continue
        for binding in context['scenes']:
            if binding['chapter'] != chapter or not binding['first'] <= scene <= binding['last']:
                continue
            expected = binding.get('source_hash')
            if source_hash and expected and expected != source_hash:
                continue
            result.append(context['id'])
            break
    return result


def contexts_for(volume_name, chapter, scene, data=None, source_hash=None):
    """Contexts bound to this scene. A binding made for different text is stale and is not applied."""
    data = document() if data is None else data
    return _contexts_for(organization(data), volume_key(volume_name), chapter, scene, source_hash)


def alias_map(volume_name=None, context_ids=(), data=None):
    """Aliases valid in this volume and context. An alias claimed by two identities stays unresolved."""
    data = document() if data is None else data
    org = organization(data)
    volume = volume_key(volume_name) if volume_name else None
    result = {entry['name'].casefold(): entry['name'] for entry in data.get('characters', [])}
    claims = {}
    for entry in data.get('characters', []):
        name = entry['name']
        scopes = {alias.casefold(): scope for alias, scope in
                  (org['characters'].get(name, {}).get('alias_scopes') or {}).items()}
        for alias in entry.get('aliases', []):
            key = alias.casefold()
            scope = scopes.get(key)
            if scope and not _scope_matches(scope, volume, context_ids):
                continue
            claims.setdefault(key, set()).add(name)
    for alias, names in claims.items():
        if alias in result and result[alias] not in names:
            continue  # a canonical name always wins over a colliding alias
        if len(names) == 1:
            result[alias] = next(iter(names))
    return result


def alias_resolver(volume_name, chapter, source_hash=None, data=None):
    """Per-scene alias map for one chapter; scene context comes from the reviewed bindings."""
    data = document() if data is None else data
    cache = {}

    def resolve(scene):
        if scene not in cache:
            cache[scene] = alias_map(volume_name, contexts_for(volume_name, chapter, scene, data, source_hash), data)
        return cache[scene]

    return resolve


def resolved_label(name, volume_name=None, context_ids=(), data=None, organization_data=None):
    """Video label for this identity in this context; the most specific entry wins."""
    data = document() if data is None else data
    meta = (organization_data or organization(data))['characters'].get(name)
    if not meta:
        return name
    volume = volume_key(volume_name) if volume_name else None
    best = None
    for item in meta.get('labels') or []:
        volumes = item.get('volumes') or []
        contexts = item.get('contexts') or []
        if volumes and (volume is None or volume not in volumes):
            continue
        if contexts and not set(contexts).intersection(context_ids):
            continue
        score = (len(contexts), len(volumes))
        if best is None or score > best[0]:
            best = (score, item['label'])
    return best[1] if best else meta.get('label', name)


def resolved_labels(rows, volume_name, chapter, data=None, source_hash=None, organization_data=None, volume_id=None):
    """All video labels of one chapter, resolved per scene context."""
    data = document() if data is None else data
    org = organization_data or organization(data)
    volume = volume_id if volume_id is not None else volume_key(volume_name)
    scenes = scene_indices(rows)
    cache, result = {}, {}
    for index, row in enumerate(rows):
        contexts = tuple(_contexts_for(org, volume, chapter, scenes[index], source_hash))
        key = (row[0], contexts)
        if key not in cache:
            cache[key] = resolved_label(row[0], volume_name, contexts, data, organization_data=org)
        result[index] = cache[key]
    return result


def check_reading(script, data=None, enforce=True):
    org = organization(data)
    used = {row[0] for row in script['rows']}
    for name, item in org['characters'].items():
        if name in used and (item['status'] == 'needs_review' or
                            item['status'] == 'provisional' and not org['allow_provisional']):
            if enforce:
                raise ValueError(f'{item["label"]}: review this character in Characters before generating audio.')
            return False
    return True


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
    """Register speakers found by an analysis. Known identities are reused; membership is not inferred."""
    current = document()
    org = organization(current)
    existing = {row[0] for row in glossary.load()}
    canonical = {name.casefold(): name for name in existing}
    volume_id = volume_key(volume)
    replacements, added = {}, []
    for entry in entries:
        name = entry[0]
        known = canonical.get(name.casefold())
        if known:
            if known != name:
                replacements[name] = known
            continue
        entry = list(entry)
        added.append(entry)
        canonical[name.casefold()] = name
        proposal = (proposals or {}).get(name, {})
        category = proposal.get('category', 'uncategorized')
        if category not in {c['id'] for c in org['categories']}:
            category = 'uncategorized'
        meta = dict(category=category, status='provisional', label=name,
                    reason=proposal.get('reason') or 'New speaker identified during analysis; review the passages.')
        if volume_id:
            meta['volumes'] = [volume_id]
        org['characters'][name] = meta
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
    volumes = [dict(id=project.volume_id(volume), name=volume['name']) for volume in project.volumes()]
    return dict(document=data, revision=digest(data), reading=global_rules(data),
                fixed={entry['name']:bool(fixed_voices.get(entry['name'])) for entry in data['characters']},
                volumes=volumes)


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
        for key in ('volumes', 'contexts', 'alias_scopes', 'labels', 'scope'):
            meta.pop(key, None)  # volume and context IDs belong to the exporting project
        meta.update(category=category_map[meta['category']], status='needs_review',
                    reason='Imported JSON; no fixed reference recordings were transferred.')
        org['characters'][entry['name']] = meta
        count += 1
    result['organization'] = org
    organization(result)
    return dict(document=result, added=count)


def adopt_contexts(incoming, volumes, existing):
    """Package contexts that belong to a volume of this project. Returns (new contexts, package ID -> local ID).
    A context already present for the same volume and name is reused and keeps its own scenes."""
    ids = {item['id'] for item in existing}
    titles = {item['name'].casefold() for item in existing}
    places = {(item['volume'], item['name'].casefold()): item['id'] for item in existing}
    added, mapping = [], {}
    for context in incoming:
        volume = volumes.get(context['volume'])
        if volume is None:
            continue
        twin = places.get((volume, context['name'].casefold()))
        if twin:
            mapping[context['id']] = twin
            continue
        key, name = context['id'], context['name']
        if key in ids:
            key = 'import-' + hashlib.sha256(json.dumps(context, sort_keys=True).encode('utf-8')).hexdigest()[:16]
        base, number = name, 1
        while name.casefold() in titles:
            name = f'{base[:140]} (imported {number})'
            number += 1
        added.append(dict(deepcopy(context), id=key, name=name, volume=volume))
        ids.add(key)
        titles.add(name.casefold())
        mapping[context['id']] = key
    return added, mapping


def adopt_links(meta, volumes, contexts):
    """Point a package character's volume and context references at this project's IDs. Membership and
    display labels that cannot be mapped are dropped. An alias whose scope cannot be mapped is returned in
    `lost` so the caller removes it: keeping it with an empty scope would make it valid everywhere."""
    meta, lost = deepcopy(meta), []

    def mapped(ids, table):
        return list(dict.fromkeys(table[key] for key in ids or [] if key in table))

    for field, table in (('volumes', volumes), ('contexts', contexts)):
        if field in meta:
            kept = mapped(meta[field], table)
            if kept:
                meta[field] = kept
            else:
                del meta[field]
    scopes = {}
    for alias, scope in (meta.get('alias_scopes') or {}).items():
        place, inside = mapped(scope.get('volumes'), volumes), mapped(scope.get('contexts'), contexts)
        if (scope.get('volumes') and not place) or (scope.get('contexts') and not inside):
            lost.append(alias)
        else:
            scopes[alias] = dict(volumes=place, contexts=inside)
    labels = []
    for label in meta.get('labels') or []:
        place, inside = mapped(label.get('volumes'), volumes), mapped(label.get('contexts'), contexts)
        if (label.get('volumes') and not place) or (label.get('contexts') and not inside):
            continue
        labels.append({'label': label['label'], **({'volumes': place} if place else {}),
                       **({'contexts': inside} if inside else {})})
    for field, value in (('alias_scopes', scopes), ('labels', labels)):
        if value:
            meta[field] = value
        else:
            meta.pop(field, None)
    return meta, lost


def _effective_target(name, data):
    from voice_rules import global_rules
    return global_rules(data).get(name) or name


def _preserve_voices(before, after):
    """A category move must not silently change the voice a listener hears. Freeze the old target."""
    old_org, new_org = organization(before), organization(after)
    kept = {}
    for entry in after['characters']:
        name = entry['name']
        old = old_org['characters'].get(name)
        new = new_org['characters'].get(name)
        if not old or not new or old['category'] == new['category'] or 'read_as' in entry:
            continue
        old_target, new_target = _effective_target(name, before), _effective_target(name, after)
        if old_target != new_target:
            entry['read_as'] = old_target
            kept[name] = old_target
    return kept


def _blocked_names(script, data, organization_data=None):
    org = organization_data or organization(data)
    allow = org['allow_provisional']
    result = []
    for name in {row[0] for row in script.get('rows', [])}:
        item = org['characters'].get(name)
        if item and (item['status'] == 'needs_review' or item['status'] == 'provisional' and not allow):
            result.append(name)
    return sorted(result)


def plan(request):
    from voice_rules import digest, global_rules, _sound
    from project_package import cast_rows, encoded
    before = snapshot()
    if not isinstance(request, dict) or request.get('revision') != before['revision']:
        raise ValueError('The character registry changed. Reload it before applying edits.')
    data = deepcopy(request.get('document'))
    cast_rows(data)
    data['organization'] = organization(data)
    kept = _preserve_voices(before['document'], data)
    if kept:
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
    before_org = organization(before['document'])
    after_org = organization(data)
    for volume in project.volumes():
        key = project.volume_id(volume)
        for chapter in project.chapters(volume['name']):
            script = chapter.script()
            if not script:
                continue
            old_display = resolved_labels(script['rows'], volume['name'], chapter.stem,
                                          before['document'], script.get('source_hash'),
                                          organization_data=before_org, volume_id=key)
            new_display = resolved_labels(script['rows'], volume['name'], chapter.stem,
                                          data, script.get('source_hash'),
                                          organization_data=after_org, volume_id=key)
            changed_labels = old_display != new_display
            resolved = sorted(set(_blocked_names(script, before['document'], before_org))
                              - set(_blocked_names(script, data, after_org)))
            blocked = sorted(set(_blocked_names(script, data, after_org))
                             - set(_blocked_names(script, before['document'], before_org)))
            old_error = None
            try:
                old_sound = _sound(chapter, settings, rows, before['reading'],
                                   registry_document=before['document'], enforce_status=False)['signature']
            except ValueError as failure:
                old_sound, old_error = None, str(failure)
            error = None
            try:
                new_sound = _sound(chapter, settings, cast_rows(data), rules,
                                   registry_document=data, enforce_status=False)['signature']
            except ValueError as failure:
                new_sound, error = None, str(failure)
            audio = bool(old_sound and new_sound and old_sound != new_sound)
            effect = dict(volume=volume['name'], chapter=chapter.stem, audio=audio,
                          video=bool(audio or changed_labels))
            if error and error != old_error:
                effect['error'] = error
            if resolved:
                effect['resolved'] = resolved
            if blocked:
                effect['blocked'] = blocked
            if effect['audio'] or effect['video'] or effect.get('error') or resolved or blocked:
                effects.append(effect)
    normalized = dict(revision=before['revision'], document=data)
    return dict(request=normalized, plan_id=digest([normalized, effects]), effects=effects,
                writes={'characters.json': encoded(data)}, kept=kept)


def _union(left, right):
    """Union of two scope lists where an empty list means "everywhere" and so absorbs the other."""
    return sorted(set(left) | set(right)) if left and right else []


def _merge_reach(target_meta, source_meta, source_aliases, target_had):
    """Where the merged identity is recognised: wherever either identity was. An unrestricted alias or
    membership stays unrestricted; the source's volumes are added to the target's."""
    scopes = {alias.casefold(): (alias, dict(scope)) for alias, scope in (target_meta.get('alias_scopes') or {}).items()}
    for alias in source_aliases:
        key = alias.casefold()
        source_scope = (source_meta.get('alias_scopes') or {})
        source_scope = next((scope for text, scope in source_scope.items() if text.casefold() == key), None)
        if key not in target_had:
            if source_scope:
                scopes[key] = (alias, dict(source_scope))
            continue
        ours = scopes[key][1] if key in scopes else {}
        theirs = source_scope or {}
        merged = {field: _union(ours.get(field, []), theirs.get(field, [])) for field in ('volumes', 'contexts')}
        if merged['volumes'] or merged['contexts']:
            scopes[key] = (scopes[key][0] if key in scopes else alias, merged)
        else:
            scopes.pop(key, None)
    if scopes:
        target_meta['alias_scopes'] = {alias: scope for alias, scope in scopes.values()}
    else:
        target_meta.pop('alias_scopes', None)
    for field in ('volumes', 'contexts'):
        merged = _union(target_meta.get(field, []), source_meta.get(field, []))
        if merged:
            target_meta[field] = merged
        else:
            target_meta.pop(field, None)


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
    target_had = {alias.casefold() for alias in target_entry['aliases']}
    target_entry['aliases'] = list(dict.fromkeys([*target_entry['aliases'], source, source_item['label'], *source_entry['aliases']]))
    if not rename:
        _merge_reach(data['organization']['characters'][target], source_item, source_entry['aliases'], target_had)
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
                audio_path = path.parent / 'audio.json'
                meta = project._read_json(audio_path, None)
                if meta:
                    changed_meta = False
                    for passage in meta.get('passages', []):
                        if passage.get('role') == source:
                            passage['role'] = target
                            changed_meta = True
                        if passage.get('voice_role') == source:
                            passage['voice_role'] = target
                            changed_meta = True
                    if changed_meta:
                        # The passage keys do not contain the identity name: the existing audio stays valid.
                        writes[audio_path.relative_to(project.ROOT).as_posix()] = encoded(meta)
                effects.append(dict(volume=volume['name'], chapter=path.parent.name,
                                    audio=not rename, video=True, identity=True))
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


def _forget_context(data, org, target):
    """Remove a deleted context from every reference without widening any rule. An empty list means
    "everywhere", so an alias or label limited to this context alone is removed, not emptied: it could
    only ever apply inside the context that no longer exists."""
    entries = {entry['name']: entry for entry in data['characters']}
    for name, meta in org['characters'].items():
        if 'contexts' in meta:
            meta['contexts'] = [key for key in meta['contexts'] if key != target]
        scopes = meta.get('alias_scopes')
        if scopes:
            for alias in [alias for alias, scope in scopes.items() if target in (scope.get('contexts') or [])]:
                remaining = [key for key in scopes[alias]['contexts'] if key != target]
                if remaining:
                    scopes[alias]['contexts'] = remaining
                    continue
                del scopes[alias]
                entries[name]['aliases'] = [text for text in entries[name].get('aliases', [])
                                            if text.casefold() != alias.casefold()]
            if not scopes:
                del meta['alias_scopes']
        if 'labels' in meta:
            kept = []
            for label in meta['labels']:
                if target in (label.get('contexts') or []):
                    remaining = [key for key in label['contexts'] if key != target]
                    if not remaining:
                        continue
                    label['contexts'] = remaining
                kept.append(label)
            if kept:
                meta['labels'] = kept
            else:
                del meta['labels']


def context_edit(request):
    """Create, rename or delete one narrative context. Scenes stay reviewed data, never inferred."""
    from project_package import encoded
    from project_transfer import transact
    from voice_rules import digest
    state = snapshot()
    if not isinstance(request, dict) or request.get('revision') != state['revision']:
        raise ValueError('The character registry changed. Reload it before editing contexts.')
    data = state['document']
    org = organization(data)
    action = request.get('action')
    if action == 'create':
        name = request.get('name')
        glossary.speaker_name(name, allow_reserved=True)
        volume = request.get('volume')
        if volume not in {project.volume_id(item) for item in project.volumes()}:
            raise ValueError('Choose a registered volume for the narrative context.')
        if any(context['name'].casefold() == name.casefold() for context in org['contexts']):
            raise ValueError('That context name already exists.')
        key = 'context-' + hashlib.sha256((name + volume).encode('utf-8')).hexdigest()[:10]
        org['contexts'].append(dict(id=key, name=name, volume=volume,
                                    description=str(request.get('description', ''))[:2000], scenes=[]))
        created = key
    elif action == 'update':
        context = next((item for item in org['contexts'] if item['id'] == request.get('id')), None)
        if context is None:
            raise ValueError('Choose an existing narrative context.')
        name = request.get('name', context['name'])
        glossary.speaker_name(name, allow_reserved=True)
        if any(item['id'] != context['id'] and item['name'].casefold() == name.casefold() for item in org['contexts']):
            raise ValueError('That context name already exists.')
        context['name'] = name
        context['description'] = str(request.get('description', context.get('description', '')))[:2000]
        created = context['id']
    elif action == 'delete':
        target = request.get('id')
        if not any(item['id'] == target for item in org['contexts']):
            raise ValueError('Choose an existing narrative context.')
        org['contexts'] = [item for item in org['contexts'] if item['id'] != target]
        _forget_context(data, org, target)
        for context in org['contexts']:
            context.setdefault('scenes', [])
        created = None
    else:
        raise ValueError('Choose a context action.')
    data['organization'] = organization({**data, 'organization': org})
    if digest(data) == state['revision']:
        return state
    transact({'characters.json': encoded(data)})
    return snapshot()


def bind_scene(volume_name, chapter, scene, context_id, source_hash):
    """Bind one reviewed scene to a context. Removing the binding never rewrites chapter assignments."""
    from project_package import encoded
    from project_transfer import transact
    from voice_rules import digest
    if type(scene) is not int or scene < 0:
        raise ValueError('Choose a valid scene.')
    if not isinstance(source_hash, str) or not SOURCE_HASH.fullmatch(source_hash):
        raise ValueError('Analyze the chapter again before setting a context.')
    state = snapshot()
    data = state['document']
    org = organization(data)
    volume = volume_key(volume_name)
    if volume is None:
        raise ValueError('The volume is not registered.')
    target = None
    if context_id:
        target = next((item for item in org['contexts'] if item['id'] == context_id), None)
        if target is None or target['volume'] != volume:
            raise ValueError('Choose a context that belongs to this volume.')
    for context in org['contexts']:
        kept = []
        for binding in context['scenes']:
            if binding['chapter'] != chapter or not binding['first'] <= scene <= binding['last']:
                kept.append(binding)
                continue
            if binding['first'] < scene:
                kept.append({**binding, 'last': scene - 1})
            if binding['last'] > scene:
                kept.append({**binding, 'first': scene + 1})
        context['scenes'] = kept
    if target is not None:
        merged = False
        for binding in target['scenes']:
            if binding['chapter'] != chapter:
                continue
            if binding['last'] == scene - 1:
                binding['last'] = scene
                merged = True
            elif binding['first'] == scene + 1:
                binding['first'] = scene
                merged = True
            if merged:
                break
        if not merged:
            target['scenes'].append(dict(chapter=chapter, first=scene, last=scene, source_hash=source_hash))
        target['scenes'].sort(key=lambda item: (item['chapter'], item['first']))
    data['organization'] = organization({**data, 'organization': org})
    if digest(data) == state['revision']:
        return state
    transact({'characters.json': encoded(data)})
    return snapshot()
