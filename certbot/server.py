import cgi
import json

from twisted.python import log
from twisted.web.http import (
    OK, INTERNAL_SERVER_ERROR, NOT_IMPLEMENTED, SERVICE_UNAVAILABLE)

from klein import Klein


# The below 3 methods are roughly stolen from the treq.content module and help
# to decode JSON content from requests correctly.
def _encoding_from_headers(headers):
    content_types = headers.getRawHeaders('content-type')
    if content_types is None:
        return None

    # This seems to be the choice browsers make when encountering multiple
    # content-type headers.
    content_type, params = cgi.parse_header(content_types[-1])

    if 'charset' in params:
        return params.get('charset').strip("'\"")


def _text_content(request, encoding='ISO-8859-1'):
    e = _encoding_from_headers(request.requestHeaders)
    content = request.content.read()

    if e is not None:
        return content.decode(e)

    return content.decode(encoding)


def _json_content(request):
    return json.loads(_text_content(request))


class MarathonEventServer(object):

    app = Klein()
    event_dispatch = {}
    health_handler = None

    def add_handler(self, event_type, event_handler):
        """
        Add a handler for a certain event type.

        :param event_type:
            The type of event for which this handler should be invoked.
        :param event_handler:
            The handler for the given event type. This must be a callable that
            returns a Deferred.
        """
        self.event_dispatch[event_type] = event_handler

    def set_health_handler(self, health_handler):
        """
        Set the handler for the health endpoint.

        :param health_handler:
            The handler for health status requests. This must be a callable
            that returns a Health object.
        """
        self.health_handler = health_handler

    def run(self, host, port, log_file=None):
        """
        Run the server, i.e. start listening for requests on the given host and
        port.

        :param host:
            The address to the interface to listen on.
        :param port:
            The port to bind to.
        :param log_file:
            The file to write logs to.
        """
        self.app.run(host, port, log_file)

    def _return_json(self, json_obj, request):
        """
        Return a serialized JSON object and set the appropriate Content-Type
        header.
        """
        request.setHeader('Content-Type', 'application/json; charset=utf-8')
        return json.dumps(json_obj).encode('utf-8')

    def _ok_response(self, json_obj, request):
        """ Return a 200/OK response with a JSON object. """
        request.setResponseCode(OK)
        return self._return_json(json_obj, request)

    def _error_response(self, failure, request):
        """ Return a 503 response with a JSON object. """
        request.setResponseCode(INTERNAL_SERVER_ERROR)
        return self._return_json({'error': failure.getErrorMessage()}, request)

    @app.route('/')
    def index(self, request):
        return self._ok_response({}, request)

    @app.route('/events')
    def events(self, request):
        """
        Listens to incoming events from Marathon on ``/events``.

        :param klein.app.KleinRequest request:
            The Klein HTTP request
        """
        event = _json_content(request)
        handler = self.event_dispatch.get(event.get('eventType'))
        if handler is None:
            return self._handle_unknown_event(request, event)

        d = handler(event)
        d.addCallback(self._ok_response, request)
        d.addErrback(self._error_response, request)

        return d

    def _handle_unknown_event(self, request, event):
        event_type = event.get('eventType')
        request.setResponseCode(NOT_IMPLEMENTED)
        log.msg('Not handling event type: %s' % (event_type,))
        return self._return_json({
            'error': 'Event type %s not supported.' % (event_type,)
        }, request)

    @app.route('/health')
    def health(self, request):
        """
        Listens to incoming pings from Marathon on ``/events``.

        :param klein.app.KleinRequest request:
            The Klein HTTP request
        """
        if self.health_handler is None:
            return self._no_health_handler(request)

        health = self.health_handler()
        response_code = OK if health.healthy else SERVICE_UNAVAILABLE
        request.setResponseCode(response_code)
        return self._return_json(health.json_message, request)

    def _no_health_handler(self, request):
        request.setResponseCode(NOT_IMPLEMENTED)
        return self._return_json({
            'error': 'Cannot determine service health: no handler set'
        }, request)


class Health(object):
    def __init__(self, healthy, json_message={}):
        """
        Health objects store the current health status of the service.

        :param bool healthy:
            The service is either healthy (True) or unhealthy (False).
        :param json_message:
            An object that can be serialized as JSON that will be sent as a
            message when the health status is requested.
        """
        self.healthy = healthy
        self.json_message = json_message
