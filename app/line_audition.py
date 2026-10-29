"""Audition saved chapter passages through the normal audio plan; select a take only on explicit apply."""
from copy import deepcopy
import secrets
from threading import Lock

import numpy as np
import soundfile as sf

import conversion
import emotions
import project
import project_package
import project_transfer
from dialogue import PAUSE, UNASSIGNED
from voice_rules import digest

_lock = Lock()
_pending = {}
MAX_PENDING = 32


def _plan(request):
    allowed = {'volume', 'stem', 'row', 'source_hash', 'script_revision', 'variant'}
    if not isinstance(request, dict) or set(request) - allowed:
        raise ValueError('Invalid line audition request.')
    chapter = project.get_chapter(request.get('volume'), request.get('stem'))
    script = chapter.script()
    if (not script or script.get('source_hash') != project.text_hash(chapter.text())
            or request.get('source_hash') != script['source_hash']
            or request.get('script_revision') != digest(script)):
        raise ValueError('The chapter changed. Refresh it before auditioning or selecting a take.')
    row = request.get('row')
    if type(row) is not int or not 0 <= row < len(script['rows']):
        raise ValueError('Choose an existing text line.')
    if script['rows'][row][0] in (PAUSE, UNASSIGNED):
        raise ValueError('Choose a speaker before auditioning this line.')
    variant = request.get('variant', script['rows'][row][3])
    if type(variant) is not int or not 0 <= variant <= 2147483647:
        raise ValueError('Invalid take number.')
    settings = project.load_settings()
    if not settings['multi_voice']:
        raise ValueError('Enable character voices to audition individual script lines.')
    candidate = deepcopy(script)
    candidate['rows'][row][3] = variant
    # An unrelated unresolved speaker must not prevent auditioning a known speaker. This copy is never saved.
    preview_settings = deepcopy(settings)
    preview_settings['unclear_policy'] = 'narrator'
    chunks, voices, keys = conversion.chapter_plan(chapter, preview_settings, script_override=candidate,
                                                  enforce_status=False)
    selected = [(chunk, key) for chunk, key in zip(chunks, keys) if chunk.line == row]
    if not selected:
        raise ValueError('This line is omitted or joined to the previous spoken passage. Audition that passage instead.')
    if any(chunk.role != script['rows'][row][0] for chunk, _ in selected):
        raise ValueError('The reading plan changed. Refresh the chapter before auditioning.')
    signature = digest([script, row, variant, [(key, chunk.pause_after) for chunk, key in selected]])
    return chapter, script, settings, selected, voices, variant, signature


def audition(request):
    if not _lock.acquire(blocking=False):
        raise ValueError('Another line audition is running. Wait for it to finish.')
    try:
        chapter, script, settings, selected, voices, variant, signature = _plan(request)
        project.PASSAGES.mkdir(parents=True, exist_ok=True)
        references = conversion.fixed_references(voices)
        warnings = set()
        for chunk, key in selected:
            role = chunk.voice_role or chunk.role
            voice, heard = conversion.delivered(chunk, voices[role])
            if chunk.emotion and chunk.emotion != emotions.NEUTRAL and not heard:
                warnings.add(f'No approved {emotions.label(chunk.emotion).lower()} take for {role}. Neutral delivery is used.')
            checked = references
            if heard and voice.mode == conversion.BASE_CLONE and role in references:
                take = conversion.fixed_voices.take(role, chunk.emotion)
                checked = {**references, role: conversion.fixed_voices.FOLDER / take['file']}
            if not conversion.passage_file(key).exists():
                conversion.render_checked(chunk, voice, conversion.temperature_for(settings, role), key, checked)
            qc = project._read_json(conversion.passage_file(key).with_suffix('.qc.json'), {})
            if qc.get('drifting'):
                warnings.add('The automatic voice check flagged this take. Listen for a change in identity.')
        # Revalidate the saved choices before returning a selectable recording.
        if _plan(request)[-1] != signature:
            raise ValueError('The reading choices changed during the audition. Refresh and try again.')
        pauses = [chunk.pause_after if index < len(selected) - 1 else 0
                  for index, (chunk, _) in enumerate(selected)]
        key = digest([(key, pause) for (_, key), pause in zip(selected, pauses)])[:20]
        target = project.PROBES / f'line-{key}.wav'
        project.PROBES.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            temporary = target.with_suffix('.audition-tmp.wav')
            try:
                with sf.SoundFile(temporary, 'w', samplerate=conversion.RATE, channels=1, subtype='PCM_16') as output:
                    for (_, passage), pause in zip(selected, pauses):
                        audio, rate = sf.read(conversion.passage_file(passage), dtype='float32')
                        if rate != conversion.RATE or audio.ndim != 1 or not audio.size or not np.isfinite(audio).all():
                            raise ValueError('The cached passage audio is invalid. Regenerate that passage.')
                        output.write(audio)
                        if pause:
                            output.write(np.zeros(round(pause * rate), dtype='float32'))
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
        token = secrets.token_urlsafe(24)
        while len(_pending) >= MAX_PENDING:
            _pending.pop(next(iter(_pending)))
        _pending[token] = dict(request=deepcopy(request), signature=signature, target=target,
                               keys=[key for _, key in selected], variant=variant)
        first = selected[0][0]
        return dict(token=token, variant=variant, current=variant == script['rows'][request['row']][3],
                    speaker=first.role, read_as=first.voice_role or first.role,
                    emotion=emotions.label(first.emotion or emotions.NEUTRAL),
                    text=' '.join(chunk.text for chunk, _ in selected), warnings=sorted(warnings),
                    path=project.media_token(target), seconds=round(sf.info(target).duration, 2))
    finally:
        _lock.release()


def keep(token):
    record = _pending.get(token) if isinstance(token, str) else None
    if record is None:
        raise ValueError('This audition is no longer available. Listen to the passage again.')
    chapter, script, _, selected, _, variant, signature = _plan(record['request'])
    if signature != record['signature']:
        raise ValueError('The voice or reading choices changed. Audition this passage again before selecting it.')
    if not record['target'].is_file() or any(not conversion.passage_file(key).is_file() for key in record['keys']):
        raise ValueError('The audition audio is no longer available. Generate another preview.')
    after = deepcopy(script)
    row = record['request']['row']
    after['rows'][row][3] = variant
    changed = after != script
    if changed:
        project_package.clean_script(after)
        project_transfer.transact({chapter.script_file.relative_to(project.ROOT).as_posix(): project_package.encoded(after)})
    _pending.pop(token)
    return dict(changed=changed, row=row, variant=variant)
