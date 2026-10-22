"""HTTP boundary for previewed voice rules and auditions, using the existing project gate."""
from fastapi import APIRouter, Body
import fixed_voices
import glossary
import project
import voice_rules


def create_router(worker):
    router = APIRouter(prefix='/api/voice-rules')

    @router.get('/cast')
    def cast(volume: str | None = None):
        return voice_rules.cast(volume)

    @router.post('/preview')
    def preview(data: dict = Body(...)):
        return voice_rules.plan(data)[1]

    @router.put('/apply')
    def apply(data: dict = Body(...)):
        with worker.idle_guard('changing reading voices'):
            return voice_rules.apply(data['request'], data['plan_id'])

    @router.delete('/undo')
    def undo():
        with worker.idle_guard('undoing a voice rule'):
            return voice_rules.undo()

    @router.post('/compare')
    def compare(data: dict = Body(...)):
        from conversion import narrator_voice, preview_voice
        from dialogue import read_cast
        from voices import MODEL_NAMES
        speaker = data.get('speaker')
        rows = glossary.load()
        if speaker not in {row[0] for row in rows}:
            raise ValueError('Choose an existing character.')
        text = str(data.get('text') or '').strip()
        if not 1 <= len(text) <= 600:
            raise ValueError('Enter 1–600 characters to compare.')
        if not fixed_voices.get(speaker) or not fixed_voices.get('Narrator'):
            raise ValueError('Fix both the character and narrator voices before comparing them.')
        with worker.idle_guard('comparing reading voices'):
            settings = project.load_settings()
            narrator = narrator_voice(settings)
            voices = read_cast(rows,MODEL_NAMES[settings['narrator']['mode']],narrator,{speaker})
            result = []
            for label, voice in (('Own voice',voices[speaker]),('Narrator',narrator)):
                path = preview_voice(voice,text,settings['narrator']['temperature'])
                from urllib.parse import quote
                result.append({'label':label,'url':'/api/audio?path='+quote(project.media_token(path))})
            return {'takes':result}

    return router
