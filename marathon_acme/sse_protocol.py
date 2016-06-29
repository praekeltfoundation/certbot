from twisted.internet import error
from twisted.internet.protocol import Protocol


class SseProtocol(Protocol):
    """
    A protocol for Server-Sent Events (SSE).
    https://html.spec.whatwg.org/multipage/comms.html#server-sent-events
    """

    _buffer = b''
    MAX_LENGTH = 16384

    def __init__(self):
        self.finished = None
        self.callbacks = {}

        self._reset_event_data()

    def _reset_event_data(self):
        self.event = 'message'
        self.data = ''

    def set_finished_deferred(self, d):
        self.finished = d

    def set_callback(self, event, callback):
        self.callbacks[event] = callback

    def dataReceived(self, data):
        """
        Translates bytes into lines, and calls lineReceived.

        Copied from ``twisted.protocols.basic.LineOnlyReceiver`` but using
        str.splitlines() to split on ``\r\n``, ``\n``, and ``\r``.
        """
        lines = (self._buffer + data).splitlines()

        # str.splitlines() doesn't split the string after a trailing newline
        # character so we must check if there is a trailing newline and, if so,
        # clear the buffer as the line is "complete". Else, the line is
        # incomplete and we keep the last line in the buffer.
        if data.endswith(b'\n') or data.endswith(b'\r'):
            self._buffer = b''
        else:
            self._buffer = lines.pop(-1)

        for line in lines:
            if self.transport.disconnecting:
                # this is necessary because the transport may be told to lose
                # the connection by a line within a larger packet, and it is
                # important to disregard all the lines in that packet following
                # the one that told it to close.
                return
            if len(line) > self.MAX_LENGTH:
                return self.lineLengthExceeded(line)
            else:
                self.lineReceived(line)
        if len(self._buffer) > self.MAX_LENGTH:
            return self.lineLengthExceeded(self._buffer)

    def lineReceived(self, line):
        line = line.decode('utf-8')

        if not line:
            self._dispatch_event()
            return

        field, value = _parse_field_value(line)
        self._handle_field_value(field, value)

    def lineLengthExceeded(self, line):
        """
        Called when the maximum line length has been reached.
        Copied from ``twisted.protocols.basic.LineOnlyReceiver``.
        """
        return error.ConnectionLost('Line length exceeded')

    def _handle_field_value(self, field, value):
        """ Handle the field, value pair. """
        if field == 'event':
            self.event = value
        elif field == 'data':
            self.data += (value + '\n')
        elif field == 'id':
            # Not implemented
            pass
        elif field == 'retry':
            # Not implemented
            pass
        # Otherwise, ignore

    def _dispatch_event(self):
        """
        Dispatch the event to the relevant callback if one is present.
        """
        callback = self.callbacks.get(self.event)
        if callback is not None:
            data = self._prepare_data()
            if data is not None:
                callback(data)

        self._reset_event_data()

    def _prepare_data(self):
        """
        Prepare the data to be delivered. Remove a trailing LF character if
        present. Return the prepared data.
        """
        data = self.data

        # If the data is empty, abort
        if not data:
            return None

        # If last character is an LF, strip it.
        if data.endswith('\n'):
            data = data[:-1]
        return data

    def connectionLost(self, reason):
        if self.finished is not None:
            self.finished.callback(None)


def _parse_field_value(line):
    """ Parse the field and value from a line. """
    if line.startswith(':'):
        # Ignore the line
        return None, None

    if ':' not in line:
        # Treat the entire line as the field, use empty string as value
        return line, ''

    # Else field is before the ':' and value is after
    field, value = line.split(':', 1)

    # If value starts with a space, remove it.
    value = value[1:] if value.startswith(' ') else value

    return field, value
