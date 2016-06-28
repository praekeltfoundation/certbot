import cgi

from requests.exceptions import HTTPError

from twisted.protocols.basic import LineReceiver


class EventSourceProtocol(LineReceiver):
    """
    A protocol for Server-Sent Events (SSE).
    https://html.spec.whatwg.org/multipage/comms.html#server-sent-events
    """

    def __init__(self, finished, callbacks):
        """
        Initialize the protocol.

        :param finished:
            A deferred that will be called when the connection is closed
        :param callbacks:
            A dict mapping event types to functions that will handle their data
        """
        self.finished = finished
        self.callbacks = callbacks

        self._reset_event_data()

    def _reset_event_data(self):
        self.event = 'message'
        self.data = ''

    def lineReceived(self, line):
        line = line.decode('utf-8')

        if not line:
            self._dispatch_event()
            return

        field, value = _parse_field_value(line)
        self._handle_field_value(field, value)

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
        self.finished.callback(None)


def _parse_field_value(line):
    """ Parse the field and value from a line. """
    colon_index = line.find(':')
    if colon_index == 0:
        # Ignore if line starts with colon
        field, value = None, None
    elif colon_index == -1:
        # Colon not found, treat whole line as field
        field = line
        value = ''
    else:
        # Colon found, field is before it, value is after it
        field = line[:colon_index]
        value = line[colon_index + 1:]
        # If value starts with a space, remove it.
        value[1:] if value.startswith(' ') else value

    return field, value


def raise_for_es_status(response):
    """
    Raise an HTTPError if the response's status code is not 200 or the
    Content-Type header is not text/event-stream.
    """
    if response.code != 200:
        raise HTTPError(
            'Non-200 (%d) response code for EventSource' % (response.code,))

    # Content-Type must be text/event-stream
    content_types = response.headers.getRawHeaders('Content-Type')
    if content_types is None:
        raise HTTPError('No Content-Type header in response')

    # Respect the last content-type header
    content_type, _ = cgi.parse_header(content_types[-1])
    if content_type != 'text/event-stream':
        raise HTTPError('Expected content-type "text/event-stream" got "%s" '
                        'instead' % (content_type,))