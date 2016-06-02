from testtools.matchers import Equals, Is, MatchesDict

from twisted.internet.defer import inlineCallbacks, DeferredQueue
from twisted.protocols.loopback import _LoopbackAddress
from twisted.web.server import Site, NOT_DONE_YET

from txfake import FakeHttpServer, FakeServer

from marathon_acme.clients import JsonClient, json_content
from marathon_acme.server import read_request_json
from marathon_acme.tests.fake_marathon import FakeMarathon, FakeMarathonAPI
from marathon_acme.tests.helpers import FakeServerAgent, TestCase
from marathon_acme.tests.matchers import (
    HasRequestProperties, IsJsonResponseWithCode, IsRecentMarathonTimestamp)


class TestFakeMarathonAPI(TestCase):
    event_requests = DeferredQueue()

    def setUp(self):
        super(TestFakeMarathonAPI, self).setUp()

        def handle_event_request(request):
            self.event_requests.put(request)
            return NOT_DONE_YET
        fake_server = FakeHttpServer(handle_event_request)

        self.marathon = FakeMarathon(fake_server.get_agent())
        self.marathon_api = FakeMarathonAPI(self.marathon)

        # FIXME: Current released version (15.3.1) of Klein expects the host to
        # have a 'port' attribute which in the case of Twisted's UNIX localhost
        # host there isn't. Monkeypatch on a port to get things to work.
        # https://github.com/twisted/klein/issues/102
        _LoopbackAddress.port = 7000

        fake_server = FakeServer(Site(self.marathon_api.app.resource()))
        fake_agent = FakeServerAgent(fake_server.endpoint)
        self.client = JsonClient('http://www.example.com', agent=fake_agent)

    def respond_to_event_request(self):
        """ Respond 200/OK to a waiting event request. """
        def response_ok(request):
            request.setResponseCode(200)
            request.finish()
        return self.event_requests.get().addCallback(response_ok)

    @inlineCallbacks
    def test_get_apps_empty(self):
        """
        When the list of apps is requested and there are no apps, an empty list
        of apps should be returned.
        """
        response = yield self.client.request('GET', '/v2/apps')
        self.assertThat(response, IsJsonResponseWithCode(200))

        response_json = yield json_content(response)
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

        response = yield self.client.request('GET', '/v2/apps')
        self.assertThat(response, IsJsonResponseWithCode(200))

        response_json = yield json_content(response)
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

        response = yield self.client.request('GET', '/v2/apps/my-app_1')
        self.assertThat(response, IsJsonResponseWithCode(200))

        response_json = yield json_content(response)
        self.assertThat(response_json, Equals({'app': app}))

    @inlineCallbacks
    def test_get_app_not_found(self):
        """
        When a specific app is requested but the app does not exist, a 404
        response code should be returned as well as a message about the app
        not existing.
        """
        response = yield self.client.request('GET', '/v2/apps/my-app_1')
        self.assertThat(response, IsJsonResponseWithCode(404))

        response_json = yield json_content(response)
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

        response = yield self.client.request('GET', '/v2/apps/my-app_1/tasks')
        self.assertThat(response, IsJsonResponseWithCode(200))

        response_json = yield json_content(response)
        self.assertThat(response_json, Equals({'tasks': tasks}))

    @inlineCallbacks
    def test_get_app_tasks_not_found(self):
        """
        When the tasks for an app are requested but the app does not exist, a
        404 response code should be returned as well as a message about the app
        not existing.
        """
        response = yield self.client.request('GET', '/v2/apps/my-app_1/tasks')
        self.assertThat(response, IsJsonResponseWithCode(404))

        response_json = yield json_content(response)
        self.assertThat(response_json,
                        Equals({'message': "App '/my-app_1' does not exist"}))

    @inlineCallbacks
    def test_get_event_subscriptions(self):
        """
        When the event subscriptions are requested, the callback URLs for
        subscribers should be returned.
        """
        callback_url = 'http://marathon-acme.marathon.mesos:7000'
        self.marathon.event_subscriptions = [callback_url]

        response = yield self.client.request('GET', '/v2/eventSubscriptions')
        self.assertThat(response, IsJsonResponseWithCode(200))

        response_json = yield json_content(response)
        self.assertThat(response_json,
                        Equals({'callbackUrls': [callback_url]}))

    @inlineCallbacks
    def test_post_event_subscriptions(self):
        """
        When a callback URL is posted for an event subscription, the subscibe
        event should be returned and FakeMarathon should now have the callback
        URL registered.
        """
        callback_url = 'http://marathon-acme.marathon.mesos:7000'

        response = yield self.client.request(
            'POST', '/v2/eventSubscriptions',
            params={'callbackUrl': callback_url})
        self.assertThat(response, IsJsonResponseWithCode(200))

        response_json = yield json_content(response)
        self.assertThat(response_json, MatchesDict({
            'eventType': Equals('subscribe_event'),
            'callbackUrl': Equals(callback_url),
            'clientIp': Is(None),  # FIXME: No clientIp in request
            'timestamp': IsRecentMarathonTimestamp()
        }))

        # Check we also receive the event on the event bus
        event_request = yield self.event_requests.get()
        self.assertThat(event_request,
                        HasRequestProperties(method='POST', url=callback_url))

        event_request_json = read_request_json(event_request)
        self.assertThat(event_request_json, Equals(response_json))

        event_request.setResponseCode(200)
        event_request.finish()

        # Assert that the event subscription was actually added
        self.assertThat(self.marathon.get_event_subscriptions(),
                        Equals([callback_url]))

    @inlineCallbacks
    def test_post_event_subscriptions_idempotent(self):
        """
        Posting the same callback URL for an event subscription twice succeeds
        both times and doesn't result in more than one callback URL being
        registered.
        """
        callback_url = 'http://marathon-acme.marathon.mesos:7000'

        response = yield self.client.request(
            'POST', '/v2/eventSubscriptions',
            params={'callbackUrl': callback_url})
        self.assertThat(response, IsJsonResponseWithCode(200))

        self.assertThat(self.marathon.get_event_subscriptions(),
                        Equals([callback_url]))

        yield self.respond_to_event_request()

        response = yield self.client.request(
            'POST', '/v2/eventSubscriptions',
            params={'callbackUrl': callback_url})
        self.assertThat(response, IsJsonResponseWithCode(200))

        self.assertThat(self.marathon.get_event_subscriptions(),
                        Equals([callback_url]))

        yield self.respond_to_event_request()

    @inlineCallbacks
    def test_delete_event_subscriptions(self):
        """
        When a callback URL is deleted for an event subscription, the
        unsubscibe event should be returned, other event subscribers should be
        notified, and FakeMarathon should not have the callback URL registered
        any more.
        """
        callback_url_1 = 'http://marathon-acme.marathon.mesos:7000'
        callback_url_2 = 'http://consular.marathon.mesos:5000'
        self.marathon.event_subscriptions = [callback_url_1, callback_url_2]

        response = yield self.client.request(
            'DELETE', '/v2/eventSubscriptions',
            params={'callbackUrl': callback_url_1})
        self.assertThat(response, IsJsonResponseWithCode(200))

        response_json = yield json_content(response)
        self.assertThat(response_json, MatchesDict({
            'eventType': Equals('unsubscribe_event'),
            'callbackUrl': Equals(callback_url_1),
            'clientIp': Is(None),  # FIXME: No clientIp in request
            'timestamp': IsRecentMarathonTimestamp()
        }))

        # Event should be received at second callback URL
        event_request = yield self.event_requests.get()
        self.assertThat(event_request,
                        HasRequestProperties(method='POST',
                                             url=callback_url_2))

        event_request_json = read_request_json(event_request)
        self.assertThat(event_request_json, Equals(response_json))

        event_request.setResponseCode(200)
        event_request.finish()

        # Assert that the event subscription was actually removed
        self.assertThat(self.marathon.get_event_subscriptions(),
                        Equals([callback_url_2]))

    @inlineCallbacks
    def test_delete_event_subscriptions_idempotent(self):
        """
        Deleting the same callback URL for an event subscription twice
        succeeds both times and doesn't result in more than one callback URL
        being deleted.
        """
        callback_url = 'http://marathon-acme.marathon.mesos:7000'
        self.marathon.event_subscriptions = [callback_url]

        response = yield self.client.request(
            'DELETE', '/v2/eventSubscriptions',
            params={'callbackUrl': callback_url})
        self.assertThat(response, IsJsonResponseWithCode(200))

        self.assertThat(self.marathon.get_event_subscriptions(),
                        Equals([]))

        response = yield self.client.request(
            'DELETE', '/v2/eventSubscriptions',
            params={'callbackUrl': callback_url})
        self.assertThat(response, IsJsonResponseWithCode(200))

        self.assertThat(self.marathon.get_event_subscriptions(),
                        Equals([]))
