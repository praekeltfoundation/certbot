import json
import treq

from twisted.internet.defer import fail, inlineCallbacks, succeed
from twisted.protocols.loopback import _LoopbackAddress
from twisted.web.client import ProxyAgent, URI
from twisted.web.server import Site

from testtools.matchers import Equals, MatchesStructure
from testtools.twistedsupport import AsynchronousDeferredRunTest

from txfake import FakeServer

from uritools import uricompose

from certbot.server import MarathonEventServer, Health
from certbot.tests.helpers import TestCase
from certbot.tests.matchers import HasHeader


class FakeServerAgent(ProxyAgent):
    """
    ProxyAgent uses the entire URI as the request path, which is the correct
    thing to do when talking to a proxy but not for non-proxy servers.
    """
    def request(self, method, uri, headers=None, bodyProducer=None):
        key = ('http-proxy', self._proxyEndpoint)
        parsedURI = URI.fromBytes(uri)
        return self._requestWithEndpoint(
            key, self._proxyEndpoint, method, parsedURI, headers,
            bodyProducer, parsedURI.originForm)


def IsJsonResponseWithCode(code):
    """
    Match the status code on a treq.response object and check that a header is
    set to indicate that the content type is UTF-8 encoded JSON.
    """
    return MatchesStructure(
        code=Equals(code),
        headers=HasHeader('Content-Type', ['application/json; charset=utf-8'])
    )


class TestMarathonEventServer(TestCase):
    def setUp(self):
        super(TestMarathonEventServer, self).setUp()

        self.event_server = MarathonEventServer()

        # FIXME: Current released version (15.3.1) of Klein expects the host to
        # have a 'port' attribute which in the case of Twisted's UNIX localhost
        # host there isn't. Monkeypatch on a port to get things to work.
        # https://github.com/twisted/klein/issues/102
        _LoopbackAddress.port = 7000

        fake_server = FakeServer(Site(self.event_server.app.resource()))
        self.agent = FakeServerAgent(fake_server.endpoint)

    def request(self, method, path, query=None, json_data=None):
        url = uricompose('http', 'www.example.com', path, query)
        data = None
        headers = {'Accept': 'application/json'}

        # Add JSON body if there is JSON data
        if json_data is not None:
            data = json.dumps(json_data).encode('utf-8')
            headers['Content-Type'] = 'application/json; charset=utf-8'

        return treq.request(
            method, url, data=data, headers=headers, agent=self.agent)

    @inlineCallbacks
    def test_index(self):
        """
        When a GET request is made to the root path ``/``, the server should
        return a 200 status code and an empty JSON object.
        """
        response = yield self.request('GET', '/')
        self.assertThat(response, IsJsonResponseWithCode(200))

        response_json = yield response.json()
        self.assertThat(response_json, Equals({}))

    @inlineCallbacks
    def test_handle_event_success(self):
        """
        When a POST request is made to the events endpoint, and an event is
        sent that has a handler set, and the handler returns successfully, a
        200 status code should be returned as well as the JSON message from the
        handler.
        """
        self.event_server.add_handler(
            'status_update_event', lambda event: succeed({'message': 'hello'}))

        json_data = {
            'eventType': 'status_update_event',
            'timestamp': '2014-03-01T23:29:30.158Z',
            'slaveId': '20140909-054127-177048842-5050-1494-0',
            'taskId': 'my-app_0-1396592784349',
            'taskStatus': 'TASK_RUNNING',
            'appId': '/my-app',
            'host': 'slave-1234.acme.org',
            'ports': [31372],
            'version': '2014-04-04T06:26:23.051Z',
        }
        response = yield self.request('POST', '/events', json_data=json_data)
        self.assertThat(response, IsJsonResponseWithCode(200))

        response_json = yield response.json()
        self.assertThat(response_json, Equals({'message': 'hello'}))

    @inlineCallbacks
    def test_handle_event_failure(self):
        """
        When a POST request is made to the events endpoint, and an event is
        sent that has a handler set, and the handler fails, a 500 status code
        should be returned as well as a JSON object containing the error
        message from the handler.
        """
        self.event_server.add_handler(
            'status_update_event',
            lambda event: fail(RuntimeError('Something went wrong')))

        json_data = {
            'eventType': 'status_update_event',
            'timestamp': '2014-03-01T23:29:30.158Z',
            'slaveId': '20140909-054127-177048842-5050-1494-0',
            'taskId': 'my-app_0-1396592784349',
            'taskStatus': 'TASK_RUNNING',
            'appId': '/my-app',
            'host': 'slave-1234.acme.org',
            'ports': [31372],
            'version': '2014-04-04T06:26:23.051Z',
        }
        response = yield self.request('POST', '/events', json_data=json_data)
        self.assertThat(response, IsJsonResponseWithCode(500))

        response_json = yield response.json()
        self.assertThat(response_json,
                        Equals({'error': 'Something went wrong'}))

    @inlineCallbacks
    def test_handle_event_unknown(self):
        """
        When a POST request is made to the events endpoint, and an event is
        sent that doesn't have a handler, a 501 status code should be returned
        as well as a JSON message that explains that the event type is not
        supported.
        """
        json_data = {
          'eventType': 'subscribe_event',
          'timestamp': '2014-03-01T23:29:30.158Z',
          'clientIp': '1.2.3.4',
          'callbackUrl': 'http://subscriber.acme.org/callbacks'
        }
        response = yield self.request('POST', '/events', json_data=json_data)
        self.assertThat(response, IsJsonResponseWithCode(501))

        response_json = yield response.json()
        self.assertThat(response_json, Equals({
            'error': 'Event type subscribe_event not supported.'
        }))

    @inlineCallbacks
    def test_health_healthy(self):
        """
        When a GET request is made to the health endpoint, and the health
        handler reports that the service is healthy, a 200 status code should
        be returned together with the JSON message from the handler.
        """
        self.event_server.set_health_handler(
            lambda: Health(True, {'message': 'I\'m 200/OK!'}))

        response = yield self.request('GET', '/health')
        self.assertThat(response, IsJsonResponseWithCode(200))

        response_json = yield response.json()
        self.assertThat(response_json, Equals({'message': 'I\'m 200/OK!'}))

    @inlineCallbacks
    def test_health_unhealthy(self):
        """
        When a GET request is made to the health endpoint, and the health
        handler reports that the service is unhealthy, a 503 status code should
        be returned together with the JSON message from the handler.
        """
        self.event_server.set_health_handler(
            lambda: Health(False, {'error': 'I\'m sad :('}))

        response = yield self.request('GET', '/health')
        self.assertThat(response, IsJsonResponseWithCode(503))

        response_json = yield response.json()
        self.assertThat(response_json, Equals({'error': 'I\'m sad :('}))

    @inlineCallbacks
    def test_health_handler_unset(self):
        """
        When a GET request is made to the health endpoint, and the health
        handler hasn't been set, a 501 status code should be returned together
        with a JSON message that explains that the handler is not set.
        """
        response = yield self.request('GET', '/health')
        self.assertThat(response, IsJsonResponseWithCode(501))

        response_json = yield response.json()
        self.assertThat(response_json, Equals({
            'error': 'Cannot determine service health: no handler set'
        }))
