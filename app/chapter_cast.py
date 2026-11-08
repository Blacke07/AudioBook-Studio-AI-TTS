"""Previewed speaker replacements; identities and reference voices are never merged implicitly."""
from copy import deepcopy
import hashlib

import glossary
import project
import project_transfer as transfer
import voice_rules
from dialogue import NARRATOR, PAUSE, UNASSIGNED
from project_package import clean_script, encoded


def replace_speakers(script, replacements):
    """Preserve text and takes while replacing identity anchors and their obsolete voice overrides."""
    updated = deepcopy(script)
    for index, target in replacements.items():
        source = updated['rows'][index][0]
        updated['rows'][index][0] = target
        updated.get('attribution', {}).pop(str(index), None)
        for entry in updated.get('spoken_text', {}).get('lines', []):
            if entry.get('row') == index and entry.get('speaker') == source:
                entry['speaker'] = target
    local = updated.get('voice_rules', {})
    overrides = local.get('lines', [])
    removed = sum(entry['row'] in replacements for entry in overrides)
    if overrides:
        local['lines'] = [entry for entry in overrides if entry['row'] not in replacements]
    updated['speakers'] = list(dict.fromkeys(row[0] for row in updated['rows'] if row[0] not in (NARRATOR, PAUSE, UNASSIGNED)))
    return updated, removed


def plan(request):
    source, target, scope = request.get('source'), request.get('target'), request.get('scope')
    names = {row[0] for row in glossary.load()}
    if (not isinstance(source,str) or not isinstance(target,str)
            or source not in names | {NARRATOR, UNASSIGNED} or target not in names | {NARRATOR} or source == target):
        raise ValueError('Choose a different existing character or Narrator.')
    if not isinstance(scope,str) or scope not in ('line', 'chapter', 'everywhere'):
        raise ValueError('Choose this line, this chapter or all analyzed chapters.')
    selected = project.get_chapter(request['volume'], request['stem'])
    original = selected.script()
    if (not original or original['source_hash'] != project.text_hash(selected.text())
            or request.get('source_hash') != original['source_hash']
            or request.get('script_revision') != voice_rules.digest(original)):
        raise ValueError('The chapter changed. Save manual assignments or reload before replacing a speaker.')
    index = request.get('row')
    if scope == 'line' and (type(index) is not int or not 0 <= index < len(original['rows'])
                            or original['rows'][index][0] != source):
        raise ValueError('The selected line changed. Reload the chapter.')
    writes, chapters, total = {}, [], 0
    candidates = [selected] if scope != 'everywhere' else [c for v in project.volumes() for c in project.chapters(v['name'])]
    for chapter in candidates:
        script = chapter.script()
        if not script:
            continue
        indices = [i for i,row in enumerate(script['rows']) if row[0] == source and (scope != 'line' or i == index)]
        if not indices:
            continue
        if script['source_hash'] != project.text_hash(chapter.text()):
            raise ValueError(f'{chapter.stem}: source text changed; review this chapter before a batch replacement.')
        updated, removed = replace_speakers(script, dict.fromkeys(indices, target))
        clean_script(updated)
        writes[chapter.script_file.relative_to(project.ROOT).as_posix()] = encoded(updated)
        total += len(indices)
        chapters.append(dict(volume=chapter.volume, chapter=chapter.stem, lines=len(indices), removed_voice_overrides=removed))
    report = dict(request=request, lines=total, chapters=chapters)
    report['plan_id'] = voice_rules.digest([transfer.state_hash(), report,
                                          {name:hashlib.sha256(content).hexdigest() for name,content in writes.items()}])
    return writes, report


def apply(request, plan_id):
    writes, report = plan(request)
    if report['plan_id'] != plan_id:
        raise ValueError('The project changed after preview. Preview the replacement again.')
    if writes:
        transfer.transact(writes)
    return report
