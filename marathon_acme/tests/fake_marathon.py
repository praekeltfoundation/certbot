from datetime import datetime

from klein import Klein

from twisted.internet.defer import DeferredQueue

from uritools import urisplit

from marathon_acme.clients import JsonClient
from marathon_acme.server import write_request_json


def marathon_timestamp(time=datetime.utcnow()):
    """
    Make a Marathon/JodaTime-like timestamp string in ISO8601 format with
    milliseconds for the current time in UTC.
    """
    return time.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'


class FakeMarathon(object):
    def __init__(self, agent):
        self._apps = {}
        self._tasks = {}
        self._app_tasks = {}
        self.event_subscriptions = []

        self._event_bus_client = JsonClient(agent=agent)
        self.event_bus_requests = DeferredQueue()

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

    def update_task_status(self, task_id, status):
        assert task_id in self._tasks
        task = self._tasks[task_id]

        # Update the task status
        task['status'] = status

        # Trigger an event
        self.trigger_event(
            'status_update_event',
            taskId=task_id,
            taskStatus=status,
            appId=task['appId'],
            slaveId=task['slaveId'],
            host=task['host'],
            ports=task['ports'],
            version=task['version'])

    def get_event_subscriptions(self):
        return self.event_subscriptions

    def add_event_subscription(self, callback_url, client_ip=None):
        if callback_url not in self.event_subscriptions:
            self.event_subscriptions.append(callback_url)

        return self.trigger_event(
            'subscribe_event', callbackUrl=callback_url, clientIp=client_ip)

    def remove_event_subscription(self, callback_url, client_ip=None):
        if callback_url in self.event_subscriptions:
            self.event_subscriptions.remove(callback_url)

        return self.trigger_event(
            'unsubscribe_event', callbackUrl=callback_url, clientIp=client_ip)

    def trigger_event(self, event_type, **kwargs):
        event = {
            'eventType': event_type,
            'timestamp': marathon_timestamp()
        }
        event.update(kwargs)

        # Notify event subscribers
        for callback_url in self.event_subscriptions:
            self.event_bus_requests.put(self._event_bus_client.request(
                'POST', callback_url, json_data=event))

        return event


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

    @app.route('/v2/eventSubscriptions', methods=['GET'])
    def get_event_subscriptions(self, request):
        response = {
            'callbackUrls': self._marathon.get_event_subscriptions()
        }
        request.setResponseCode(200)
        write_request_json(request, response)

    @app.route('/v2/eventSubscriptions', methods=['POST'])
    def post_event_subscriptions(self, request):
        query = urisplit(request.uri).getquerydict()

        assert 'callbackUrl' in query
        assert query['callbackUrl']

        callback_url = query['callbackUrl'][0]
        event = self._marathon.add_event_subscription(
            callback_url, request.getClientIP())

        request.setResponseCode(200)
        write_request_json(request, event)

    @app.route('/v2/eventSubscriptions', methods=['DELETE'])
    def delete_event_subscriptions(self, request):
        query = urisplit(request.uri).getquerydict()

        assert 'callbackUrl' in query
        assert query['callbackUrl']

        callback_url = query['callbackUrl'][0]
        event = self._marathon.remove_event_subscription(
            callback_url, request.getClientIP())

        request.setResponseCode(200)
        write_request_json(request, event)

    def _app_not_found(self, request, app_id):
        request.setResponseCode(404)
        write_request_json(request, {
            'message': "App '/%s' does not exist" % (app_id,)
        })
