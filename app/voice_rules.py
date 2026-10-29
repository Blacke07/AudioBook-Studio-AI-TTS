"""Voice selection is separate from speaker identity. One resolver and journalled edits."""
import base64
from collections import Counter
from dataclasses import replace
import hashlib
import json

import fixed_voices
import glossary
import project
import project_package as package
import project_transfer as transfer

NARRATOR = 'Narrator'
UNDO = 'projects-state/reports/voice-rule-undo.json'


def digest(value):
    return hashlib.sha256(package.encoded(value)).hexdigest()


def global_rules(data=None):
    if data is None:
        data = project._read_json(glossary.GLOSSARY_FILE, {})
    if isinstance(data, list):
        return {}
    if not isinstance(data, dict):
        raise ValueError('Invalid character voice rules.')
    from character_registry import inherited
    result = inherited(data)
    for entry in data.get('characters', []):
        target = entry.get('read_as')
        if target is not None:
            if not isinstance(target, str):
                raise ValueError('Invalid read_as voice.')
            result[entry['name']] = target
    validate_targets(result, {entry['name'] for entry in data.get('characters', [])}, set(glossary.document_voices(data)))
    return result


def explicit_rules(data=None):
    if data is None:
        data = project._read_json(glossary.GLOSSARY_FILE, {})
    return {entry['name']: entry['read_as'] for entry in data.get('characters', []) if 'read_as' in entry} if isinstance(data, dict) else {}


def validate_targets(rules, speakers, voices):
    """Rules map characters to voices: an own voice, a shared voice or the narrator's."""
    if not isinstance(rules, dict):
        raise ValueError('Invalid character voice rules.')
    for speaker, target in rules.items():
        if speaker not in speakers or target not in voices | {NARRATOR}:
            raise ValueError(f'Unknown speaker or reading voice: {speaker} → {target}. Reset the rule before removing that character.')


def validate_script(script):
    rules = script.get('voice_rules', {})
    if not isinstance(rules, dict) or set(rules) - {'characters', 'lines', 'conflicts'}:
        raise ValueError('Invalid chapter voice rules.')
    characters = rules.get('characters', {})
    if not isinstance(characters, dict):
        raise ValueError('Invalid chapter character rules.')
    for speaker, target in characters.items():
        glossary.speaker_name(speaker)
        glossary.speaker_name(target, allow_reserved=True)
        if target in ('Unassigned', 'Scene break'):
            raise ValueError('Choose a reading voice, not an unresolved role.')
    rows = rules.get('lines', [])
    conflicts = rules.get('conflicts', [])
    if not isinstance(rows, list) or not isinstance(conflicts, list) or len(conflicts) > 100000:
        raise ValueError('Invalid line voice rules.')
    seen = set()
    for entry in rows:
        if (not isinstance(entry, dict) or set(entry) != {'row', 'speaker', 'text_hash', 'source_hash', 'read_as'}
                or type(entry['row']) is not int or not 0 <= entry['row'] < len(script['rows'])
                or entry['row'] in seen):
            raise ValueError('Invalid or duplicate line voice rule.')
        seen.add(entry['row'])
        row = script['rows'][entry['row']]
        glossary.speaker_name(entry['speaker'], allow_reserved=True)
        glossary.speaker_name(entry['read_as'], allow_reserved=True)
        if (entry['speaker'] != row[0] or entry['text_hash'] != digest(row[1])
                or entry['source_hash'] != script['source_hash']
                or entry['speaker'] in ('Unassigned', 'Scene break')
                or entry['read_as'] in ('Unassigned', 'Scene break')):
            raise ValueError('A line voice rule no longer matches its speaker and text. Review the chapter.')
    if any(not isinstance(entry, dict) for entry in conflicts):
        raise ValueError('Invalid voice-rule conflicts.')
    return rules


def reconcile(old, new):
    """Never move a line rule to another text after a split, re-analysis or speaker edit."""
    if not old or not old.get('voice_rules'):
        return new
    rules = json.loads(json.dumps(old['voice_rules']))
    kept = []
    conflicts = list(rules.get('conflicts', []))
    for entry in rules.get('lines', []):
        index = entry['row']
        if (old['source_hash'] == new['source_hash'] and index < len(new['rows'])
                and new['rows'][index][0] == entry['speaker']
                and digest(new['rows'][index][1]) == entry['text_hash']):
            kept.append(entry)
        else:
            conflicts.append(entry)
    rules.update(lines=kept, conflicts=conflicts)
    new['voice_rules'] = rules
    return new


def effective(script, rows, rules=None):
    names = {row[0] for row in rows}
    voices = set(glossary.voice_names(rows))
    general = global_rules() if rules is None else rules
    validate_targets(general, names, voices)
    local = validate_script(script)
    validate_targets(local.get('characters', {}), names, voices)
    if local.get('conflicts'):
        raise ValueError('Voice rules need review after the text or speaker assignments changed. Open Voice rules in this chapter.')
    overrides = {entry['row']:entry['read_as'] for entry in local.get('lines', [])}
    result = {}
    for index, row in enumerate(script['rows']):
        speaker = row[0]
        if speaker in ('Scene break', 'Unassigned'):
            continue
        target = overrides.get(index, local.get('characters', {}).get(speaker, general.get(speaker, speaker)))
        if target not in voices | {NARRATOR}:
            if target == speaker and speaker in names:
                raise ValueError(f'{speaker} has no voice of their own. Choose a reading voice in Characters.')
            raise ValueError('Unknown reading voice: ' + target)
        result[index] = target
    return result


def resolve(lines, script, rows, rules=None):
    mapping = effective(script, rows, rules)
    return [replace(line, voice_role=mapping.get(line.row, line.role)) for line in lines]


def cast(volume=None):
    from character_registry import organization
    org = organization()
    rows = glossary.load()
    general = global_rules()
    counts, chapters = Counter(), {}
    volumes = [project.get_volume(volume)] if volume else project.volumes()
    for item in volumes:
        folder = project.WORK / project.safe_name(item['name'])
        for file in sorted(folder.glob('*/script.json')):
            script = project._read_json(file, {})
            for row in script.get('rows', []):
                if row[0] not in ('Narrator', 'Scene break', 'Unassigned'):
                    counts[row[0]] += 1
                    chapters.setdefault(row[0], set()).add((item['name'], file.parent.name))
    explicit = explicit_rules()
    return {'categories':org['categories'], 'characters':[{'name':row[0], 'read_as':general.get(row[0], row[0]), 'explicit_read_as':explicit.get(row[0]),
                           **org['characters'][row[0]],
                           'lines':counts[row[0]], 'chapters':len(chapters.get(row[0], set())),
                           'fixed':bool(fixed_voices.get(row[0]))} for row in rows],
            'voices':[NARRATOR, *glossary.voice_names(rows)],
            'can_undo':transfer.target(UNDO).is_file()}


def _sound(chapter, settings, rows, rules, script=None, registry_document=None, enforce_status=True):
    from conversion import chapter_plan
    chunks, voices, keys = chapter_plan(chapter, settings, rows, routing_rules=rules, script_override=script, registry_document=registry_document, enforce_status=enforce_status)
    return {'signature':digest([[key,chunk.pause_after] for key,chunk in zip(keys,chunks)]),
            'omitted':[i for i,row in enumerate((script or chapter.script())['rows'])
                       if row[0] == NARRATOR and i not in {chunk.line for chunk in chunks}]}


def plan(request):
    if not isinstance(request, dict) or request.get('scope') not in ('everywhere', 'chapter', 'line', 'clear_conflicts'):
        raise ValueError('Choose Everywhere, Only this chapter or Only this line.')
    request = {key:request[key] for key in ('scope','speaker','read_as','volume','stem','row','source_hash') if key in request}
    rows = glossary.load()
    names = {row[0] for row in rows}
    voices = set(glossary.voice_names(rows))
    general = global_rules()
    changed = dict(general)
    writes = {}
    scope = request['scope']
    speaker = request.get('speaker')
    target = request.get('read_as')
    if scope != 'clear_conflicts':
        if speaker not in names | {NARRATOR} or scope != 'line' and speaker == NARRATOR:
            raise ValueError('Choose an existing character.')
        if target is not None and target not in voices | {NARRATOR}:
            raise ValueError('Choose an existing reading voice.')
    selected = None
    old_script = new_script = None
    if scope == 'everywhere':
        saved_rules = explicit_rules()
        if target is None:
            saved_rules.pop(speaker, None)
        else:
            saved_rules[speaker] = target
        value = glossary.to_data(rows, read_as=saved_rules)
        changed = global_rules(value)
        if package.encoded(value) != package.encoded(glossary.to_data(rows)):
            writes['characters.json'] = package.encoded(value)
    else:
        selected = project.get_chapter(request['volume'], request['stem'])
        old_script = selected.script()
        if not old_script or old_script['source_hash'] != project.text_hash(selected.text()):
            raise ValueError('Analyze or save the current manual assignments first.')
        if request.get('source_hash') != old_script['source_hash']:
            raise ValueError('The chapter changed. Refresh before editing its voice rules.')
        new_script = json.loads(json.dumps(old_script))
        local = new_script.setdefault('voice_rules', {})
        if scope == 'clear_conflicts':
            local['conflicts'] = []
        elif scope == 'chapter':
            mapping = local.setdefault('characters', {})
            if target is None:
                mapping.pop(speaker, None)
            else:
                mapping[speaker] = target
        else:
            index = request.get('row')
            if type(index) is not int or not 0 <= index < len(new_script['rows']) or new_script['rows'][index][0] != speaker:
                raise ValueError('The selected line changed. Refresh the chapter.')
            local['lines'] = [entry for entry in local.get('lines', []) if entry['row'] != index]
            if target is not None:
                local['lines'].append({'row':index, 'speaker':speaker, 'text_hash':digest(new_script['rows'][index][1]),
                                       'source_hash':new_script['source_hash'], 'read_as':target})
        validate_script(new_script)
        relative = selected.script_file.relative_to(project.ROOT).as_posix()
        if new_script != old_script:
            writes[relative] = package.encoded(new_script)
    settings = project.load_settings()
    affected = []
    line_count = 0
    volume_list = [project.get_volume(request['volume'])] if selected else project.volumes()
    for volume in volume_list:
        try:
            chapters = [selected] if selected else project.chapters(volume['name'])
        except ValueError as error:
            affected.append({'volume':volume['name'], 'chapter':None, 'error':str(error)})
            continue
        for chapter in chapters:
            script = chapter.script()
            if not script:
                continue
            after = new_script if selected else script
            relevant = [i for i,row in enumerate(script['rows']) if row[0] == speaker]
            if scope == 'line':
                relevant = [request['row']]
            line_count += len(relevant)
            if not relevant and scope != 'clear_conflicts':
                continue
            try:
                before_sound = _sound(chapter,settings,rows,general)
            except ValueError:
                before_sound = None
            try:
                after_sound = _sound(chapter,settings,rows,changed,after)
                differs = before_sound != after_sound
                affected.append({'volume':volume['name'], 'chapter':chapter.stem, 'changed':differs,
                                 'audio_outdated':differs and chapter.audio_file.exists(),
                                 'video_outdated':differs and chapter.audio_file.exists(),
                                 'tags_read':sorted(set((before_sound or {}).get('omitted',[]))-set(after_sound['omitted'])),
                                 'tags_omitted':sorted(set(after_sound['omitted'])-set((before_sound or {}).get('omitted',[])))})
            except ValueError as error:
                affected.append({'volume':volume['name'], 'chapter':chapter.stem, 'error':str(error)})
    report = {'request':request, 'lines':line_count, 'chapters':affected, 'changes':len(writes)}
    report['plan_id'] = digest([transfer.state_hash(), report, {name:hashlib.sha256(data).hexdigest() for name,data in writes.items()}])
    return writes, report


def apply(request, plan_id):
    writes, report = plan(request)
    if report['plan_id'] != plan_id:
        raise ValueError('The project changed after preview. Preview the voice change again.')
    if writes:
        before = {name:base64.b64encode(transfer.target(name).read_bytes()).decode('ascii')
                  if transfer.target(name).exists() else None for name in writes}
        saved = {'before':before, 'after':{name:hashlib.sha256(data).hexdigest() for name,data in writes.items()}}
        writes[UNDO] = package.encoded(saved)
        transfer.transact(writes)
    return report


def undo():
    saved = project._read_json(transfer.target(UNDO), None)
    if not saved:
        raise ValueError('No voice-rule change to undo.')
    for name, expected in saved['after'].items():
        file = transfer.target(name)
        if not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest() != expected:
            raise ValueError('The edited data changed since the voice rule. Undo refused to overwrite it.')
    writes = {name:base64.b64decode(value, validate=True) if value is not None else None
              for name,value in saved['before'].items()}
    writes[UNDO] = None
    transfer.transact(writes)
    return {'ok':True}
