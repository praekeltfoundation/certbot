import cgi
import json

from requests.exceptions import HTTPError

from treq.client import HTTPClient

from twisted.python import log
from twisted.web.http import OK

from uritools import uricompose, uridecode, urisplit


def get_content_type(headers):
    """
    Parse the Content-Type header value from the given headers.
    """
    content_types = headers.getRawHeaders('Content-Type')
    if content_types is None:
        return None

    # Take the final Content-Type header as the authorative
    content_type, _ = cgi.parse_header(content_types[-1])
    return content_type


def json_content(response):
    # Raise if content type is not application/json
    raise_for_content_type(response, 'application/json')

    # Workaround for treq not treating JSON as UTF-8 by default (RFC7158)
    # https://github.com/twisted/treq/pull/126
    # See this discussion: http://stackoverflow.com/q/9254891
    d = response.text(encoding='utf-8')
    return d.addCallback(json.loads)


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


def raise_for_content_type(response, expected):
    content_type = get_content_type(response.headers)
    if content_type is None:
        raise HTTPError('Expected content type "%s" but could not determine '
                        'content type of response' % (expected,))

    if content_type != expected:
        raise HTTPError('Expected content type "%s" but got "%s" instead' % (
            expected, content_type,))

    return response


def default_reactor(reactor):
    if reactor is None:
        from twisted.internet import reactor
    return reactor


def default_agent(agent, reactor):
    """
    Set up a default agent if one is not provided. Use a default reactor to do
    so, unless one is not provided. The agent will set up a default
    (non-persistent) connection pool if one is not provided.
    """
    if agent is None:
        from twisted.web.client import Agent
        agent = Agent(reactor)

    return agent


class JsonClient(object):
    debug = False
    timeout = 5

    def __init__(self, url=None, agent=None, reactor=None):
        """
        Create a client with the specified default URL.
        """
        self.url = url
        # Keep track of the reactor because treq uses it for timeouts in a
        # clumsy way
        self._reactor = default_reactor(reactor)
        self._client = HTTPClient(default_agent(agent, self._reactor))

    def _log_request_response(self, response, method, path, data):
        log.msg('%s %s with %s returned: %s' % (
            method, path, data, response.code))
        return response

    def _log_request_error(self, failure, url):
        log.err(failure, 'Error performing request to %s' % (url,))
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

    def request(self, method, url=None, json_data=None, **kwargs):
        """
        Perform a request. A number of basic defaults are set on the request
        that make using a JSON API easier. These defaults can be overridden by
        setting the parameters in the keyword args.

        :param: method:
            The HTTP method to use (example is `GET`).
        :param: url:
            The URL to use. The default value is the URL this client was
            created with (`self.url`) (example is `http://localhost:8080`)
        :param: json_data:
            A python data structure that will be converted to a JSON string
            using `json.dumps` and used as the request body.
        :param: kwargs:
            Any other parameters that will be passed to `treq.request`, for
            example headers. Or any URL parameters to override, for example
            path, query or fragment.
        """
        url = self._compose_url(url, kwargs)

        data = None
        headers = {'Accept': 'application/json'}

        # Add JSON body if there is JSON data
        if json_data is not None:
            data = json.dumps(json_data).encode('utf-8')
            headers['Content-Type'] = 'application/json'

        request_kwargs = {
            'headers': headers,
            'data': data,
            'timeout': self.timeout
        }
        request_kwargs.update(kwargs)

        d = self._client.request(method, url, reactor=self._reactor,
                                 **request_kwargs)

        if self.debug:
            d.addCallback(self._log_request_response, method, url, data)

        d.addErrback(self._log_request_error, url)

        return d


class MarathonClient(JsonClient):

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

    def get_event_subscriptions(self):
        """
        Get the current Marathon event subscriptions, returning a list of
        callback URLs.
        """
        return self.get_json_field(
            'callbackUrls', path='/v2/eventSubscriptions')

    def post_event_subscription(self, callback_url):
        """
        Post a new Marathon event subscription with the given callback URL.
        """
        d = self.request('POST',
                         path='/v2/eventSubscriptions',
                         params={'callbackUrl': callback_url})
        return d.addCallback(lambda response: response.code == OK)

    def delete_event_subscription(self, callback_url):
        """
        Delete the Marathon event subscription with the given callback URL.
        """
        d = self.request('DELETE',
                         path='/v2/eventSubscriptions',
                         params={'callbackUrl': callback_url})
        return d.addCallback(lambda response: response.code == OK)

    def get_apps(self):
        """
        Get the currently running Marathon apps, returning a list of app
        definitions.
        """
        return self.get_json_field('apps', path='/v2/apps')

    def get_app(self, app_id):
        """
        Get information about the app with the given app ID.
        """
        return self.get_json_field('app', path='/v2/apps%s' % (app_id,))

    def get_app_tasks(self, app_id):
        """
        Get the currently running tasks for the app with the given app ID,
        returning a list of task definitions.
        """
        return self.get_json_field(
            'tasks', path='/v2/apps%s/tasks' % (app_id,))
