import json
from functools import partial
from operator import methodcaller

from testtools.assertions import assert_that
from testtools.matchers import AfterPreprocessing as After
from testtools.matchers import (
    Equals, Is, MatchesAll, MatchesListwise, MatchesStructure)
from testtools.twistedsupport import succeeded
from treq.content import json_content

from marathon_acme.clients import sse_content, _sse_content_with_protocol
from marathon_acme.tests.fake_marathon import (
    FakeMarathon, FakeMarathonAPI, FakeMarathonLb)
from marathon_acme.tests.matchers import (
    HasHeader, IsJsonResponseWithCode, IsMarathonEvent, IsSseResponse)


def dict_handler(callback_dict):
    def dispatch(event, data):
        callback = callback_dict.get(event)
        if callback is not None:
            callback(data)
    return dispatch


def collect_events(event_type, response):
    messages = []
    sse_content(response, dict_handler({event_type: messages.append}))
    return messages


class TestFakeMarathonAPI(object):
    def setup_method(self):
        self.marathon = FakeMarathon()
        self.marathon_api = FakeMarathonAPI(self.marathon)
        self.client = self.marathon_api.client

    def test_get_apps_empty(self):
        """
        When the list of apps is requested and there are no apps, an empty list
        of apps should be returned.
        """
        response = self.client.get('http://localhost/v2/apps')
        assert_that(response, succeeded(MatchesAll(
            IsJsonResponseWithCode(200),
            After(json_content, succeeded(Equals({'apps': []})))
        )))

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

        response = self.client.get('http://localhost/v2/apps')
        assert_that(response, succeeded(MatchesAll(
            IsJsonResponseWithCode(200),
            After(json_content, succeeded(Equals({'apps': [app]})))
        )))

    def test_get_apps_check_called(self):
        """
        When a client makes a call to the GET /v2/apps API, a flag should be
        set to indicate that the API has been called. Checking the flag should
        reset it.
        """
        # The flag should start out False
        assert_that(self.marathon_api.check_called_get_apps(), Equals(False))

        # Make a call to get_apps()
        response = self.client.get('http://localhost/v2/apps')
        assert_that(response, succeeded(MatchesAll(
            IsJsonResponseWithCode(200),
            After(json_content, succeeded(Equals({'apps': []})))
        )))

        # After the call the flag should be True
        assert_that(self.marathon_api.check_called_get_apps(), Equals(True))

        # Checking the flag should reset it to False
        assert_that(self.marathon_api.check_called_get_apps(), Equals(False))

    def test_get_events(self):
        """
        When a request is made to the event stream endpoint, an SSE stream
        should be received in response and an event should be fired that
        indicates that the stream was attached to.
        """
        response = self.client.get('http://localhost/v2/events', headers={
            'Accept': 'text/event-stream'
        })

        assert_that(response, succeeded(MatchesAll(
            IsSseResponse(),
            After(
                partial(collect_events, 'event_stream_attached'),
                MatchesListwise([
                    After(json.loads, IsMarathonEvent(
                        'event_stream_attached',
                        remoteAddress=Equals('127.0.0.1')))
                ])
            )
        )))

    def test_get_events_lost_connection(self):
        """
        When two connections are made to the event stream, the first connection
        should receive events for both connections attaching to the stream.
        Then, when the first connection is disconnected, the second should
        receive a detach event for the first.
        """
        response1_d = self.client.get('http://localhost/v2/events', headers={
            'Accept': 'text/event-stream'
        })
        # First listener attaches and receives event it attached
        assert_that(response1_d, succeeded(IsSseResponse()))

        response1 = response1_d.result
        attach_data1 = []
        detach_data1 = []
        handler1 = dict_handler({
           'event_stream_attached': attach_data1.append,
           'event_stream_detached': detach_data1.append
        })
        finished, protocol = _sse_content_with_protocol(response1, handler1)

        response2_d = self.client.get('http://localhost/v2/events', headers={
            'Accept': 'text/event-stream'
        })
        assert_that(response2_d, succeeded(IsSseResponse()))

        response2 = response2_d.result
        attach_data2 = []
        detach_data2 = []
        handler2 = dict_handler({
           'event_stream_attached': attach_data2.append,
           'event_stream_detached': detach_data2.append
        })
        sse_content(response2, handler2)

        # Close request 1's connection
        # FIXME: Currently the only way to get the underlying transport so that
        # we can simulate a lost connection is to get the transport that the
        # SseProtocol receives. This transport is actually a
        # TransportProxyProducer (because that's what HTTP11ClientProtocol
        # gives our protocol). Get the actual wrapped transport from the
        # _producer attribute.
        protocol.transport._producer.loseConnection()
        # Flush the client so that the disconnection propagates
        self.client.flush()
        assert_that(finished, succeeded(Is(None)))

        # Assert request 1's response data
        assert_that(attach_data1, MatchesListwise([
            # First attach event on request 1 from itself connecting
            After(json.loads, IsMarathonEvent(
                'event_stream_attached', remoteAddress=Equals('127.0.0.1'))),
            # Second attach event on request 1 from request 2 connecting
            After(json.loads, IsMarathonEvent(
                'event_stream_attached', remoteAddress=Equals('127.0.0.1')))
        ]))

        # Request 1 shouldn't receive any detach events
        assert_that(detach_data1, Equals([]))

        # Now look at request 2's events
        # Attach event only for itself
        assert_that(attach_data2, MatchesListwise([
            After(json.loads, IsMarathonEvent(
                'event_stream_attached', remoteAddress=Equals('127.0.0.1')))
        ]))

        # Detach event for request 1
        assert_that(detach_data2, MatchesListwise([
            After(json.loads, IsMarathonEvent(
                'event_stream_detached', remoteAddress=Equals('127.0.0.1')))
        ]))

    def test_add_app_triggers_api_post_event(self):
        """
        When an app is added to the underlying fake Marathon, an
        ``api_post_event`` should be received by any event listeners.
        """
        response = self.client.get('http://localhost/v2/events', headers={
            'Accept': 'text/event-stream'
        })
        assert_that(response, succeeded(IsSseResponse()))

        app = {
            'id': '/my-app_1',
            'labels': {
                'HAPROXY_GROUP': 'external',
                'MARATHON_ACME_0_DOMAIN': 'example.com'
            },
            'portDefinitions': [
                {'port': 9000, 'protocol': 'tcp', 'labels': {}}
            ]
        }
        self.marathon.add_app(app)

        assert_that(response, succeeded(
            After(
                partial(collect_events, 'api_post_event'),
                MatchesListwise([
                    After(json.loads, IsMarathonEvent(
                        'api_post_event',
                        clientIp=Is(None),
                        uri=Equals('/v2/apps/my-app_1'),
                        appDefinition=Equals(app)))
                ]))))


class TestFakeMarathonLb(object):

    def setup_method(self):
        self.marathon_lb = FakeMarathonLb()
        self.client = self.marathon_lb.client

    def test_signal_hup(self):
        """
        When a client calls the ``/mlb_signal/hup`` endpoint, the correct
        response should be returned and the ``signalled_hup`` flag set True.
        """
        assert_that(self.marathon_lb.check_signalled_hup(), Equals(False))

        response = self.client.get('http://localhost/_mlb_signal/hup')
        assert_that(response, succeeded(MatchesAll(
            MatchesStructure(
                code=Equals(200),
                headers=HasHeader('content-type', ['text/plain'])),
            After(methodcaller('text'), succeeded(
                Equals('Sent SIGHUP signal to marathon-lb')))
        )))

        assert_that(self.marathon_lb.check_signalled_hup(), Equals(True))

        # Signalled flag should be reset to false after it is checked
        assert_that(self.marathon_lb.check_signalled_hup(), Equals(False))

    def test_signal_usr1(self):
        """
        When a client calls the ``/mlb_signal/usr1`` endpoint, the correct
        response should be returned and the ``signalled_usr1`` flag set True.
        """
        assert_that(self.marathon_lb.check_signalled_usr1(), Equals(False))

        response = self.client.get('http://localhost/_mlb_signal/usr1')
        assert_that(response, succeeded(MatchesAll(
            MatchesStructure(
                code=Equals(200),
                headers=HasHeader('content-type', ['text/plain'])),
            After(methodcaller('text'), succeeded(
                Equals('Sent SIGUSR1 signal to marathon-lb')))
        )))

        assert_that(self.marathon_lb.check_signalled_usr1(), Equals(True))

        # Signalled flag should be reset to false after it is checked
        assert_that(self.marathon_lb.check_signalled_usr1(), Equals(False))
