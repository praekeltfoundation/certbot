from testtools import TestCase
from testtools.twistedsupport import AsynchronousDeferredRunTest

from treq.client import HTTPClient as treq_HTTPClient

from twisted.internet.defer import DeferredQueue
from twisted.web.server import NOT_DONE_YET

from txfake import FakeHttpServer
from txfake.fake_connection import wait0

from uritools import urisplit


class TestHTTPClientBase(TestCase):
    # TODO: Run client tests synchronously with treq.testing tools (#38)
    run_tests_with = AsynchronousDeferredRunTest.make_factory(timeout=0.1)

    def setUp(self):
        super(TestHTTPClientBase, self).setUp()

        self.requests = DeferredQueue()
        self.fake_server = FakeHttpServer(self.handle_request)

        fake_client = treq_HTTPClient(self.fake_server.get_agent())
        self.client = self.get_client(fake_client)

        # Spin the reactor once at the end of each test to clean up any
        # cancelled deferreds
        self.addCleanup(wait0)

    def handle_request(self, request):
        self.requests.put(request)
        return NOT_DONE_YET

    def get_client(self, client):
        """To be implemented by subclass"""
        raise NotImplementedError()

    def uri(self, path):
        return '%s%s' % (self.client.url, path,)

    def cleanup_d(self, d):
        self.addCleanup(lambda: d)
        return d


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
