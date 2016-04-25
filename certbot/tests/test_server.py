import json
import treq

from twisted.internet.defer import fail, inlineCallbacks, succeed
from twisted.protocols.loopback import _LoopbackAddress
from twisted.trial.unittest import TestCase
from twisted.web.client import ProxyAgent, URI
from twisted.web.server import Site

from txfake import FakeServer

from uritools import uricompose

from certbot.server import MarathonEventServer, Health


class FakeServerAgent(ProxyAgent):
    """
    ProxyAgent uses the entire URI as the request path, which is the correct
    thing to do when talking to a proxy but not for non-proxy servers.
    """
    def request(self, method, uri, headers=None, bodyProducer=None):
        key = ("http-proxy", self._proxyEndpoint)
        parsedURI = URI.fromBytes(uri)
        return self._requestWithEndpoint(
            key, self._proxyEndpoint, method, parsedURI, headers,
            bodyProducer, parsedURI.originForm)


class MarathonEventServerTest(TestCase):

    def setUp(self):
        self.event_server = MarathonEventServer(lambda: Health(200))

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
        headers = {
            'Accept': 'application/json',
        }

        # Add JSON body if there is JSON data
        if json_data is not None:
            data = json.dumps(json_data).encode('utf-8')
            headers['Content-Type'] = 'application/json; charset=utf-8'

        return treq.request(
            method, url, data=data, headers=headers, agent=self.agent)

    @inlineCallbacks
    def test_index(self):
        response = yield self.request('GET', '/')
        response_json = yield response.json()

        self.assertEqual(response.code, 200)
        self.assertEqual(response.headers.getRawHeaders('Content-Type'),
                         ['application/json; charset=utf-8'])
        self.assertEqual(response_json, {})

    @inlineCallbacks
    def test_handle_event_success(self):
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
        response_json = yield response.json()

        self.assertEqual(response.code, 200)
        self.assertEqual(response.headers.getRawHeaders('Content-Type'),
                         ['application/json; charset=utf-8'])
        self.assertEqual(response_json, {'message': 'hello'})

    @inlineCallbacks
    def test_handle_event_failure(self):
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
        response_json = yield response.json()

        self.assertEqual(response.code, 500)
        self.assertEqual(response.headers.getRawHeaders('Content-Type'),
                         ['application/json; charset=utf-8'])
        self.assertEqual(response_json, {'error': 'Something went wrong'})

    def test_handle_event_unknown(self):
        pass

    def test_health_healthy(self):
        pass

    def test_health_unhealthy(self):
        pass
