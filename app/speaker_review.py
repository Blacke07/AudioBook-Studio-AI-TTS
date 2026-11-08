"""A bounded second speaker pass over saved uncertain lines, without resegmenting the chapter."""
from copy import deepcopy
from datetime import datetime

import auto_speakers
import glossary
import project
from chapter_cast import replace_speakers
from dialogue import INNER_VOICE, NARRATOR, PAUSE, UNASSIGNED, segment
from project_package import clean_script
from voice_rules import digest


def pending_ids(script):
    if not script:
        return []
    notes = script.get('attribution', {})
    return [i for i,row in enumerate(script['rows']) if row[0] not in (NARRATOR, PAUSE, INNER_VOICE)
            and (row[0] == UNASSIGNED or notes.get(str(i), {}).get('basis') == 'context')]


def run(chapter, settings, progress, release=True, cancelled=lambda: False):
    from character_registry import document, scoped_rows
    from conversion import LOCK
    from engine_client import close_engine

    original = deepcopy(chapter.script())
    text = chapter.text()
    if not original or original['source_hash'] != project.text_hash(text):
        raise ValueError('Analyze this chapter or save its manual assignments before reviewing speakers.')
    clean_script(original)
    saved_text = ' '.join(' '.join(row[1].split()) for row in original['rows'])
    source_text = ' '.join(' '.join(item.text.split()) for item in segment(text))
    if saved_text != source_text:
        raise ValueError('Saved lines no longer match the manuscript. Review the text before asking Gemma.')
    ids = pending_ids(original)
    if not ids:
        return dict(reviewed=0, changed=0, unresolved=0)
    registry = document()
    known = {entry['name'] for entry in registry['characters']}
    entries = scoped_rows(glossary.load(), chapter.volume)
    with LOCK:
        close_engine()
        rows, _, _, _, _, notes = auto_speakers.attribute(
            text, entries, settings['narrator']['mode'], progress, release=release,
            batch_size=auto_speakers.REPAIR_BATCH, volume=chapter.volume, chapter=chapter.stem,
            source_hash=original['source_hash'], review_rows=original['rows'], review_ids=ids)
    if cancelled():
        raise InterruptedError('Speaker review stopped. Saved assignments were kept.')
    if (digest(chapter.script()) != digest(original) or chapter.text() != text or digest(document()) != digest(registry)):
        raise ValueError('The chapter or characters changed during speaker review. No results were saved; run it again.')
    replacements = {}
    for index in ids:
        if rows[index][0] not in known:
            rows[index][0] = UNASSIGNED  # Creating identities and voices stays an explicit separate decision.
        if rows[index][0] != original['rows'][index][0]:
            replacements[index] = rows[index][0]
    updated, _ = replace_speakers(original, replacements)
    attribution = updated.setdefault('attribution', {})
    for index in ids:
        attribution.pop(str(index), None)
        if rows[index][0] == UNASSIGNED:
            attribution[str(index)] = {'basis':'unclear', 'reason':'Second pass could not identify an existing character reliably.'}
        elif str(index) in notes:
            attribution[str(index)] = notes[str(index)]
    result = dict(reviewed=len(ids), changed=len(replacements), unresolved=sum(rows[i][0] == UNASSIGNED for i in ids))
    updated['report'] = (original.get('report', '') + '\nSpeaker review ' + datetime.now().isoformat(timespec='seconds')
                         + f": {result['reviewed']} rechecked with adjacent context; {result['changed']} changed; "
                         + f"{result['unresolved']} still unassigned. Fixed assignments, text and voice references were kept.")
    chapter.save_script(clean_script(updated))
    if chapter.error_file.exists() and chapter.error_file.read_text(encoding='utf-8').startswith('speaker review:'):
        chapter.error_file.unlink()
    return result
