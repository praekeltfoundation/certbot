import json

from twisted.python import log
from twisted.web.http import (
    OK, INTERNAL_SERVER_ERROR, NOT_IMPLEMENTED, SERVICE_UNAVAILABLE)

from klein import Klein

from certbot.utils import json_dumpb


class MarathonEventServer(object):

    app = Klein()
    event_dispatch = {}

    def __init__(self, health_handler):
        self.health_handler = health_handler

    def add_handler(self, event_type, event_handler):
        self.event_dispatch[event_type] = event_handler

    def run(self, host, port, log_file=None):
        self.app.run(host, port, log_file)

    @app.route('/')
    def index(self, request):
        request.setHeader('Content-Type', 'application/json')
        return json_dumpb({})

    @app.route('/events')
    def events(self, request):
        """
        Listens to incoming events from Marathon on ``/events``.

        :param klein.app.KleinRequest request:
            The Klein HTTP request
        """
        request.setHeader('Content-Type', 'application/json')
        event = json.load(request.content)
        handler = self.event_dispatch.get(event.get('eventType'))
        if handler is None:
            return self.handle_unknown_event(request, event)

        d = handler(event)
        d.addCallback(self.event_handler_success, request)
        d.addErrback(self.event_handler_failure, request)

        return d

    def event_handler_success(self, response, request):
        request.setResponseCode(OK)
        return json.dumps(response)

    def event_handler_failure(self, error, request):
        request.setResponseCode(INTERNAL_SERVER_ERROR)
        return json_dumpb(error.message())

    def handle_unknown_event(self, request, event):
        event_type = event.get('eventType')
        request.setResponseCode(NOT_IMPLEMENTED)
        log.msg('Not handling event type: %s' % (event_type,))
        return json_dumpb({
            'error': 'Event type %s not supported.' % (event_type,)
        })

    @app.route('/health')
    def health(self, request):
        health = self.health_handler()
        response_code = OK if health.healthy else SERVICE_UNAVAILABLE
        request.setResponseCode(response_code)
        request.setHeader('Content-Type', 'application/json')
        return json_dumpb(health.json_message)


class Health(object):
    def __init__(self, healthy, json_message={}):
        self.healthy = healthy
        self.json_message = json_message
