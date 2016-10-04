import json

from testtools.matchers import Equals, Is

from twisted.internet.defer import inlineCallbacks, DeferredQueue
from twisted.protocols.loopback import _LoopbackAddress
from twisted.web.server import Site

from txfake import FakeServer
from txfake.fake_connection import wait0

from marathon_acme.clients import (
    JsonClient, json_content, sse_content, sse_content_with_protocol)
from marathon_acme.tests.fake_marathon import FakeMarathon, FakeMarathonAPI
from marathon_acme.tests.helpers import FakeServerAgent, TestCase
from marathon_acme.tests.matchers import (
    IsJsonResponseWithCode, IsMarathonEvent, IsSseResponse)


class TestFakeMarathonAPI(TestCase):
    event_requests = DeferredQueue()

    def setUp(self):
        super(TestFakeMarathonAPI, self).setUp()

        self.marathon = FakeMarathon()
        self.marathon_api = FakeMarathonAPI(self.marathon)

        # FIXME: Current released version (15.3.1) of Klein expects the host to
        # have a 'port' attribute which in the case of Twisted's UNIX localhost
        # host there isn't. Monkeypatch on a port to get things to work.
        # https://github.com/twisted/klein/issues/102
        _LoopbackAddress.port = 7000

        fake_server = FakeServer(Site(self.marathon_api.app.resource()))
        fake_agent = FakeServerAgent(fake_server.endpoint)
        self.client = JsonClient('http://www.example.com', agent=fake_agent)

    @inlineCallbacks
    def test_get_apps_empty(self):
        """
        When the list of apps is requested and there are no apps, an empty list
        of apps should be returned.
        """
        response = yield self.client.request('GET', '/v2/apps')
        self.assertThat(response, IsJsonResponseWithCode(200))

        response_json = yield json_content(response)
        self.assertThat(response_json, Equals({'apps': []}))

    @inlineCallbacks
    def test_get_apps(self):
        """
        When the list of apps is requested, a list of apps added via add_app()
        should be returned.
        """
        app = {
            'id': '/my-app_1',
            'cmd': 'sleep 50',
            'tasks': [
                {
                    "host": "host1.local",
                    "id": "my-app_1-1396592790353",
                    "ports": []
                },
                {
                    "host": "host2.local",
                    "id": "my-app_1-1396592784349",
                    "ports": []
                }
            ]
        }
        self.marathon.add_app(app)

        response = yield self.client.request('GET', '/v2/apps')
        self.assertThat(response, IsJsonResponseWithCode(200))

        response_json = yield json_content(response)
        self.assertThat(response_json, Equals({'apps': [app]}))

    @inlineCallbacks
    def test_get_events(self):
        """
        When a request is made to the event stream endpoint, an SSE stream
        should be received in response and an event should be fired that
        indicates that the stream was attached to.
        """
        response = yield self.client.request('GET', '/v2/events', headers={
            'Accept': 'text/event-stream'
        })
        self.assertThat(response, IsSseResponse())

        data = []
        sse_content(response, {'event_stream_attached': data.append})

        yield wait0()

        self.assertThat(len(data), Equals(1))

        data_json = json.loads(data[0])
        # FIXME: No clientIp in request
        self.assertThat(data_json, IsMarathonEvent(
            'event_stream_attached', remoteAddress=Is(None)))

    @inlineCallbacks
    def test_get_events_lost_connection(self):
        """
        When two connections are made the the event stream, the first
        connection should receive events for both connections attaching to the
        stream. Then, when the first connection is disconnected, the second
        should receive a detach event for the first.
        """
        response1 = yield self.client.request('GET', '/v2/events', headers={
            'Accept': 'text/event-stream'
        })
        self.assertThat(response1, IsSseResponse())

        attach_data1 = []
        detach_data1 = []
        finished, protocol = sse_content_with_protocol(response1, {
            'event_stream_attached': attach_data1.append,
            'event_stream_detached': detach_data1.append
        })

        response2 = yield self.client.request('GET', '/v2/events', headers={
            'Accept': 'text/event-stream'
        })
        self.assertThat(response2, IsSseResponse())

        attach_data2 = []
        detach_data2 = []
        sse_content(response2, {
            'event_stream_attached': attach_data2.append,
            'event_stream_detached': detach_data2.append
        })

        # Close request 1's connection
        # FIXME: Currently the only way to get the underlying transport so that
        # we can simulate a lost connection is to get the transport that the
        # SseProtocol receives. This transport is actually a
        # TransportProxyProducer (because that's what HTTP11ClientProtocol
        # gives our protocol). Get the actual wrapped transport from the
        # _producer attribute.
        transport = protocol.transport._producer
        yield transport.loseConnection()
        yield finished

        # Spin the reactor to fire all the callbacks
        yield wait0()

        # Assert request 1's response data
        self.assertThat(len(attach_data1), Equals(2))

        # First attach event on request 1 from itself connecting
        data0_json = json.loads(attach_data1[0])
        # FIXME: No clientIp in request
        self.assertThat(data0_json, IsMarathonEvent(
            'event_stream_attached', remoteAddress=Is(None)))

        # Second attach event on request 1 from request 2 connecting
        data1_json = json.loads(attach_data1[1])
        # FIXME: No clientIp in request
        self.assertThat(data1_json, IsMarathonEvent(
            'event_stream_attached', remoteAddress=Is(None)))

        # Request 1 shouldn't receive any detach events
        self.assertThat(detach_data1, Equals([]))

        # Now look at request 2's events
        # Attach event only for itself
        self.assertThat(len(attach_data2), Equals(1))
        attach_data_json = json.loads(attach_data2[0])
        # FIXME: No clientIp in request
        self.assertThat(attach_data_json, IsMarathonEvent(
            'event_stream_attached', remoteAddress=Is(None)))

        # Detach event for request 1
        self.assertThat(len(detach_data2), Equals(1))
        detach_data_json = json.loads(detach_data2[0])
        # FIXME: No clientIp in request
        self.assertThat(detach_data_json, IsMarathonEvent(
            'event_stream_detached', remoteAddress=Is(None)))
