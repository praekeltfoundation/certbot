import json

from requests.exceptions import HTTPError

from treq.content import json_content

from twisted.web.http import OK

from uritools import uridecode

from marathon_acme.clients._base import (
    HTTPClient, raise_for_header, raise_for_status)
from marathon_acme.sse_protocol import SseProtocol


def raise_for_not_ok_status(response):
    """
    Raises a `requests.exceptions.HTTPError` if the response has a non-200
    status code.
    """
    if response.code != OK:
        raise HTTPError('Non-200 response code (%s) for url: %s' % (
            response.code, uridecode(response.request.absoluteURI)))

    return response


def _sse_content_with_protocol(response, handler, **sse_kwargs):
    """
    Sometimes we need the protocol object so that we can manipulate the
    underlying transport in tests.
    """
    protocol = SseProtocol(handler, **sse_kwargs)
    finished = protocol.when_finished()

    response.deliverBody(protocol)

    return finished, protocol


def sse_content(response, handler, **sse_kwargs):
    """
    Callback to collect the Server-Sent Events content of a response. Callbacks
    passed will receive event data.

    :param response:
        The response from the SSE request.
    :param handler:
        The handler for the SSE protocol.
    """
    # An SSE response must be 200/OK and have content-type 'text/event-stream'
    raise_for_not_ok_status(response)
    raise_for_header(response, 'Content-Type', 'text/event-stream')

    finished, _ = _sse_content_with_protocol(response, handler, **sse_kwargs)
    return finished


class MarathonClient(HTTPClient):
    def __init__(self, endpoints, sse_kwargs=None, **kwargs):
        """
        :param endpoints:
            A priority-ordered list of Marathon endpoints. Each endpoint will
            be tried one-by-one until the request succeeds or all endpoints
            fail.
        """
        super(MarathonClient, self).__init__(**kwargs)
        self.endpoints = endpoints
        self._sse_kwargs = {} if sse_kwargs is None else sse_kwargs

    def request(self, *args, **kwargs):
        d = self._request(None, list(self.endpoints), *args, **kwargs)
        d.addErrback(self._log_all_endpoints_failed)
        return d

    def _request(self, failure, endpoints, *args, **kwargs):
        """
        Recursively make requests to each endpoint in ``endpoints``.
        """
        # We've run out of endpoints, fail
        if not endpoints:
            return failure

        endpoint = endpoints.pop(0)
        d = super(MarathonClient, self).request(*args, url=endpoint, **kwargs)

        # If something goes wrong, call ourselves again with the remaining
        # endpoints
        d.addErrback(self._request, endpoints, *args, **kwargs)
        return d

    def _log_all_endpoints_failed(self, failure):
        # Just log an error so it is clear what has happened and return the
        # final failure. Individual failures should have been logged via
        # _log_request_error().
        self.log.error('Failed to make a request to all Marathon endpoints')
        return failure

    def get_json_field(self, field, **kwargs):
        """
        Perform a GET request and get the contents of the JSON response.

        Marathon's JSON responses tend to contain an object with a single key
        which points to the actual data of the response. For example /v2/apps
        returns something like {"apps": [ {"app1"}, {"app2"} ]}. We're
        interested in the contents of "apps".

        This method will raise an error if:
        * There is an error response code
        * The field with the given name cannot be found
        """
        d = self.request(
            'GET', headers={'Accept': 'application/json'}, **kwargs)
        d.addCallback(raise_for_status)
        d.addCallback(raise_for_header, 'Content-Type', 'application/json')
        d.addCallback(json_content)
        d.addCallback(self._get_json_field, field)
        return d

    def _get_json_field(self, response_json, field_name):
        """
        Get a JSON field from the response JSON.

        :param: response_json:
            The parsed JSON content of the response.
        :param: field_name:
            The name of the field in the JSON to get.
        """
        if field_name not in response_json:
            raise KeyError('Unable to get value for "%s" from Marathon '
                           'response: "%s"' % (
                               field_name, json.dumps(response_json),))

        return response_json[field_name]

    def get_apps(self):
        """
        Get the currently running Marathon apps, returning a list of app
        definitions.
        """
        return self.get_json_field('apps', path='/v2/apps')

    def get_events(self, callbacks):
        """
        Attach to Marathon's event stream using Server-Sent Events (SSE).

        :param callbacks:
            A dict mapping event types to functions that handle the event data
        """
        d = self.request(
            'GET', path='/v2/events', unbuffered=True,
            # The event_type parameter was added in Marathon 1.3.7. It can be
            # used to specify which event types we are interested in. On older
            # versions of Marathon it is ignored, and we ignore events we're
            # not interested in anyway.
            params={'event_type': sorted(callbacks.keys())},
            headers={
                'Accept': 'text/event-stream',
                'Cache-Control': 'no-store'
            })

        def handler(event, data):
            callback = callbacks.get(event)
            # Deserialize JSON if a callback is present
            if callback is not None:
                callback(json.loads(data))

        return d.addCallback(
            sse_content, handler, reactor=self._reactor, **self._sse_kwargs)
