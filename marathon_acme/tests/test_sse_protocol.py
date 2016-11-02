# -*- coding: utf-8 -*-
from testtools.assertions import assert_that
from testtools.matchers import Contains, Equals, IsInstance
from twisted.internet.defer import Deferred
from twisted.internet.error import ConnectionLost

from marathon_acme.sse_protocol import SseProtocol


class DummyTransport(object):
    disconnecting = False


class TestSseProtocol(object):
    def setup_method(self):
        self.protocol = SseProtocol()

        self.transport = DummyTransport()
        self.protocol.transport = self.transport

    def test_default_callback(self):
        """
        When data is received, followed by a blank line, the default callback,
        'message', should be called with the data.
        """
        data = []
        self.protocol.set_callback('message', data.append)
        self.protocol.dataReceived(b'data:hello\r\n\r\n')

        assert_that(data, Equals(['hello']))

    def test_multiline_data(self):
        """
        When multiple lines of data are specified in a single event, those
        lines should be received by the callback with a '\n' character
        separating them.
        """
        data = []
        self.protocol.set_callback('message', data.append)
        self.protocol.dataReceived(b'data:hello\r\ndata:world\r\n\r\n')

        assert_that(data, Equals(['hello\nworld']))

    def test_different_newlines(self):
        """
        When data is received with '\r\n', '\n', or '\r', lines should be split
        on those characters.
        """
        data = []
        self.protocol.set_callback('message', data.append)
        self.protocol.dataReceived(b'data:hello\ndata:world\r\r\n')

        assert_that(data, Equals(['hello\nworld']))

    def test_empty_data(self):
        """
        When the data field is specified in an event but no data is given, the
        callback should receive an empty string.
        """
        data = []
        self.protocol.set_callback('message', data.append)
        self.protocol.dataReceived(b'data:\r\n\r\n')

        assert_that(data, Equals(['']))

    def test_no_data(self):
        """
        When the data field is not specified and the event is completed, the
        callback should not be called.
        """
        data = []
        self.protocol.set_callback('message', data.append)
        self.protocol.dataReceived(b'\r\n')

        assert_that(data, Equals([]))

    def test_space_before_value(self):
        """
        When a field/value pair is received, and there is a space before the
        value, the leading space should be stripped.
        """
        data = []
        self.protocol.set_callback('message', data.append)
        self.protocol.dataReceived(b'data: hello\r\n\r\n')

        assert_that(data, Equals(['hello']))

    def test_space_before_value_strip_only_first_space(self):
        """
        When a field/value pair is received, and there are multiple spaces at
        the start of the value, the leading space should be stripped and the
        other spaces left intact.
        """
        data = []
        self.protocol.set_callback('message', data.append)
        self.protocol.dataReceived(b'data:%s\r\n\r\n' % (b' ' * 4,))

        assert_that(data, Equals([' ' * 3]))

    def test_custom_event(self):
        """
        If a custom event is set for an event, a callback for that event should
        be called.
        """
        data = []
        self.protocol.set_callback('my_event', data.append)
        self.protocol.dataReceived(b'event:my_event\r\n')
        self.protocol.dataReceived(b'data:hello\r\n\r\n')

        assert_that(data, Equals(['hello']))

    def test_multiple_events(self):
        """
        If a multiple different event types are received, the callbacks for
        each of those events should be called.
        """
        data1 = []
        data2 = []
        self.protocol.set_callback('test1', data1.append)
        self.protocol.set_callback('test2', data2.append)

        self.protocol.dataReceived(b'event:test1\r\n')
        self.protocol.dataReceived(b'data:hello\r\n\r\n')
        self.protocol.dataReceived(b'event:test2\r\n')
        self.protocol.dataReceived(b'data:world\r\n\r\n')

        assert_that(data1, Equals(['hello']))
        assert_that(data2, Equals(['world']))

    def test_id_ignored(self):
        """
        When the id field is included in an event, it should be ignored.
        """
        data = []
        self.protocol.set_callback('message', data.append)
        self.protocol.dataReceived(b'data:hello\r\n')
        self.protocol.dataReceived(b'id:123\r\n\r\n')

        assert_that(data, Equals(['hello']))

    def test_retry_ignored(self):
        """
        When the retry field is included in an event, it should be ignored.
        """
        data = []
        self.protocol.set_callback('message', data.append)
        self.protocol.dataReceived(b'data:hello\r\n')
        self.protocol.dataReceived(b'retry:123\r\n\r\n')

        assert_that(data, Equals(['hello']))

    def test_unknown_field_ignored(self):
        """
        When an unknown field is included in an event, it should be ignored.
        """
        data = []
        self.protocol.set_callback('message', data.append)
        self.protocol.dataReceived(b'data:hello\r\n')
        self.protocol.dataReceived(b'somefield:123\r\n\r\n')

        assert_that(data, Equals(['hello']))

    def test_leading_colon_ignored(self):
        """
        When a line is received starting with a ':' character, the line should
        be ignored.
        """
        data = []
        self.protocol.set_callback('message', data.append)
        self.protocol.dataReceived(b'data:hello\r\n')
        self.protocol.dataReceived(b':123abc\r\n\r\n')

        assert_that(data, Equals(['hello']))

    def test_missing_colon(self):
        """
        When a line is received that doesn't contain a ':' character, the whole
        line should be treated as the field and the value should be an empty
        string.
        """
        data = []
        self.protocol.set_callback('message', data.append)
        self.protocol.dataReceived(b'data\r\n')
        self.protocol.dataReceived(b'data:hello\r\n\r\n')

        assert_that(data, Equals(['\nhello']))

    def test_trim_only_last_newline(self):
        """
        When multiline data is received, only the final newline character
        should be stripped before the data is passed to the callback.
        """
        data = []
        self.protocol.set_callback('message', data.append)
        self.protocol.dataReceived(b'data:\r')
        self.protocol.dataReceived(b'data:\n')
        self.protocol.dataReceived(b'data:\r\n\r\n')

        assert_that(data, Equals(['\n\n']))

    def test_multiple_data_parts(self):
        """
        When data is received in multiple parts, the parts should be collected
        to form the lines of the event.
        """
        data = []
        self.protocol.set_callback('message', data.append)
        self.protocol.dataReceived(b'data:')
        self.protocol.dataReceived(b' hello\r\n')
        self.protocol.dataReceived(b'\r\n')

        assert_that(data, Equals(['hello']))

    def test_unicode_data(self):
        """
        When unicode data encoded as UTF-8 is received, the characters should
        be decoded correctly.
        """
        data = []
        self.protocol.set_callback('message', data.append)
        self.protocol.dataReceived(u'data:hëlló\r\n\r\n'.encode('utf-8'))

        assert_that(data, Equals([u'hëlló']))

    def test_line_too_long(self):
        """
        When a line is received that is beyond the maximum allowed length,
        ``dataReceived`` should return a ``ConnectionLost`` error.
        """
        data = []
        self.protocol.set_callback('message', data.append)
        err = self.protocol.dataReceived(b'data:%s\r\n\r\n' % (
            b'x' * (self.protocol.MAX_LENGTH + 1),))

        assert_that(err, IsInstance(ConnectionLost))
        assert_that(str(err), Contains('Line length exceeded'))

    def test_incomplete_line_too_long(self):
        """
        When a part of a line is received that is beyond the maximum allowed
        length, ``dataReceived`` should return a ``ConnectionLost`` error.
        """
        data = []
        self.protocol.set_callback('message', data.append)
        err = self.protocol.dataReceived(b'data:%s' % (
            b'x' * (self.protocol.MAX_LENGTH + 1),))

        assert_that(err, IsInstance(ConnectionLost))
        assert_that(str(err), Contains('Line length exceeded'))

    def test_transport_disconnecting(self):
        """
        When the transport for the protocol is disconnecting, processing should
        be halted.
        """
        data = []
        self.protocol.set_callback('message', data.append)
        self.transport.disconnecting = True
        self.protocol.dataReceived(b'data:hello\r\n\r\n')

        assert_that(data, Equals([]))

    def test_transport_connection_lost(self):
        """
        When the connection is lost, the finished deferred should be called.
        """
        finished = Deferred()
        self.protocol.set_finished_deferred(finished)

        self.protocol.connectionLost('Something went wrong')

        assert_that(finished.called, Equals(True))

    def test_transport_connection_lost_no_callback(self):
        """
        When the connection is lost and the finished deferred hasn't been set,
        nothing should happen.
        """
        self.protocol.connectionLost('Something went wrong')

    def test_multiple_events_resets_the_event_type(self):
        """
        After an event is consumed with a custom event type, the event type
        should be reset to the default, and the default callback should
        receive further messages without a specified event type.
        """
        message_data = []
        self.protocol.set_callback('message', message_data.append)

        status_data = []
        self.protocol.set_callback('status', status_data.append)

        # Event 1
        self.protocol.dataReceived(b'event:status\r\n')
        self.protocol.dataReceived(b'data:hello\r\n')
        self.protocol.dataReceived(b'\r\n')

        # Event 2
        self.protocol.dataReceived(b'data:world\r\n')
        self.protocol.dataReceived(b'\r\n')

        assert_that(status_data, Equals(['hello']))
        assert_that(message_data, Equals(['world']))
