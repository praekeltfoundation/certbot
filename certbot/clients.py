import json
import treq

from twisted.internet import reactor
from twisted.python import log
from twisted.web import client
from twisted.web.http import OK

from uritools import uricompose, urisplit

# Twisted's default HTTP11 client factory is way too verbose
client._HTTP11ClientFactory.noisy = False


class JsonClient(object):
    debug = False
    clock = reactor
    timeout = 5
    agent = None

    def __init__(self, endpoint):
        """
        Create a client with the specified default endpoint.
        """
        self.endpoint = urisplit(endpoint)
        self.pool = client.HTTPConnectionPool(self.clock, persistent=False)

    def requester(self, *args, **kwargs):
        return treq.request(*args, **kwargs)

    def _log_http_response(self, response, method, path, data):
        log.msg('%s %s with %s returned: %s' % (
            method, path, data, response.code))
        return response

    def _log_http_error(self, failure, url):
        log.err(failure, 'Error performing request to %s' % (url,))
        return failure

    def request(self, method, path, query=None, endpoint=None, json_data=None,
                **kwargs):
        """
        Perform a request. A number of basic defaults are set on the request
        that make using a JSON API easier. These defaults can be overridden by
        setting the parameters in the keyword args.

        :param: method:
            The HTTP method to use (example is `GET`).
        :param: path:
            The URL path (example is `/v2/apps`).
        :param: query:
            The URL query parameters as a dict.
        :param: endpoint:
            The URL endpoint to use. The default value is the endpoint this
            client was created with (`self.endpoint`) (example is
            `http://localhost:8080`)
        :param: json_data:
            A python data structure that will be converted to a JSON string
            using `json.dumps` and used as the request body.
        :param: kwargs:
            Any other parameters that will be passed to `treq.request`, for
            example headers or parameters.
        """
        if endpoint is not None:
            scheme, authority = urisplit(endpoint)[:2]
        else:
            scheme, authority = self.endpoint[:2]
        url = uricompose(scheme, authority, path, query)

        data = json.dumps(json_data) if json_data else None
        requester_kwargs = {
            'headers': {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
            },
            'data': data,
            'pool': self.pool,
            'agent': self.agent,
            'timeout': self.timeout
        }
        requester_kwargs.update(kwargs)

        d = self.requester(method, url, **requester_kwargs)

        if self.debug:
            d.addCallback(self._log_http_response, method, url, data)

        d.addErrback(self._log_http_error, url)
        return d.addCallback(self._raise_for_status, url)

    def get_json(self, path, query=None, **kwargs):
        """
        Perform a GET request to the given path and return the JSON response.
        """
        d = self.request('GET', path, query, **kwargs)
        return d.addCallback(lambda response: response.json())

    def _raise_for_status(self, response, url):
        """
        Raises an `HTTPError` if the response did not succeed.
        Adapted from the Requests library:
        https://github.com/kennethreitz/requests/blob/v2.8.1/requests/models.py#L825-L837
        """
        http_error_msg = ''

        if 400 <= response.code < 500:
            http_error_msg = '%s Client Error for url: %s' % (response.code,
                                                              url)

        elif 500 <= response.code < 600:
            http_error_msg = '%s Server Error for url: %s' % (response.code,
                                                              url)

        if http_error_msg:
            raise HTTPError(http_error_msg, response)

        return response


class HTTPError(IOError):
    """
    Error raised for 4xx and 5xx response codes.
    """
    def __init__(self, message, response):
        self.response = response
        super(HTTPError, self).__init__(message)


class MarathonClient(JsonClient):

    def get_json_field(self, path, field):
        """
        Perform a GET request and get the contents of the JSON response.

        Marathon's JSON responses tend to contain an object with a single key
        which points to the actual data of the response. For example /v2/apps
        returns something like {"apps": [ {"app1"}, {"app2"} ]}. We're
        interested in the contents of "apps".
        """
        return self.get_json(path).addCallback(self._get_json_field, field)

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
            '/v2/eventSubscriptions', 'callbackUrls')

    def post_event_subscription(self, callback_url):
        """
        Post a new Marathon event subscription with the given callback URL.
        """
        d = self.request(
            'POST', '/v2/eventSubscriptions', {'callbackUrl': callback_url})
        return d.addCallback(lambda response: response.code == OK)

    def get_apps(self):
        """
        Get the currently running Marathon apps, returning a list of app
        definitions.
        """
        return self.get_json_field('/v2/apps', 'apps')

    def get_app(self, app_id):
        """
        Get information about the app with the given app ID.
        """
        return self.get_json_field('/v2/apps%s' % (app_id,), 'app')

    def get_app_tasks(self, app_id):
        """
        Get the currently running tasks for the app with the given app ID,
        returning a list of task definitions.
        """
        return self.get_json_field('/v2/apps%s/tasks' % (app_id,), 'tasks')


class ConsulClient(JsonClient):

    fallback_timeout = 2

    def __init__(self, endpoint, enable_fallback=False):
        """
        Create a Consul client.

        :param: endpoint:
            The default Consul endpoint, usually on the same node as Consular
            is running.
        :param: enable_fallback:
            Fall back to the default Consul endpoint when registering services
            on an agent that cannot be reached.
        """
        super(ConsulClient, self).__init__(endpoint)
        self.enable_fallback = enable_fallback

    def _get_agent_endpoint(self, agent_address):
        """
        Use the default endpoint to construct the agent endpoint from an
        address, i.e. use the same scheme and port but swap in the address.
        """
        return uricompose(scheme=self.endpoint.scheme, host=agent_address,
                          port=self.endpoint.port)

    def register_agent_service(self, agent_address, registration):
        """
        Register a Consul service at the given agent address.
        """
        agent_endpoint = self._get_agent_endpoint(agent_address)
        d = self.request('PUT', '/v1/agent/service/register',
                         endpoint=agent_endpoint, json_data=registration)

        if self.enable_fallback:
            d.addErrback(self._register_agent_service_fallback, registration)

        return d

    def _register_agent_service_fallback(self, failure, registration):
        """
        Fallback to the default agent endpoint (`self.endpoint`) to register
        a Consul service.
        """
        log.msg('Falling back for %s at %s.' % (
            registration['Name'], self.endpoint))
        return self.request(
            'PUT', '/v1/agent/service/register', json_data=registration,
            timeout=self.fallback_timeout)

    def deregister_agent_service(self, agent_address, service_id):
        """
        Deregister a Consul service at the given agent address.
        """
        agent_endpoint = self._get_agent_endpoint(agent_address)
        return self.request('PUT', '/v1/agent/service/deregister/%s' % (
            service_id,), endpoint=agent_endpoint)

    def put_kv(self, key, value):
        """
        Put a key/value in Consul's k/v store.
        """
        return self.request(
            'PUT', '/v1/kv/%s' % (key,), json_data=value)

    def get_kv_keys(self, keys_path, separator=None):
        """
        Get the stored keys for the given keys path from the Consul k/v store.

        :param: keys_path:
            The path to some keys (example is `consular/my-app/`).
        :param: separator:
            Get all the keys up to some separator in the key path. Useful for
            getting all the keys non-recursively for a path. For more
            information see the Consul API documentation.
        """
        query = {'keys': None}
        if separator:
            query['separator'] = separator
        return self.get_json('/v1/kv/%s' % (keys_path,), query)

    def delete_kv_keys(self, key, recurse=False):
        """
        Delete the store key(s) at the given path from the Consul k/v store.

        :param: key:
            The key or key path to be deleted.
        :param: recurse:
            Whether or not to recursively delete all subpaths of the key.
        """
        query = {'recurse': None} if recurse else None
        return self.request('DELETE', '/v1/kv/%s' % (key,), query)

    def get_catalog_nodes(self):
        """
        Get the list of active Consul nodes from the catalog.
        """
        return self.get_json('/v1/catalog/nodes')

    def get_agent_services(self, agent_address):
        """
        Get the list of running services for the given agent address.
        """
        agent_endpoint = self._get_agent_endpoint(agent_address)
        return self.get_json('/v1/agent/services', endpoint=agent_endpoint)
