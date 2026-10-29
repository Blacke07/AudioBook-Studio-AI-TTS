"""Use the existing project gate and worker guard for line auditions and explicit take selection."""
from urllib.parse import quote
from fastapi import APIRouter, Body
import line_audition


def create_router(worker):
    router = APIRouter(prefix='/api/chapter/audition')

    @router.post('')
    def audition(data: dict = Body(...)):
        with worker.idle_guard('auditioning a line'):
            result = line_audition.audition(data)
            result['url'] = '/api/audio?path=' + quote(result.pop('path'))
            return result

    @router.put('/apply')
    def apply(data: dict = Body(...)):
        with worker.idle_guard('selecting a line take'):
            return line_audition.keep(data.get('token'))

    return router
