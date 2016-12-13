import json

from klein import Klein
from twisted.internet.endpoints import serverFromString
from twisted.logger import Logger
from twisted.web.http import OK, NOT_IMPLEMENTED, SERVICE_UNAVAILABLE
from twisted.web.server import Site


def write_request_json(request, json_obj):
    request.setHeader('Content-Type', 'application/json')
    request.write(json.dumps(json_obj).encode('utf-8'))


class MarathonAcmeServer(object):

    app = Klein()
    log = Logger()

    def __init__(self, responder_resource):
        """
        :param responder_resource:
            An ``IResponse`` used to respond to ACME HTTP challenge validation
            requests.
        """
        self.responder_resource = responder_resource
        self.health_handler = None

    def listen(self, reactor, endpoint_description):
        """
        Run the server, i.e. start listening for requests on the given host and
        port.

        :param reactor: The ``IReactorTCP`` to use.
        :param endpoint_description:
            The Twisted description for the endpoint to listen on.
        :return:
            A deferred that returns an object that provides ``IListeningPort``.
        """
        endpoint = serverFromString(reactor, endpoint_description)
        return endpoint.listen(Site(self.app.resource()))

    @app.route('/.well-known/acme-challenge/', branch=True, methods=['GET'])
    def acme_challenge(self, request):
        """
        Respond to ACME challenge validation requests on
        ``/.well-known/acme-challenge/`` using the ACME responder resource.
        """
        return self.responder_resource

    def set_health_handler(self, health_handler):
        """
        Set the handler for the health endpoint.

        :param health_handler:
            The handler for health status requests. This must be a callable
            that returns a Health object.
        """
        self.health_handler = health_handler

    @app.route('/health', methods=['GET'])
    def health(self, request):
        """ Listens to incoming health checks from Marathon on ``/health``. """
        if self.health_handler is None:
            return self._no_health_handler(request)

        health = self.health_handler()
        response_code = OK if health.healthy else SERVICE_UNAVAILABLE
        request.setResponseCode(response_code)
        write_request_json(request, health.json_message)

    def _no_health_handler(self, request):
        self.log.warn('Request to /health made but no handler is set')
        request.setResponseCode(NOT_IMPLEMENTED)
        write_request_json(request, {
            'error': 'Cannot determine service health: no handler set'
        })


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
