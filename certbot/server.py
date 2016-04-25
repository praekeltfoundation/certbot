import json

from twisted.python import log
from twisted.web.http import (
    OK, INTERNAL_SERVER_ERROR, NOT_IMPLEMENTED, SERVICE_UNAVAILABLE)

from klein import Klein


class MarathonEventServer(object):

    app = Klein()
    event_dispatch = {}

    def __init__(self, health_handler):
        self.health_handler = health_handler

    def add_handler(self, event_type, event_handler):
        self.event_dispatch[event_type] = event_handler

    def run(self, host, port, log_file=None):
        self.app.run(host, port, log_file)

    def _return_json(self, json_obj, request):
        request.setHeader('Content-Type', 'application/json; charset=utf-8')
        return json.dumps(json_obj).encode('utf-8')

    def _ok_response(self, json_obj, request):
        request.setResponseCode(OK)
        return self._return_json(json_obj, request)

    def _error_response(self, failure, request):
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
        event = json.load(request.content)
        handler = self.event_dispatch.get(event.get('eventType'))
        if handler is None:
            return self.handle_unknown_event(request, event)

        d = handler(event)
        d.addCallback(self._ok_response, request)
        d.addErrback(self._error_response, request)

        return d

    def handle_unknown_event(self, request, event):
        event_type = event.get('eventType')
        request.setResponseCode(NOT_IMPLEMENTED)
        log.msg('Not handling event type: %s' % (event_type,))
        return self._return_json({
            'error': 'Event type %s not supported.' % (event_type,)
        }, request)

    @app.route('/health')
    def health(self, request):
        health = self.health_handler()
        response_code = OK if health.healthy else SERVICE_UNAVAILABLE
        request.setResponseCode(response_code)
        return self._return_json(health.json_message, request)


class Health(object):
    def __init__(self, healthy, json_message={}):
        self.healthy = healthy
        self.json_message = json_message
