import json

import testtools

from testtools.twistedsupport import AsynchronousDeferredRunTest

from twisted.web.client import ProxyAgent, URI


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


def read_json_response(request):
    """ Read JSON from the UTF-8 encoded body of the given request. """
    return json.loads(request.content.read().decode('utf-8'))


def write_json_response(request, json_data, response_code=200):
    """
    Write UTF-8 encoded JSON to the body of a request, set the Content-Type
    header and finish() the request.
    """
    request.setResponseCode(response_code)
    request.setHeader('Content-Type', 'application/json')
    request.write(json.dumps(json_data).encode('utf-8'))
    request.finish()
