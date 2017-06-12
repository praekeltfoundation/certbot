import cgi
import json

from requests.exceptions import HTTPError
from treq.client import HTTPClient as treq_HTTPClient
from treq.content import json_content
from twisted.internet.defer import DeferredList
from twisted.logger import Logger, LogLevel
from twisted.web.http import OK
from uritools import uricompose, uridecode, urisplit

from marathon_acme.sse_protocol import SseProtocol


def get_single_header(headers, key):
    """
    Get a single value for the given key out of the given set of headers.

    :param twisted.web.http_headers.Headers headers:
        The set of headers in which to look for the header value
    :param str key:
        The header key
    """
    raw_headers = headers.getRawHeaders(key)
    if raw_headers is None:
        return None

    # Take the final header as the authorative
    header, _ = cgi.parse_header(raw_headers[-1])
    return header


def raise_for_status(response):
    """
    Raises a `requests.exceptions.HTTPError` if the response did not succeed.
    Adapted from the Requests library:
    https://github.com/kennethreitz/requests/blob/v2.8.1/requests/models.py#L825-L837
    """
    http_error_msg = ''

    if 400 <= response.code < 500:
        http_error_msg = '%s Client Error for url: %s' % (
            response.code, uridecode(response.request.absoluteURI))

    elif 500 <= response.code < 600:
        http_error_msg = '%s Server Error for url: %s' % (
            response.code, uridecode(response.request.absoluteURI))

    if http_error_msg:
        raise HTTPError(http_error_msg, response=response)

    return response


def raise_for_header(response, key, expected):
    header = get_single_header(response.headers, key)
    if header is None:
        raise HTTPError('Expected header "%s" to be "%s" but header not found '
                        'in response' % (key, expected,))

    if header != expected:
        raise HTTPError('Expected header "%s" to be "%s" but found "%s" '
                        'instead' % (key, expected, header,))

    return response


def default_reactor(reactor):
    if reactor is None:
        from twisted.internet import reactor
    return reactor


def default_client(client, reactor):
    """
    Set up a default client if one is not provided. Set up the default
    ``twisted.web.client.Agent`` using the provided reactor.
    """
    if client is None:
        from twisted.web.client import Agent
        client = treq_HTTPClient(Agent(reactor))

    return client


class HTTPClient(object):
    timeout = 5
    log = Logger()

    def __init__(self, url=None, client=None, reactor=None):
        """
        Create a client with the specified default URL.
        """
        self.url = url
        # Keep track of the reactor because treq uses it for timeouts in a
        # clumsy way
        self._reactor = default_reactor(reactor)
        self._client = default_client(client, self._reactor)

    def _log_request_response(self, response, method, path, kwargs):
        self.log.debug(
            '{method} {path} with args {args} returned: {code}',
            method=method, path=path, args=kwargs, code=response.code)
        return response

    def _log_request_error(self, failure, url):
        self.log.failure('Error performing request to url "{url}"', failure,
                         LogLevel.error, url=url)
        return failure

    def _compose_url(self, url, kwargs):
        """
        Compose a URL starting with the given URL (or self.url if that URL is
        None) and using the values in kwargs.

        :param str url:
            The base URL to use. If None, ``self.url`` will be used instead.
        :param dict kwargs:
            A dictionary of values to override in the base URL. Relevant keys
            will be popped from the dictionary.
        """
        if url is None:
            url = self.url

        if url is not None:
            split_result = urisplit(url)
            userinfo = split_result.userinfo

        # Build up the kwargs to pass to uricompose
        compose_kwargs = {}
        for key in ['scheme', 'host', 'port', 'path', 'fragment']:
            if key in kwargs:
                compose_kwargs[key] = kwargs.pop(key)
            elif split_result is not None:
                compose_kwargs[key] = getattr(split_result, key)

        if 'params' in kwargs:
            compose_kwargs['query'] = kwargs.pop('params')
        elif split_result is not None:
            compose_kwargs['query'] = split_result.query

        # Take the userinfo out of the URL and pass as 'auth' to treq so it can
        # be used for HTTP basic auth headers
        if 'auth' not in kwargs and userinfo is not None:
            # treq expects a 2-tuple (username, password)
            kwargs['auth'] = tuple(userinfo.split(':', 2))

        return uricompose(**compose_kwargs)

    def request(self, method, url=None, **kwargs):
        """
        Perform a request.

        :param: method:
            The HTTP method to use (example is `GET`).
        :param: url:
            The URL to use. The default value is the URL this client was
            created with (`self.url`) (example is `http://localhost:8080`)
        :param: kwargs:
            Any other parameters that will be passed to `treq.request`, for
            example headers. Or any URL parameters to override, for example
            path, query or fragment.
        """
        url = self._compose_url(url, kwargs)

        kwargs.setdefault('timeout', self.timeout)

        d = self._client.request(method, url, reactor=self._reactor, **kwargs)

        d.addCallback(self._log_request_response, method, url, kwargs)
        d.addErrback(self._log_request_error, url)

        return d


class JsonClient(HTTPClient):
    def request(self, method, url=None, json_data=None, **kwargs):
        """
        Make a request to an API that speaks JSON. A number of basic defaults
        are set on the request that make using a JSON API easier. These
        defaults can be overridden by setting the parameters in the keyword
        args.

        :param: json_data:
            A python data structure that will be converted to a JSON string
            using `json.dumps` and used as the request body.
        """
        data = kwargs.get('data')
        headers = kwargs.get('headers', {}).copy()
        headers.setdefault('Accept', 'application/json')

        # Add JSON body if there is JSON data
        if json_data is not None:
            if data is not None:
                raise ValueError("Cannot specify both 'data' and 'json_data' "
                                 'keyword arguments')

            data = json.dumps(json_data).encode('utf-8')
            headers.setdefault('Content-Type', 'application/json')

        kwargs['headers'] = headers
        kwargs['data'] = data

        return super(JsonClient, self).request(method, url, **kwargs)


def raise_for_not_ok_status(response):
    """
    Raises a `requests.exceptions.HTTPError` if the response has a non-200
    status code.
    """
    if response.code != OK:
        raise HTTPError('Non-200 response code (%s) for url: %s' % (
            response.code, uridecode(response.request.absoluteURI)))

    return response


def _sse_content_with_protocol(response, handler):
    """
    Sometimes we need the protocol object so that we can manipulate the
    underlying transport in tests.
    """
    protocol = SseProtocol(handler)
    finished = protocol.when_finished()

    response.deliverBody(protocol)

    return finished, protocol


def sse_content(response, handler):
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

    finished, _ = _sse_content_with_protocol(response, handler)
    return finished


class MarathonClient(JsonClient):

    def __init__(self, endpoints, *args, **kwargs):
        """
        :param endpoints:
            A priority-ordered list of Marathon endpoints. Each endpoint will
            be tried one-by-one until the request succeeds or all endpoints
            fail.
        """
        super(MarathonClient, self).__init__(*args, **kwargs)
        self.endpoints = endpoints

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
        d = self.request('GET', **kwargs)
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
        d = self.request('GET', path='/v2/events', headers={
            'Accept': 'text/event-stream',
            'Cache-Control': 'no-store'
        })

        def handler(event, data):
            callback = callbacks.get(event)
            # Deserialize JSON if a callback is present
            if callback is not None:
                callback(json.loads(data))

        return d.addCallback(sse_content, handler)


class MarathonLbClient(HTTPClient):
    """
    Very basic client for accessing the ``/_mlb_signal`` endpoints on
    marathon-lb.
    """

    def __init__(self, endpoints, *args, **kwargs):
        """
        :param endpoints:
            The list of marathon-lb endpoints. All marathon-lb endpoints will
            be called at once for any request.
        """
        super(MarathonLbClient, self).__init__(*args, **kwargs)
        self.endpoints = endpoints

    def request(self, *args, **kwargs):
        return (
            DeferredList(
                [self._request(e, *args, **kwargs) for e in self.endpoints],
                consumeErrors=True)
            .addCallback(self._check_request_results))

    def _request(self, endpoint, *args, **kwargs):
        """
        Perform a request to a specific endpoint. Raise an error if the status
        code indicates a client or server error.
        """
        kwargs['url'] = endpoint
        return (super(MarathonLbClient, self).request(*args, **kwargs)
                .addCallback(raise_for_status))

    def _check_request_results(self, results):
        """
        Check the result of each request that we made. If a failure occurred,
        but some requests succeeded, log and count the failures. If all
        requests failed, raise an error.

        :return:
            The list of responses, with a None value for any requests that
            failed.
        """
        responses = []
        failed_endpoints = []
        for index, result_tuple in enumerate(results):
            success, result = result_tuple
            if success:
                responses.append(result)
            else:
                endpoint = self.endpoints[index]
                self.log.failure(
                    'Failed to make a request to a marathon-lb instance: '
                    '{endpoint}', result, LogLevel.error, endpoint=endpoint)
                responses.append(None)
                failed_endpoints.append(endpoint)

        if len(failed_endpoints) == len(self.endpoints):
            raise RuntimeError(
                'Failed to make a request to all marathon-lb instances')

        if failed_endpoints:
            self.log.error(
                'Failed to make a request to {x}/{y} marathon-lb instances: '
                '{endpoints}', x=len(failed_endpoints), y=len(self.endpoints),
                endpoints=failed_endpoints)

        return responses

    def mlb_signal_hup(self):
        """
        Trigger a SIGHUP signal to be sent to marathon-lb. Causes a full reload
        of the config as though a relevant event was received from Marathon.
        """
        return self.request('POST', path='/_mlb_signal/hup')

    def mlb_signal_usr1(self):
        """
        Trigger a SIGUSR1 signal to be sent to marathon-lb. Causes the existing
        config to be reloaded, whether it has changed or not.
        """
        return self.request('POST', path='/_mlb_signal/usr1')
