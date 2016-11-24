from treq.client import HTTPClient
from twisted.internet.defer import fail
from uritools import urisplit


class FailingAgent(object):
    def __init__(self, error=RuntimeError()):
        self.error = error

    """ A twisted.web.iweb.IAgent that does nothing but fail. """
    def request(self, method, uri, headers=None, bodyProducer=None):
        return fail(self.error)


""" A Treq client that will fail with a RuntimeError for any request made. """
failing_client = HTTPClient(FailingAgent())


class PerLocationAgent(object):
    """
    A twisted.web.iweb.IAgent that delegates to other agents for specific URI
    locations.
    """
    def __init__(self):
        self.agents = {}

    def add_agent(self, location, agent):
        """
        Add an agent for URIs with the specified location.
        :param bytes location:
            The URI authority/location (e.g. b'example.com:80')
        :param agent: The twisted.web.iweb.IAgent to use for the location
        """
        self.agents[location] = agent

    def request(self, method, uri, headers=None, bodyProducer=None):
        agent = self.agents[urisplit(uri).authority]
        return agent.request(
            method, uri, headers=headers, bodyProducer=bodyProducer)
