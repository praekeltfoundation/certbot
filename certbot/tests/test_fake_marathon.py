from twisted.internet.defer import inlineCallbacks, DeferredQueue
from twisted.web.server import NOT_DONE_YET

from certbot.tests.fake_marathon import (
    FakeMarathon, FakeMarathonData, FakeMarathonEventBus,
    FakeMarathonEventBusClient)
from certbot.tests.helpers import TestCase
from certbot.tests.matchers import HasRequestProperties

from testtools.matchers import Equals

from txfake import FakeHttpServer


class TestFakeMarathon(TestCase):

    def setUp(self):
        super(TestFakeMarathon, self).setUp()

        # Event bus client
        self.event_bus_requests = DeferredQueue()
        self.event_bus_receiver = FakeHttpServer(self.handle_event_bus_request)
        self.event_bus_client = FakeMarathonEventBusClient(
            self.event_bus_receiver.get_agent())

        # Event bus
        self.event_bus = FakeMarathonEventBus(self.event_bus_client)

        # Marathon
        self.data = FakeMarathonData()
        self.marathon = FakeMarathon(self.data, self.event_bus)

    def handle_event_bus_request(self, request):
        self.event_bus_requests.put(request)
        return NOT_DONE_YET

    @inlineCallbacks
    def test_add_event_callback(self):
        event = self.marathon.add_event_subscription(
            'http://localhost:7000', '127.0.0.1')
        self.assertThat(event['eventType'], Equals('subscribe_event'))
        self.assertThat(event['callbackUrl'], Equals('http://localhost:7000'))

        event_request = yield self.event_bus_requests.get()
        self.assertThat(event_request, HasRequestProperties(
            method='POST',
            url='http://localhost:7000'
        ))
