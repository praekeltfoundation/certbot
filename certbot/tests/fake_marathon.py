import json

from klein import Klein


class FakeMarathon(object):
    def __init__(self):
        self._apps = {}
        self._tasks = {}
        self._app_tasks = {}

    def add_app(self, app, tasks):
        # Store the app
        app_id = app['id']
        assert app_id not in self._apps
        self._apps[app_id] = app

        # Store the tasks
        task_ids = []
        for task in tasks:
            task_id = task['id']
            assert task_id not in self._tasks
            self._tasks[task_id] = task
            task_ids.append(task_id)

        # Store the app id -> task ids mapping
        self._app_tasks[app_id] = task_ids

    def get_apps(self):
        return list(self._apps.values())

    def get_app(self, app_id):
        return self._apps.get(app_id)

    def get_tasks(self):
        return self._tasks.values()

    def get_task(self, task_id):
        return self._tasks.get(task_id)

    def get_app_tasks(self, app_id):
        task_ids = self._app_tasks.get(app_id)
        if task_ids is None:
            return None

        return [self._tasks[task_id] for task_id in task_ids]


class FakeMarathonAPI(object):
    app = Klein()

    def __init__(self, marathon):
        self._marathon = marathon

    @app.route('/v2/apps', methods=['GET'])
    def get_apps(self, request):
        response = {
            'apps': self._marathon.get_apps()
        }
        request.setResponseCode(200)
        return self._json_response(request, response)

    @app.route('/v2/apps/<app_id>', methods=['GET'])
    def get_app(self, request, app_id):
        app = self._marathon.get_app('/' + app_id.rstrip('/'))
        if app is None:
            return self._app_not_found(request, app_id)

        response = {
            'app': app
        }
        request.setResponseCode(200)
        return self._json_response(request, response)

    @app.route('/v2/apps/<app_id>/tasks', methods=['GET'])
    def get_app_tasks(self, request, app_id):
        tasks = self._marathon.get_app_tasks('/' + app_id)
        if tasks is None:
            return self._app_not_found(request, app_id)

        response = {
            'tasks': tasks
        }
        request.setResponseCode(200)
        return self._json_response(request, response)

    def _json_response(self, request, json_obj):
        request.setHeader('Content-Type', 'application/json; charset=utf-8')
        return json.dumps(json_obj).encode('utf-8')

    def _app_not_found(self, request, app_id):
        request.setResponseCode(404)
        return self._json_response(request, {
            'message': 'App \'/%s\' does not exist' % (app_id,)
        })
