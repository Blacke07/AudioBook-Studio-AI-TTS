"""Registry previews share the existing project gate and durable transaction writer."""
from fastapi import APIRouter, Body
import character_registry as registry


def create_router(worker):
    router = APIRouter(prefix='/api/character-registry')

    @router.get('')
    def get_registry():
        return registry.snapshot()

    @router.get('/passages')
    def passages(name: str):
        import project
        result = []
        for volume in project.volumes():
            folder = project.WORK / project.safe_name(volume['name'])
            for path in sorted(folder.glob('*/script.json')):
                script = project._read_json(path, {})
                for row in script.get('rows', []):
                    if row[0] == name:
                        result.append(dict(volume=volume['name'], chapter=path.parent.name, text=row[1]))
                        if len(result) == 200:
                            return dict(passages=result, truncated=True)
        return dict(passages=result, truncated=False)

    @router.post('/preview')
    def preview(data: dict = Body(...)):
        result = registry.plan(data)
        return {key:value for key,value in result.items() if key != 'writes'}

    @router.post('/import-preview')
    def import_preview(data: dict = Body(...)):
        return registry.import_document(data.get('text'), data.get('document'))

    @router.put('')
    def save(data: dict = Body(...)):
        with worker.idle_guard():
            return registry.apply(data['request'], data['plan_id'])

    @router.post('/merge-preview')
    def merge_preview(data: dict = Body(...)):
        result = registry.merge_plan(data)
        return {k:v for k,v in result.items() if k != 'writes'}

    @router.put('/merge')
    def merge(data: dict = Body(...)):
        from project_transfer import transact
        with worker.idle_guard():
            result = registry.merge_plan(data['request'])
            if result['plan_id'] != data['plan_id']:
                raise ValueError('Assignments changed. Preview the merge again.')
            transact(result['writes'])
            return registry.snapshot()

    return router
