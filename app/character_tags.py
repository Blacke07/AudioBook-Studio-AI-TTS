"""Name tags reuse aliases, scoped labels and narrative contexts; no second identity registry."""
from copy import deepcopy
import uuid

import character_registry as registry
import glossary
import project


def chapters(volume):
    return [chapter.stem for chapter in project.chapters(volume)]


def _overlaps(left, right, contexts):
    def volumes(label):
        return set(label.get('volumes') or [contexts[key]['volume'] for key in label.get('contexts', []) if key in contexts])
    a_volumes,b_volumes=volumes(left),volumes(right)
    if a_volumes and b_volumes and not a_volumes.intersection(b_volumes):
        return False
    def ranges(label):
        return [contexts[key].get('chapter_range') for key in label.get('contexts', []) if key in contexts]
    ours, theirs = ranges(left), ranges(right)
    if not ours or not theirs or any(bounds is None for bounds in [*ours,*theirs]):
        return True  # Do not guess that a scene-only label is disjoint from this chapter interval.
    for a in ours:
        for b in theirs:
            if a.get('before') and b.get('from') and project.chapter_order(a['before']) <= project.chapter_order(b['from']):
                continue
            if b.get('before') and a.get('from') and project.chapter_order(b['before']) <= project.chapter_order(a['from']):
                continue
            return True
    return False


def plan(request):
    if (not isinstance(request,dict) or set(request)-{'name','alias','volume','from','before','display','revision','original','delete','context_id'}
            or any(key in request and type(request[key]) is not bool for key in ('display','delete'))):
        raise ValueError('Invalid name-tag request.')
    state = registry.snapshot()
    if request.get('revision') != state['revision']:
        raise ValueError('The registry changed. Reopen Name tags.')
    name, alias = request.get('name'), request.get('alias')
    glossary.speaker_name(alias)
    data = deepcopy(state['document'])
    entry = next((c for c in data['characters'] if c['name'] == name), None)
    if entry is None:
        raise ValueError('Choose an existing character.')
    if request.get('delete') is not True and alias.casefold() in {c['name'].casefold() for c in data['characters']}:
        raise ValueError('That name is already an identity. Use Link / merge identity to make it a tag.')
    org, meta = data['organization'], data['organization']['characters'][name]
    scopes = meta.setdefault('alias_scopes', {})
    aliases = entry.setdefault('aliases', [])
    existing = next((a for a in aliases if a.casefold() == alias.casefold()), None)
    original = request.get('original')
    if original and original not in aliases:
        raise ValueError('The tag changed. Reopen Name tags.')
    if existing and existing != original:
        raise ValueError('This character already has that tag. Edit its rule instead.')
    if original:
        aliases.remove(original)
        for key in list(scopes):
            if key.casefold() == original.casefold():
                scopes.pop(key)
        meta['labels'] = [label for label in meta.get('labels', []) if label['label'].casefold() != original.casefold()]
    if request.get('delete') is not True:
        volume = request.get('volume') or ''
        bounds = {key:request[key] for key in ('from', 'before') if request.get(key)}
        context_ids, volumes = [], []
        if volume:
            found = project.get_volume(volume)
            volumes = [project.volume_id(found)]
        if bounds:
            if not volume:
                raise ValueError('Choose a volume for chapter boundaries.')
            available = chapters(volume)
            if any(stem not in available for stem in bounds.values()):
                raise ValueError('A chapter boundary is missing. Choose it again.')
            # A stable ID supplied by the preview is required so re-planning produces exactly the same write.
            key = request.get('context_id')
            if not isinstance(key, str) or not registry.IDENTIFIER.fullmatch(key):
                raise ValueError('Invalid name-tag context ID.')
            if any(c['id'] == key for c in org['contexts']):
                raise ValueError('The name-tag context changed. Reopen the editor.')
            org['contexts'].append(dict(id=key, name=f'{name[:60]}: {alias[:60]} ({key[-8:]})', volume=volumes[0],
                                        description='Chapter-bound name tag.', scenes=[], chapter_range=bounds))
            context_ids = [key]
        aliases.append(alias)
        if volumes or context_ids:
            scopes[alias] = dict(volumes=volumes, contexts=context_ids)
        if request.get('display') is True:
            proposed = dict(label=alias, volumes=volumes, contexts=context_ids)
            for label in meta.get('labels', []):
                if _overlaps(label, proposed, {c['id']:c for c in org['contexts']}):
                    raise ValueError('Another display name overlaps this range. Edit or narrow its rule first.')
            meta.setdefault('labels', []).append(proposed)
    elif not original:
        raise ValueError('Choose an existing name tag to remove.')
    # Remove only this editor's unused generated range contexts, after every alias/label reference is gone.
    used = {key for m in org['characters'].values() for field in ('alias_scopes','labels')
            for item in (m.get(field, {}).values() if field == 'alias_scopes' else m.get(field, []))
            for key in item.get('contexts', [])}
    used.update(key for m in org['characters'].values() for key in m.get('contexts', []))
    org['contexts'] = [c for c in org['contexts'] if not (c['id'].startswith('tag-') and c.get('description') == 'Chapter-bound name tag.'
                                                        and 'chapter_range' in c and c['id'] not in used)]
    return registry.plan(dict(revision=state['revision'], document=data))


def preview(request):
    request = dict(request)
    request['context_id'] = 'tag-' + uuid.uuid4().hex
    result = plan(request)
    # Applying goes through registry.plan using its normalized document, never a second interpretation.
    return {key:value for key,value in result.items() if key != 'writes'}
