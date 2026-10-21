"""Local project dialogs and short-lived preview tokens. No browser file uploads."""
from datetime import datetime
import hashlib
from pathlib import Path
from tempfile import NamedTemporaryFile
import threading
import time
import uuid

from fastapi import APIRouter, Body
from starlette.concurrency import run_in_threadpool
import project
import project_package as package
import project_transfer as transfer


def native_dialog(kind):
    result = {}

    def ask():
        import tkinter
        from tkinter import filedialog
        root = None
        try:
            root = tkinter.Tk()
            root.withdraw()
            root.attributes('-topmost', True)
            options = dict(parent=root, filetypes=[('AudioBook Studio project','*.abstudio')])
            result['path'] = (filedialog.asksaveasfilename(title='Export project', defaultextension='.abstudio', confirmoverwrite=False,
                initialfile=f'AudioBook-project-{datetime.now():%Y-%m-%d}.abstudio', **options) if kind=='save'
                else filedialog.askopenfilename(title='Open project', **options))
        except Exception as error:
            result['error'] = error
        finally:
            if root is not None:
                root.destroy()
    thread = threading.Thread(target=ask)
    thread.start()
    thread.join()
    if 'error' in result:
        raise RuntimeError('Could not open the native file dialog: '+str(result['error']))
    return Path(result['path']).resolve() if result.get('path') else None


def digest(path):
    if not path.is_file():
        return None
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(8*1024**2),b''):
            result.update(block)
    return result.hexdigest()


def create_router(worker, access):
    router = APIRouter(prefix='/api/project')
    sessions = {}
    sessions_lock = threading.Lock()

    def remember(data):
        with sessions_lock:
            now = time.monotonic()
            for token in list(sessions):
                if now-sessions[token]['time']>1800:
                    del sessions[token]
            while len(sessions)>=8:
                del sessions[next(iter(sessions))]
            token = uuid.uuid4().hex
            sessions[token] = {**data,'time':now}
        return token

    def session(token, mode):
        with sessions_lock:
            value = sessions.get(token)
        if not value or value['mode']!=mode or time.monotonic()-value['time']>1800:
            raise ValueError('This preview expired. Preview the project again.')
        return value

    def consumed(token):
        with sessions_lock:
            sessions.pop(token, None)

    async def run(action, write=False, idle=True):
        def perform():
            if not idle:
                return action()
            with worker.idle_guard():
                return action()
        async with access().hold(write=write):
            return await run_in_threadpool(perform)

    async def choose(kind):
        # A dialog can stay open indefinitely: it must not hold an API gate or worker reservation.
        with worker.idle_guard():
            pass
        return await run_in_threadpool(native_dialog,kind)

    @router.get('')
    async def info():
        return await run(transfer.history,idle=False)

    @router.post('/export/preview')
    async def export_preview(data: dict = Body(...)):
        path = await choose('save')
        if path is None:
            return {'cancelled':True}
        def prepare():
            parts = data.get('parts',[])
            files = package.collect(parts)
            preview = package.summary(package.parse_files(files))
            if path.suffix.casefold()!='.abstudio':
                raise ValueError('Use the .abstudio extension.')
            previous = digest(path)
            token = remember({'mode':'export','path':path,'previous':previous,'parts':parts,
                              'state':transfer.state_hash()})
            return {**preview,'token':token,'path':str(path),'exists':previous is not None}
        return await run(prepare)

    @router.post('/export/apply')
    async def export_apply(data: dict = Body(...)):
        if data.get('confirm') is not True:
            raise ValueError('Confirm the export preview first.')
        def apply():
            saved = session(data.get('token'), 'export')
            path = saved['path']
            if transfer.state_hash()!=saved['state'] or digest(path)!=saved['previous']:
                raise ValueError('The project or destination changed. Preview the export again.')
            if saved['previous'] is not None and data.get('overwrite') is not True:
                raise ValueError('Confirm replacement of the existing project file.')
            files = package.collect(saved['parts'])
            with NamedTemporaryFile(prefix='project-',suffix='.tmp',dir=path.parent,delete=False) as stream:
                temporary = Path(stream.name)
            try:
                package.write_package(temporary,files)
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
            consumed(data['token'])
            return {'message':'Project exported.','path':str(path)}
        return await run(apply)

    @router.post('/import/preview')
    async def import_preview(data: dict = Body(...)):
        path = None
        if not data.get('token'):
            path = await choose('open')
            if path is None:
                return {'cancelled':True}
        def prepare():
            incoming_path = path
            if data.get('token'):
                old = session(data['token'],'import')
                incoming_path = old['path']
                before = old['digest']
                if digest(incoming_path)!=before:
                    raise ValueError('The project archive changed. Open it again.')
            else:
                before = digest(incoming_path)
            incoming = package.read_package(incoming_path)
            if digest(incoming_path)!=before:
                raise ValueError('The project archive changed while reading it.')
            choices = data.get('choices',{})
            _, preview = transfer.plan(incoming,choices)
            token = remember({'mode':'import','path':incoming_path,'digest':before,'choices':choices,
                              'state':transfer.state_hash(),'plan':preview})
            return {**preview,'summary':package.summary(incoming),'token':token,'path':str(incoming_path)}
        return await run(prepare)

    @router.post('/import/apply')
    async def import_apply(data: dict = Body(...)):
        if data.get('confirm') is not True:
            raise ValueError('Confirm the import preview first.')
        def apply():
            saved = session(data.get('token'),'import')
            if digest(saved['path'])!=saved['digest']:
                raise ValueError('The project archive changed. Preview it again.')
            incoming = package.read_package(saved['path'])
            result = transfer.apply(incoming,saved['choices'],saved['state'],saved['plan'])
            consumed(data['token'])
            return result
        return await run(apply,write=True)

    @router.post('/undo/preview')
    async def undo_preview():
        def prepare():
            last = transfer.history()['last_import']
            if not last:
                raise ValueError('There is no import to undo.')
            return {'token':remember({'mode':'undo','state':transfer.state_hash()}),'backup':last['backup']}
        return await run(prepare)

    @router.post('/undo/apply')
    async def undo_apply(data: dict = Body(...)):
        if data.get('confirm') is not True:
            raise ValueError('Confirm restoration of the backup first.')
        def apply():
            saved = session(data.get('token'),'undo')
            if transfer.state_hash()!=saved['state']:
                raise ValueError('The project changed. Preview Undo again.')
            result = transfer.undo()
            consumed(data['token'])
            return result
        return await run(apply,write=True)
    return router
