import json
import treq

from twisted.internet.defer import inlineCallbacks
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
        data = json.dumps(json_data) if json_data is not None else None
        treq_kwargs = {
            'data': data,
            'agent': self.agent
        }

        return treq.request(method, url, **treq_kwargs)

    @inlineCallbacks
    def test_index(self):
        response = yield self.request('GET', '/')
        response_json = yield response.content()

        self.assertEqual(response_json, '')

    def test_handle_event_success(self):
        pass

    def test_handle_event_failure(self):
        pass

    def test_handle_event_unknown(self):
        pass

    def test_health_healthy(self):
        pass

    def test_health_unhealthy(self):
        pass
