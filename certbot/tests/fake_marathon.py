import datetime
import json

import treq

from twisted.internet.defer import gatherResults

from klein import Klein


class FakeMarathonData(object):
    def __init__(self):
        self._apps = {}
        self._tasks = {}
        self._app_tasks = {}

    def get_apps(self):
        return self._apps.values()

    def has_app(self, app_id):
        return app_id in self._apps

    def get_app(self, app_id):
        assert app_id in self._apps
        return self._apps[app_id]

    def get_task(self, task_id):
        assert task_id in self._tasks
        return self._tasks[task_id]

    def get_app_tasks(self, app_id):
        assert app_id in self._app_tasks
        task_ids = self._app_tasks[app_id]
        return [self._get_task(task_id) for task_id in task_ids]


class FakeMarathonEventBus(object):
    def __init__(self, client):
        self.client = client

    def subscribe_event(self, callback_url, client_ip):
        return self._emit_event('subscribe_event', {
            'callbackUrl': callback_url,
            'clientIp': client_ip
        })

    def _emit_event(self, event_type, data):
        event = {
            'eventType': event_type,
            'timestamp': datetime.datetime.now().isoformat()
        }
        event.update(data)

        self.client.notify_subscribers(event)

        return event


class FakeMarathonEventBusClient(object):
    def __init__(self, agent):
        self._agent = agent
        self._callback_urls = []

    def add_callback_url(self, callback_url):
        if callback_url not in self._callback_urls:
            self._callback_urls.append(callback_url)

    def get_callback_urls(self):
        return self.callback_urls

    def _notify(self, callback_url, event):
        headers = {'Content-Type': 'application/json'}
        data = json.dumps(event).encode('utf-8')
        return treq.request('POST', callback_url,
                            headers=headers, data=data, agent=self._agent)

    def notify_subscribers(self, event):
        return gatherResults([self._notify(callback_url, event)
                              for callback_url in self._callback_urls])


class FakeMarathon(object):
    def __init__(self, data, event_bus):
        self._data = data
        self._event_bus = event_bus

    def add_event_subscription(self, callback_url, client_ip):
        self._event_bus.client.add_callback_url(callback_url)
        return self._event_bus.subscribe_event(callback_url, client_ip)

    def get_event_subscriptions(self):
        return self._event_bus.client.get_callback_urls()

    def get_apps(self):
        return self._data.get_apps()

    def get_app(self, app_id):
        if self._data.has_app(app_id):
            return self._data.get_app(app_id)
        return None

    def get_app_tasks(self, app_id):
        if self._data.has_app(app_id):
            return self._data.get_app_tasks(app_id)
        return None


class FakeMarathonAPI(object):
    app = Klein()

    def __init__(self, marathon):
        self._marathon = marathon

    @app.route('/v2/eventSubscriptions', methods=['POST'])
    def post_event_subscriptions(self, request):
        assert 'callbackUrl' in request.args
        callback_url = request.args['callbackUrl']

        event = self._marathon.add_event_subscription(
            callback_url, request.getClientIp())

        return self._json_response(event)

    @app.route('/v2/eventSubscriptions')
    def get_event_subscriptions(self, request):
        response = {
            'callbackUrls': self._marathon.get_event_subscriptions()
        }
        request.setResponseCode(200)
        return self._json_response(response)

    @app.route('/v2/apps')
    def get_apps(self, request):
        response = {
            'apps': self._marathon.get_apps()
        }
        request.setResponseCode(200)
        return self._json_response(response)

    @app.route('/v2/app/<app_id>')
    def get_app(self, request, app_id):
        app = self._marathon.get_app(app_id.rstrip('/'))
        if app is None:
            return self._app_not_found(request, app_id)

        response = {
            'app': app
        }
        request.setResponseCode(200)
        return self._json_response(response)

    @app.route('/v2/app/<app_id>/tasks')
    def get_app_tasks(self, request, app_id):
        tasks = self._marathon.get_app_tasks(app_id)
        if tasks is None:
            return self._app_not_found(request, app_id)

        response = {
            'tasks': tasks
        }
        request.setResponseCode(200)
        return self._json_response(response)

    def _json_response(self, request, json_obj):
        request.setHeader('Content-Type', 'application/json')
        return json.dumps(json_obj).encode('utf-8')

    def _app_not_found(self, request, app_id):
        request.setResponseCode(404)
        return self._json_response({
            'message': 'App \'/%s\' does not exist' % (app_id,)
        })
