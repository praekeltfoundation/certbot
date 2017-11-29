# -*- coding: utf-8 -*-
import pytest

from testtools.assertions import assert_that
from testtools.matchers import Is
from testtools.twistedsupport import succeeded

from twisted.internet.task import Clock

from marathon_acme.sse_protocol import SseProtocol


class DummyTransport(object):
    disconnecting = False

    def loseConnection(self):
        self.disconnecting = True


@pytest.fixture
def messages():
    return list()


@pytest.fixture
def protocol(messages):
    return make_protocol(messages)


def make_protocol(messages=None, **kwargs):
    if messages is None:
        messages = list()

    def handler(event, data):
        messages.append((event, data))

    protocol = SseProtocol(handler, **kwargs)
    protocol.transport = DummyTransport()
    return protocol


class TestSseProtocol(object):
    def test_default_event(self, protocol, messages):
        """
        When data is received, followed by a blank line, the default event
        type, 'message', should be used.
        """
        protocol.dataReceived(b'data:hello\r\n\r\n')

        assert messages == [('message', 'hello')]

    def test_multiline_data(self, protocol, messages):
        """
        When multiple lines of data are specified in a single event, those
        lines should be received by the handler with a '\n' character
        separating them.
        """
        protocol.dataReceived(b'data:hello\r\ndata:world\r\n\r\n')

        assert messages == [('message', 'hello\nworld')]

    def test_different_newlines(self, protocol, messages):
        """
        When data is received with '\r\n', '\n', or '\r', lines should be split
        on those characters.
        """
        protocol.dataReceived(b'data:hello\ndata:world\r\r\n')

        assert messages == [('message', 'hello\nworld')]

    def test_empty_data(self, protocol, messages):
        """
        When the data field is specified in an event but no data is given, the
        handler should receive a message with empty data.
        """
        protocol.dataReceived(b'data:\r\n\r\n')

        assert messages == [('message', '')]

    def test_no_data(self, protocol, messages):
        """
        When the data field is not specified and the event is completed, the
        handler should not be called.
        """
        protocol.dataReceived(b'\r\n')

        assert messages == []

    def test_space_before_value(self, protocol, messages):
        """
        When a field/value pair is received, and there is a space before the
        value, the leading space should be stripped.
        """
        protocol.dataReceived(b'data: hello\r\n\r\n')

        assert messages == [('message', 'hello')]

    def test_space_before_value_strip_only_first_space(
            self, protocol, messages):
        """
        When a field/value pair is received, and there are multiple spaces at
        the start of the value, the leading space should be stripped and the
        other spaces left intact.
        """
        protocol.dataReceived(
            'data:{}\r\n\r\n'.format(' ' * 4).encode('utf-8'))

        assert messages == [('message', ' ' * 3)]

    def test_custom_event(self, protocol, messages):
        """
        If a custom event is set for an event, a the handler should be called
        with the correct event.
        """
        protocol.dataReceived(b'event:my_event\r\n')
        protocol.dataReceived(b'data:hello\r\n\r\n')

        assert messages == [('my_event', 'hello')]

    def test_multiple_events(self, protocol, messages):
        """
        If multiple different event types are received, the handler should
        receive the different event types and their corresponding data.
        """
        protocol.dataReceived(b'event:test1\r\n')
        protocol.dataReceived(b'data:hello\r\n\r\n')
        protocol.dataReceived(b'event:test2\r\n')
        protocol.dataReceived(b'data:world\r\n\r\n')

        assert messages == [
            ('test1', 'hello'),
            ('test2', 'world'),
        ]

    def test_id_ignored(self, protocol, messages):
        """
        When the id field is included in an event, it should be ignored.
        """
        protocol.dataReceived(b'data:hello\r\n')
        protocol.dataReceived(b'id:123\r\n\r\n')

        assert messages == [('message', 'hello')]

    def test_retry_ignored(self, protocol, messages):
        """
        When the retry field is included in an event, it should be ignored.
        """
        protocol.dataReceived(b'data:hello\r\n')
        protocol.dataReceived(b'retry:123\r\n\r\n')

        assert messages == [('message', 'hello')]

    def test_unknown_field_ignored(self, protocol, messages):
        """
        When an unknown field is included in an event, it should be ignored.
        """
        protocol.dataReceived(b'data:hello\r\n')
        protocol.dataReceived(b'somefield:123\r\n\r\n')

        assert messages == [('message', 'hello')]

    def test_leading_colon_ignored(self, protocol, messages):
        """
        When a line is received starting with a ':' character, the line should
        be ignored.
        """
        protocol.dataReceived(b'data:hello\r\n')
        protocol.dataReceived(b':123abc\r\n\r\n')

        assert messages == [('message', 'hello')]

    def test_missing_colon(self, protocol, messages):
        """
        When a line is received that doesn't contain a ':' character, the whole
        line should be treated as the field and the value should be an empty
        string.
        """
        protocol.dataReceived(b'data\r\n\r\n')

        assert messages == [('message', '')]

    def test_trim_only_last_newline(self, protocol, messages):
        """
        When multiline data is received, only the final newline character
        should be stripped before the data is passed to the handler.
        """
        protocol.dataReceived(b'data:\r')
        protocol.dataReceived(b'data:\n')
        protocol.dataReceived(b'data:\r\n\r\n')

        assert messages == [('message', '\n\n')]

    def test_multiple_data_parts(self, protocol, messages):
        """
        When data is received in multiple parts, the parts should be collected
        to form the lines of the event.
        """
        protocol.dataReceived(b'data:')
        protocol.dataReceived(b' hello\r\n')
        protocol.dataReceived(b'\r\n')

        assert messages == [('message', 'hello')]

    def test_unicode_data(self, protocol, messages):
        """
        When unicode data encoded as UTF-8 is received, the characters should
        be decoded correctly.
        """
        protocol.dataReceived(u'data:hëlló\r\n\r\n'.encode('utf-8'))

        assert messages == [('message', u'hëlló')]

    def test_line_too_long(self):
        """
        When a line is received that is beyond the maximum allowed length,
        the transport should be in 'disconnecting' state due to a request to
        lose the connection.
        """
        protocol = make_protocol(max_length=8)
        assert not protocol.transport.disconnecting

        protocol.dataReceived(
            'data:{}\r\n\r\n'.format('x' * 9).encode('utf-8'))

        assert protocol.transport.disconnecting

    def test_incomplete_line_too_long(self):
        """
        When a part of a line is received that is beyond the maximum allowed
        length, the transport should be in 'disconnecting' state due to a
        request to lose the connection.
        """
        protocol = make_protocol(max_length=8)
        assert not protocol.transport.disconnecting

        protocol.dataReceived('data:{}'.format('x' * 9).encode('utf-8'))

        assert protocol.transport.disconnecting

    def test_transport_disconnecting(self, protocol, messages):
        """
        When the transport for the protocol is disconnecting, processing should
        be halted.
        """
        protocol.transport.disconnecting = True
        protocol.dataReceived(b'data:hello\r\n\r\n')

        assert messages == []

    def test_transport_connection_lost(self, protocol):
        """
        When the connection is lost, the finished deferred should be called.
        """
        finished = protocol.when_finished()

        protocol.connectionLost()

        assert_that(finished, succeeded(Is(None)))

    def test_transport_connection_lost_no_callback(self, protocol):
        """
        When the connection is lost and the finished deferred hasn't been set,
        nothing should happen.
        """
        protocol.connectionLost()

    def test_multiple_events_resets_the_event_type(self, protocol, messages):
        """
        After an event is consumed with a custom event type, the event type
        should be reset to the default, and the handler should receive further
        messages with the default event type.
        """
        # Event 1
        protocol.dataReceived(b'event:status\r\n')
        protocol.dataReceived(b'data:hello\r\n')
        protocol.dataReceived(b'\r\n')

        # Event 2
        protocol.dataReceived(b'data:world\r\n')
        protocol.dataReceived(b'\r\n')

        assert messages == [
            ('status', 'hello'),
            ('message', 'world'),
        ]

    def test_timeout(self):
        """
        When a timeout value is set, the timeout should be triggered once the
        timeout has elapsed and should disconnect the transport.
        """
        timeout = 5
        clock = Clock()
        protocol = make_protocol(timeout=timeout, reactor=clock)
        protocol.connectionMade()

        assert not protocol.transport.disconnecting

        clock.advance(timeout)
        # Timeout should be triggered
        assert protocol.transport.disconnecting

    def test_timeout_reset(self):
        """
        When a timeout value is set, the timeout should be reset once new data
        has been received.
        """
        timeout = 5
        clock = Clock()
        protocol = make_protocol(timeout=timeout, reactor=clock)
        protocol.connectionMade()

        # Advance a bit, but not up to the timeout
        clock.advance(timeout / 2.0)
        assert not protocol.transport.disconnecting

        # Send some data "down the pipe"
        protocol.dataReceived(b'event:status\r\n')

        # Advance beyond the original deadline, but not beyond the new one
        clock.advance(timeout / 2.0 + timeout / 4.0)
        # Timeout should not be triggered
        assert not protocol.transport.disconnecting

        # Advance beyond the new deadline
        clock.advance(timeout / 2.0)
        # Timeout should be triggered
        assert protocol.transport.disconnecting
