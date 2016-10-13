import testtools

from testtools.twistedsupport import AsynchronousDeferredRunTest

from treq.client import HTTPClient

from twisted.web.client import ProxyAgent, URI
from twisted.web.server import Site

from txfake import FakeServer


class TestCase(testtools.TestCase):
    """ TestCase class for use with Twisted asynchornous tests. """
    run_tests_with = AsynchronousDeferredRunTest.make_factory(timeout=0.1)


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


def fake_client(resource):
    """
    Build a Treq HTTPClient aroudn a FakeServer to make requests against the
    given resource.
    """
    fake_server = FakeServer(Site(resource))
    fake_agent = FakeServerAgent(fake_server.endpoint)
    return HTTPClient(fake_agent)
