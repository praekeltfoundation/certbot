import json

import treq

from testtools.matchers import Equals

from twisted.internet.defer import inlineCallbacks
from twisted.protocols.loopback import _LoopbackAddress
from twisted.web.server import Site

from txfake import FakeServer

from uritools import uricompose

from marathon_acme.tests.fake_marathon import FakeMarathon, FakeMarathonAPI
from marathon_acme.tests.helpers import FakeServerAgent, TestCase
from marathon_acme.tests.matchers import IsJsonResponseWithCode


class TestFakeMarathonAPI(TestCase):

    def setUp(self):
        super(TestFakeMarathonAPI, self).setUp()

        self.marathon = FakeMarathon()
        self.marathon_api = FakeMarathonAPI(self.marathon)

        # FIXME: Current released version (15.3.1) of Klein expects the host to
        # have a 'port' attribute which in the case of Twisted's UNIX localhost
        # host there isn't. Monkeypatch on a port to get things to work.
        # https://github.com/twisted/klein/issues/102
        _LoopbackAddress.port = 7000

        fake_server = FakeServer(Site(self.marathon_api.app.resource()))
        self.agent = FakeServerAgent(fake_server.endpoint)

    def request(self, method, path, query=None, json_data=None):
        url = uricompose('http', 'www.example.com', path, query)
        data = None
        headers = {'Accept': 'application/json'}

        # Add JSON body if there is JSON data
        if json_data is not None:
            data = json.dumps(json_data).encode('utf-8')
            headers['Content-Type'] = 'application/json'

        return treq.request(
            method, url, data=data, headers=headers, agent=self.agent)

    @inlineCallbacks
    def test_get_apps_empty(self):
        """
        When the list of apps is requested and there are no apps, an empty list
        of apps should be returned.
        """
        response = yield self.request('GET', '/v2/apps')
        self.assertThat(response, IsJsonResponseWithCode(200))

        response_json = yield response.json()
        self.assertThat(response_json, Equals({'apps': []}))

    @inlineCallbacks
    def test_get_apps(self):
        """
        When the list of apps is requested, a list of apps added via add_app()
        should be returned.
        """
        app = {
            'id': '/my-app_1',
            'cmd': 'sleep 50'
        }
        tasks = [
            {
                "host": "host1.local",
                "id": "my-app_1-1396592790353",
                "ports": []
            },
            {
                "host": "host2.local",
                "id": "my-app_1-1396592784349",
                "ports": []
            }
        ]
        self.marathon.add_app(app, tasks)

        response = yield self.request('GET', '/v2/apps')
        self.assertThat(response, IsJsonResponseWithCode(200))

        response_json = yield response.json()
        self.assertThat(response_json, Equals({'apps': [app]}))

    @inlineCallbacks
    def test_get_app(self):
        """
        When a specific app is requested, the app data should be returned.
        """
        app = {
            'id': '/my-app_1',
            'cmd': 'sleep 50'
        }
        tasks = [
            {
                "host": "host1.local",
                "id": "my-app_1-1396592790353",
                "ports": []
            },
            {
                "host": "host2.local",
                "id": "my-app_1-1396592784349",
                "ports": []
            }
        ]
        self.marathon.add_app(app, tasks)

        response = yield self.request('GET', '/v2/apps/my-app_1')
        self.assertThat(response, IsJsonResponseWithCode(200))

        response_json = yield response.json()
        self.assertThat(response_json, Equals({'app': app}))

    @inlineCallbacks
    def test_get_app_not_found(self):
        """
        When a specific app is requested but the app does not exist, a 404
        response code should be returned as well as a message about the app
        not existing.
        """
        response = yield self.request('GET', '/v2/apps/my-app_1')
        self.assertThat(response, IsJsonResponseWithCode(404))

        response_json = yield response.json()
        self.assertThat(response_json,
                        Equals({'message': "App '/my-app_1' does not exist"}))

    @inlineCallbacks
    def test_get_app_tasks(self):
        """
        When the tasks for an app are requested, the tasks for that app should
        be returned.
        """
        app = {
            'id': '/my-app_1',
            'cmd': 'sleep 50'
        }
        tasks = [
            {
                "host": "host1.local",
                "id": "my-app_1-1396592790353",
                "ports": [
                    31336,
                    31337
                ],
                "stagedAt": "2014-04-04T06:26:30.355Z",
                "startedAt": "2014-04-04T06:26:30.860Z",
                "version": "2014-04-04T06:26:23.051Z"
            },
            {
                "host": "host2.local",
                "id": "my-app_1-1396592784349",
                "ports": [
                    31382,
                    31383
                ],
                "stagedAt": "2014-04-04T06:26:24.351Z",
                "startedAt": "2014-04-04T06:26:24.919Z",
                "version": "2014-04-04T06:26:23.051Z"
            }
        ]
        self.marathon.add_app(app, tasks)

        response = yield self.request('GET', '/v2/apps/my-app_1/tasks')
        self.assertThat(response, IsJsonResponseWithCode(200))

        response_json = yield response.json()
        self.assertThat(response_json, Equals({'tasks': tasks}))

    @inlineCallbacks
    def test_get_app_tasks_not_found(self):
        """
        When the tasks for an app are requested but the app does not exist, a
        404 response code should be returned as well as a message about the app
        not existing.
        """
        response = yield self.request('GET', '/v2/apps/my-app_1/tasks')
        self.assertThat(response, IsJsonResponseWithCode(404))

        response_json = yield response.json()
        self.assertThat(response_json,
                        Equals({'message': "App '/my-app_1' does not exist"}))

    @inlineCallbacks
    def test_get_event_subscriptions(self):
        """
        When the event subscriptions are requested, the callback URLs for
        subscribers should be returned.
        """
        callback_url = 'http://marathon-acme.marathon.mesos:7000'
        self.marathon.add_event_subscription(callback_url)

        response = yield self.request('GET', '/v2/eventSubscriptions')
        self.assertThat(response, IsJsonResponseWithCode(200))

        response_json = yield response.json()
        self.assertThat(response_json,
                        Equals({'callbackUrls': [callback_url]}))
