import json

from datetime import datetime

from klein import Klein

from marathon_acme.clients import get_single_header
from marathon_acme.server import write_request_json


def marathon_timestamp(time=datetime.utcnow()):
    """
    Make a Marathon/JodaTime-like timestamp string in ISO8601 format with
    milliseconds for the current time in UTC.
    """
    return time.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'


class FakeMarathon(object):
    def __init__(self):
        self._apps = {}
        self._tasks = {}
        self._app_tasks = {}
        self.event_callbacks = []

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

    def get_app_tasks(self, app_id):
        task_ids = self._app_tasks.get(app_id)
        if task_ids is None:
            return None

        return [self._tasks[task_id] for task_id in task_ids]

    def attach_event_stream(self, callback, remote_address=None):
        assert callback not in self.event_callbacks

        print('attaching event stream')
        self.event_callbacks.append(callback)
        self.trigger_event('event_stream_attached',
                           remoteAddress=remote_address)

    def detach_event_stream(self, callback, remote_address=None):
        assert callback in self.event_callbacks

        print('detaching event stream')
        self.event_callbacks.remove(callback)
        self.trigger_event('event_stream_detached',
                           remoteAddress=remote_address)

    def trigger_event(self, event_type, **kwargs):
        event = {
            'eventType': event_type,
            'timestamp': marathon_timestamp()
        }
        event.update(kwargs)

        for callback in self.event_callbacks:
            callback(event)


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
        write_request_json(request, response)

    @app.route('/v2/apps/<app_id>', methods=['GET'])
    def get_app(self, request, app_id):
        app = self._marathon.get_app('/' + app_id.rstrip('/'))
        if app is None:
            self._app_not_found(request, app_id)
            return

        response = {
            'app': app
        }
        request.setResponseCode(200)
        write_request_json(request, response)

    @app.route('/v2/apps/<app_id>/tasks', methods=['GET'])
    def get_app_tasks(self, request, app_id):
        tasks = self._marathon.get_app_tasks('/' + app_id)
        if tasks is None:
            self._app_not_found(request, app_id)
            return

        response = {
            'tasks': tasks
        }
        request.setResponseCode(200)
        write_request_json(request, response)

    def _app_not_found(self, request, app_id):
        request.setResponseCode(404)
        write_request_json(request, {
            'message': "App '/%s' does not exist" % (app_id,)
        })

    @app.route('/v2/events', methods=['GET'])
    def get_events(self, request):
        assert (get_single_header(request.requestHeaders, 'Accept') ==
                'text/event-stream')

        request.setResponseCode(200)
        request.setHeader('Content-Type', 'text/event-stream')

        def callback(event):
            _write_request_event(request, event)
        self._marathon.attach_event_stream(callback, request.getClientIP())

        finished = request.notifyFinish()
        finished.addErrback(
            lambda _: self._marathon.detach_event_stream(
                callback, request.getClientIP()))

        return finished


def _write_request_event(request, event):
    event_type = event['eventType']
    request.write(b'event: %s\n' % (event_type.encode('utf-8'),))
    request.write(b'data: %s\n' % (json.dumps(event).encode('utf-8'),))
    request.write(b'\n')
