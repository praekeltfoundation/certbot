# -*- coding: utf-8 -*-
from testtools.matchers import Equals
from twisted.internet.defer import inlineCallbacks
from twisted.protocols.loopback import _LoopbackAddress

from marathon_acme.clients import JsonClient, json_content
from marathon_acme.server import HealthServer, Health
from marathon_acme.tests.helpers import fake_client, TestCase
from marathon_acme.tests.matchers import IsJsonResponseWithCode


class TestHealthServer(TestCase):
    def setUp(self):
        super(TestHealthServer, self).setUp()

        self.event_server = HealthServer()

        # FIXME: Current released version (15.3.1) of Klein expects the host to
        # have a 'port' attribute which in the case of Twisted's UNIX localhost
        # host there isn't. Monkeypatch on a port to get things to work.
        # https://github.com/twisted/klein/issues/102
        _LoopbackAddress.port = 7000

        self.client = JsonClient(
            'http://www.example.com',
            client=fake_client(self.event_server.app.resource()))

    @inlineCallbacks
    def test_health_healthy(self):
        """
        When a GET request is made to the health endpoint, and the health
        handler reports that the service is healthy, a 200 status code should
        be returned together with the JSON message from the handler.
        """
        self.event_server.set_health_handler(
            lambda: Health(True, {'message': "I'm 200/OK!"}))

        response = yield self.client.request('GET', '/health')
        self.assertThat(response, IsJsonResponseWithCode(200))

        response_json = yield json_content(response)
        self.assertThat(response_json, Equals({'message': "I'm 200/OK!"}))

    @inlineCallbacks
    def test_health_unhealthy(self):
        """
        When a GET request is made to the health endpoint, and the health
        handler reports that the service is unhealthy, a 503 status code should
        be returned together with the JSON message from the handler.
        """
        self.event_server.set_health_handler(
            lambda: Health(False, {'error': "I'm sad :("}))

        response = yield self.client.request('GET', '/health')
        self.assertThat(response, IsJsonResponseWithCode(503))

        response_json = yield json_content(response)
        self.assertThat(response_json, Equals({'error': "I'm sad :("}))

    @inlineCallbacks
    def test_health_handler_unset(self):
        """
        When a GET request is made to the health endpoint, and the health
        handler hasn't been set, a 501 status code should be returned together
        with a JSON message that explains that the handler is not set.
        """
        response = yield self.client.request('GET', '/health')
        self.assertThat(response, IsJsonResponseWithCode(501))

        response_json = yield json_content(response)
        self.assertThat(response_json, Equals({
            'error': 'Cannot determine service health: no handler set'
        }))

    @inlineCallbacks
    def test_health_handler_unicode(self):
        """
        When a GET request is made to the health endpoint, and the health
        handler reports that the service is unhealthy, a 503 status code should
        be returned together with the JSON message from the handler.
        """
        self.event_server.set_health_handler(
            lambda: Health(False, {'error': u"I'm sad 🙁"}))

        response = yield self.client.request('GET', '/health')
        self.assertThat(response, IsJsonResponseWithCode(503))

        response_json = yield json_content(response)
        self.assertThat(response_json, Equals({'error': u"I'm sad 🙁"}))
