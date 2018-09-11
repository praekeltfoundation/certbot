import json

from treq.client import HTTPClient

from twisted.internet.defer import fail


class FailingAgent(object):
    def __init__(self, error=RuntimeError()):
        self.error = error

    """ A twisted.web.iweb.IAgent that does nothing but fail. """
    def request(self, method, uri, headers=None, bodyProducer=None):
        return fail(self.error)


""" A Treq client that will fail with a RuntimeError for any request made. """
failing_client = HTTPClient(FailingAgent())


def read_request_json(request):
    """
    Read the body of a request and decode it as JSON. The counterpart to
    ``marathon_acme.server.write_request_json`` but only used in tests.
    """
    return json.loads(request.content.read().decode('utf-8'))
