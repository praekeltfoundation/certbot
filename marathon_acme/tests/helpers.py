from treq.client import HTTPClient
from twisted.internet.defer import fail


class FailingAgent(object):
    """ A twisted.web.iweb.IAgent that does nothing but fail. """
    def request(self, method, uri, headers=None, bodyProducer=None):
        return fail(RuntimeError())


""" A Treq client that will fail with a RuntimeError for any request made. """
failing_client = HTTPClient(FailingAgent())
