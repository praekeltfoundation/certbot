import json

from twisted.internet.defer import inlineCallbacks, DeferredQueue
from twisted.trial.unittest import TestCase
from twisted.web.server import NOT_DONE_YET

from txfake import FakeHttpServer
from txfake.fake_connection import wait0

from uritools import urisplit

from certbot.clients import (
    ConsulClient, HTTPError, JsonClient, MarathonClient)


class JsonClientTestBase(TestCase):
    def setUp(self):
        self.client = self.get_client()
        self.requests = DeferredQueue()
        self.fake_server = FakeHttpServer(self.handle_request)

        self.client.agent = self.fake_server.get_agent()

    def handle_request(self, request):
        self.requests.put(request)
        return NOT_DONE_YET

    def get_client(self):
        """To be implemented by subclass"""
        raise NotImplementedError()

    def json_dumpb(self, json_data):
        return json.dumps(json_data).encode('utf-8')

    def write_json_response(self, request, json_data, response_code=200,
                            headers={'Content-Type': 'application/json'}):
        request.setResponseCode(response_code)
        for name, value in headers.items():
            request.setHeader(name, value)
        request.write(self.json_dumpb(json_data))
        request.finish()

    def read_json_response(self, request):
        return json.loads(request.content.getvalue().decode('utf-8'))

    def uri(self, path, encode=False):
        uri = '%s%s' % (self.client.endpoint.geturi(), path,)
        return uri.encode('utf-8') if encode else uri

    def parse_query(self, uri):
        """
        When Twisted parses "args" from the URI, it leaves out query parameters
        that have no value. In those cases we rather use uritools to parse the
        query parameters.
        """
        return urisplit(uri).getquerydict()


class JsonClientTest(JsonClientTestBase):

    def get_client(self):
        return JsonClient('http://localhost:8000')

    @inlineCallbacks
    def test_request(self):
        """
        When a request is made, it should be made with the correct method,
        address and headers, and should contain an empty body. The response
        should be returned.
        """
        d = self.client.request('GET', '/hello')

        request = yield self.requests.get()
        self.assertEqual(request.method, b'GET')
        self.assertEqual(request.uri, self.uri('/hello', encode=True))
        self.assertEqual(request.getHeader('content-type'), 'application/json')
        self.assertEqual(request.getHeader('accept'), 'application/json')
        self.assertEqual(request.content.read(), b'')

        request.setResponseCode(200)
        request.write(b'hi\n')
        request.finish()

        response = yield d
        text = yield response.text()
        self.assertEqual(text, 'hi\n')

    @inlineCallbacks
    def test_request_json_data(self):
        """
        When a request is made with the json_data parameter set, that data
        should be sent as JSON.
        """
        d = self.client.request('GET', '/hello', json_data={'test': 'hello'})

        request = yield self.requests.get()
        self.assertEqual(request.method, b'GET')
        self.assertEqual(request.uri, self.uri('/hello', encode=True))
        self.assertEqual(self.read_json_response(request), {'test': 'hello'})

        request.setResponseCode(200)
        request.finish()

        yield d

    @inlineCallbacks
    def test_request_endpoint(self):
        """
        When a request is made with the endpoint parameter set, that parameter
        should be used as the endpoint.
        """
        d = self.client.request('GET', '/hello',
                                endpoint='http://localhost:9000')

        request = yield self.requests.get()
        self.assertEqual(request.method, b'GET')
        self.assertEqual(request.uri, b'http://localhost:9000/hello')

        request.setResponseCode(200)
        request.finish()

        yield d

    @inlineCallbacks
    def test_get_json(self):
        """
        When the get_json method is called, a GET request should be made and
        the response should be deserialized from JSON.
        """
        d = self.client.get_json('/hello')

        request = yield self.requests.get()
        self.assertEqual(request.method, b'GET')
        self.assertEqual(request.uri, self.uri('/hello', encode=True))

        request.setResponseCode(200)
        request.write(self.json_dumpb({'test': 'hello'}))
        request.finish()

        res = yield d
        self.assertEqual(res, {'test': 'hello'})

    @inlineCallbacks
    def test_client_error_response(self):
        """
        When a request is made and a 4xx response code is returned, a HTTPError
        should be raised to indicate a client error.
        """
        d = self.client.request('GET', '/hello')

        request = yield self.requests.get()
        self.assertEqual(request.method, b'GET')
        self.assertEqual(request.uri, self.uri('/hello', encode=True))

        request.setResponseCode(403)
        request.write(b'Unauthorized\n')
        request.finish()

        yield wait0()
        failure = self.failureResultOf(d, HTTPError)
        self.assertEqual(
            failure.getErrorMessage(),
            '403 Client Error for url: %s' % self.uri('/hello'))

    @inlineCallbacks
    def test_server_error_response(self):
        """
        When a request is made and a 5xx response code is returned, a HTTPError
        should be raised to indicate a server error.
        """
        d = self.client.request('GET', '/hello')

        request = yield self.requests.get()
        self.assertEqual(request.method, b'GET')
        self.assertEqual(request.uri, self.uri('/hello', encode=True))

        request.setResponseCode(502)
        request.write(b'Bad gateway\n')
        request.finish()

        yield wait0()
        failure = self.failureResultOf(d, HTTPError)
        self.assertEqual(
            failure.getErrorMessage(),
            '502 Server Error for url: %s' % self.uri('/hello'))


class MarathonClientTest(JsonClientTestBase):
    def get_client(self):
        return MarathonClient('http://localhost:8080')

    @inlineCallbacks
    def test_get_json_field(self):
        """
        When get_json_field is used to make a request, the response is
        deserialized from JSON and the value of the specified field is
        returned.
        """
        d = self.client.get_json_field('/my-path', 'field-key')

        request = yield self.requests.get()
        self.assertEqual(request.method, b'GET')
        self.assertEqual(request.uri, self.uri('/my-path', encode=True))

        self.write_json_response(request, {
            'field-key': 'field-value',
            'other-field-key': 'do-not-care'
        })

        res = yield d
        self.assertEqual(res, 'field-value')

    @inlineCallbacks
    def test_get_json_field_missing(self):
        """
        When get_json_field is used to make a request, the response is
        deserialized from JSON and if the specified field is missing, an error
        is raised.
        """
        d = self.client.get_json_field('/my-path', 'field-key')

        request = yield self.requests.get()
        self.assertEqual(request.method, b'GET')
        self.assertEqual(request.uri, self.uri('/my-path', encode=True))

        self.write_json_response(request, {'other-field-key': 'do-not-care'})

        yield wait0()
        failure = self.failureResultOf(d, KeyError)
        self.assertEqual(
            failure.getErrorMessage(),
            '\'Unable to get value for "field-key" from Marathon response: '
            '"{"other-field-key": "do-not-care"}"\'')

    @inlineCallbacks
    def test_get_event_subscription(self):
        """
        When we request event subscriptions from Marathon, we should receive a
        list of callback URLs.
        """
        d = self.client.get_event_subscriptions()

        request = yield self.requests.get()
        self.assertEqual(request.method, b'GET')
        self.assertEqual(request.uri,
                         self.uri('/v2/eventSubscriptions', encode=True))

        self.write_json_response(request, {
            'callbackUrls': [
                'http://localhost:7000/events?registration=localhost'
            ]
        })

        res = yield d
        self.assertEqual(res, [
            'http://localhost:7000/events?registration=localhost'
        ])

    @inlineCallbacks
    def test_post_event_subscription(self):
        """
        When we post an event subscription with a callback URL, we should
        return True for a 200/OK response from Marathon.
        """
        d = self.client.post_event_subscription(
            'http://localhost:7000/events?registration=localhost')

        request = yield self.requests.get()
        self.assertEqual(request.method, b'POST')
        self.assertEqual(request.path,
                         self.uri('/v2/eventSubscriptions', encode=True))
        self.assertEqual(request.args, {
            b'callbackUrl': [
                b'http://localhost:7000/events?registration=localhost'
            ]
        })

        self.write_json_response(request, {
            # TODO: Add check that callbackUrl is correct
            'callbackUrl':
                'http://localhost:7000/events?registration=localhost',
            'clientIp': '0:0:0:0:0:0:0:1',
            'eventType': 'subscribe_event'
        })

        res = yield d
        self.assertEqual(res, True)

    @inlineCallbacks
    def test_post_event_subscription_not_ok(self):
        """
        When we post an event subscription with a callback URL, we should
        return False for a non-200/OK response from Marathon.
        """
        d = self.client.post_event_subscription(
            'http://localhost:7000/events?registration=localhost')

        request = yield self.requests.get()
        self.assertEqual(request.method, b'POST')
        self.assertEqual(request.path,
                         self.uri('/v2/eventSubscriptions', encode=True))
        self.assertEqual(request.args, {
            b'callbackUrl': [
                b'http://localhost:7000/events?registration=localhost'
            ]
        })

        self.write_json_response(request, {}, response_code=201)

        res = yield d
        self.assertEqual(res, False)

    @inlineCallbacks
    def test_get_apps(self):
        """
        When we request the list of apps from Marathon, we should receive the
        list of apps with some information.
        """
        d = self.client.get_apps()

        request = yield self.requests.get()
        self.assertEqual(request.method, b'GET')
        self.assertEqual(request.uri, self.uri('/v2/apps', encode=True))

        apps = {
            'apps': [
                {
                    'id': '/product/us-east/service/myapp',
                    'cmd': 'env && sleep 60',
                    'constraints': [
                        [
                            'hostname',
                            'UNIQUE',
                            ''
                        ]
                    ],
                    'container': None,
                    'cpus': 0.1,
                    'env': {
                        'LD_LIBRARY_PATH': '/usr/local/lib/myLib'
                    },
                    'executor': '',
                    'instances': 3,
                    'mem': 5.0,
                    'ports': [
                        15092,
                        14566
                    ],
                    'tasksRunning': 0,
                    'tasksStaged': 1,
                    'uris': [
                        'https://raw.github.com/mesosphere/marathon/master/'
                        'README.md'
                    ],
                    'version': '2014-03-01T23:42:20.938Z'
                }
            ]
        }
        self.write_json_response(request, apps)

        res = yield d
        self.assertEqual(res, apps['apps'])

    @inlineCallbacks
    def test_get_app(self):
        """
        When we request information on a specific app from Marathon, we should
        receive information on that app.
        """
        d = self.client.get_app('/my-app')

        request = yield self.requests.get()
        self.assertEqual(request.method, b'GET')
        self.assertEqual(request.uri, self.uri('/v2/apps/my-app', encode=True))

        app = {
            'app': {
                'args': None,
                'backoffFactor': 1.15,
                'backoffSeconds': 1,
                'maxLaunchDelaySeconds': 3600,
                'cmd': 'python toggle.py $PORT0',
                'constraints': [],
                'container': None,
                'cpus': 0.2,
                'dependencies': [],
                'deployments': [
                    {
                        'id': '44c4ed48-ee53-4e0f-82dc-4df8b2a69057'
                    }
                ],
                'disk': 0.0,
                'env': {},
                'executor': '',
                'healthChecks': [
                    {
                        'command': None,
                        'gracePeriodSeconds': 5,
                        'intervalSeconds': 10,
                        'maxConsecutiveFailures': 3,
                        'path': '/health',
                        'portIndex': 0,
                        'protocol': 'HTTP',
                        'timeoutSeconds': 10
                    },
                    {
                        'command': None,
                        'gracePeriodSeconds': 5,
                        'intervalSeconds': 10,
                        'maxConsecutiveFailures': 6,
                        'path': '/machinehealth',
                        'overridePort': 3333,
                        'protocol': 'HTTP',
                        'timeoutSeconds': 10
                    }
                ],
                'id': '/my-app',
                'instances': 2,
                'mem': 32.0,
                'ports': [
                    10000
                ],
                'requirePorts': False,
                'storeUrls': [],
                'upgradeStrategy': {
                    'minimumHealthCapacity': 1.0
                },
                'uris': [
                    'http://downloads.mesosphere.com/misc/toggle.tgz'
                ],
                'user': None,
                'version': '2014-09-12T23:28:21.737Z',
                'versionInfo': {
                    'lastConfigChangeAt': '2014-09-11T02:26:01.135Z',
                    'lastScalingAt': '2014-09-12T23:28:21.737Z'
                }
            }
        }
        self.write_json_response(request, app)

        res = yield d
        self.assertEqual(res, app['app'])

    @inlineCallbacks
    def test_get_app_tasks(self):
        """
        When we request the list of tasks for an app from Marathon, we should
        receive a list of app tasks.
        """
        d = self.client.get_app_tasks('/my-app')

        request = yield self.requests.get()
        self.assertEqual(request.method, b'GET')
        self.assertEqual(request.uri,
                         self.uri('/v2/apps/my-app/tasks', encode=True))

        tasks = {
            'tasks': [
                {
                    'host': 'agouti.local',
                    'id': 'my-app_1-1396592790353',
                    'ports': [
                        31336,
                        31337
                    ],
                    'stagedAt': '2014-04-04T06:26:30.355Z',
                    'startedAt': '2014-04-04T06:26:30.860Z',
                    'version': '2014-04-04T06:26:23.051Z'
                },
                {
                    'host': 'agouti.local',
                    'id': 'my-app_0-1396592784349',
                    'ports': [
                        31382,
                        31383
                    ],
                    'stagedAt': '2014-04-04T06:26:24.351Z',
                    'startedAt': '2014-04-04T06:26:24.919Z',
                    'version': '2014-04-04T06:26:23.051Z'
                }
            ]
        }
        self.write_json_response(request, tasks)

        res = yield d
        self.assertEqual(res, tasks['tasks'])


class ConsulClientTest(JsonClientTestBase):
    def get_client(self):
        return ConsulClient('http://localhost:8500')

    @inlineCallbacks
    def test_register_agent_service(self):
        """
        When a service is registered with an agent, the registration JSON is
        PUT to the correct address.
        """
        registration = {
            'ID': 'redis1',
            'Name': 'redis',
            'Tags': [
                'master',
                'v1'
            ],
            'Address': '127.0.0.1',
            'Port': 8000,
            'Check': {
                'Script': '/usr/local/bin/check_redis.py',
                'HTTP': 'http://localhost:5000/health',
                'Interval': '10s',
                'TTL': '15s'
            }
        }
        d = self.client.register_agent_service('foo.example.com', registration)

        request = yield self.requests.get()
        self.assertEqual(request.method, b'PUT')
        self.assertEqual(
            request.uri,
            b'http://foo.example.com:8500/v1/agent/service/register')
        self.assertEqual(self.read_json_response(request), registration)

        request.setResponseCode(200)
        request.finish()

        yield d

    @inlineCallbacks
    def test_register_agent_service_fallback(self):
        """
        When a service is registered with an agent but the registration request
        fails, the registration should fall back to the local Consul agent.
        """
        self.client.enable_fallback = True
        # First try and do a regular registration
        registration = {
            'ID': 'redis1',
            'Name': 'redis',
            'Tags': [
                'master',
                'v1'
            ],
            'Address': '127.0.0.1',
            'Port': 8000,
            'Check': {
                'Script': '/usr/local/bin/check_redis.py',
                'HTTP': 'http://localhost:5000/health',
                'Interval': '10s',
                'TTL': '15s'
            }
        }
        d = self.client.register_agent_service('foo.example.com', registration)

        request = yield self.requests.get()
        # Fail the request
        request.setResponseCode(503)
        request.write(b'Service unavailable\n')
        request.finish()

        # Expect the request to fallback to the regular endpoint
        request = yield self.requests.get()
        self.assertEqual(request.method, b'PUT')
        self.assertEqual(request.uri,
                         self.uri('/v1/agent/service/register', encode=True))
        self.assertEqual(self.read_json_response(request), registration)

        request.setResponseCode(200)
        request.finish()

        yield d

    @inlineCallbacks
    def test_deregister_agent_service(self):
        """
        When a service is deregistered, a PUT request is made to the correct
        address.
        """
        d = self.client.deregister_agent_service('foo.example.com', 'redis1')

        request = yield self.requests.get()
        self.assertEqual(request.method, b'PUT')
        self.assertEqual(
            request.uri,
            b'http://foo.example.com:8500/v1/agent/service/deregister/redis1')

        request.setResponseCode(200)
        request.finish()

        yield d

    @inlineCallbacks
    def test_put_kv(self):
        """
        When a value is put in the key/value store, a PUT request is made to
        the correct address with the JSON data in the payload.
        """
        d = self.client.put_kv('foo', {'bar': 'baz'})

        request = yield self.requests.get()
        self.assertEqual(request.method, b'PUT')
        self.assertEqual(request.uri, self.uri('/v1/kv/foo', encode=True))
        self.assertEqual(self.read_json_response(request), {'bar': 'baz'})

        request.setResponseCode(200)
        request.write(b'true')
        request.finish()

        res = yield d
        json_res = yield res.json()
        self.assertEqual(json_res, True)

    # TODO: Consul returns False. What should we do?

    @inlineCallbacks
    def test_get_kv_keys(self):
        """
        When we get keys from the key/value store, a request is made to the
        correct address and a list of keys is returned.
        """
        d = self.client.get_kv_keys('foo')

        request = yield self.requests.get()
        self.assertEqual(request.method, b'GET')
        self.assertEqual(request.path, self.uri('/v1/kv/foo', encode=True))
        self.assertEqual(self.parse_query(request.uri), {
            'keys': [None]
        })

        keys = [
            '/foo/bar',
            '/foo/baz/boo'
        ]
        request.setResponseCode(200)
        request.write(self.json_dumpb(keys))
        request.finish()

        res = yield d
        self.assertEqual(res, keys)

    @inlineCallbacks
    def test_get_kv_keys_separator(self):
        """
        When we get keys from the key/value store and the "separator" parameter
        is specified, a request is made to the correct address, the separator
        is passed as a query parameter, and a list of keys is returned.
        """
        d = self.client.get_kv_keys('foo', separator='/')

        request = yield self.requests.get()
        self.assertEqual(request.method, b'GET')
        self.assertEqual(request.path, self.uri('/v1/kv/foo', encode=True))
        self.assertEqual(self.parse_query(request.uri), {
            'keys': [None],
            'separator': ['/']
        })

        keys = [
            '/foo/bar',
            '/foo/baz/'
        ]
        request.setResponseCode(200)
        request.write(self.json_dumpb(keys))
        request.finish()

        res = yield d
        self.assertEqual(res, keys)

    @inlineCallbacks
    def test_delete_kv_keys(self):
        """
        When we delete keys from the key/value store, a request is made to the
        correct address.
        """
        d = self.client.delete_kv_keys('foo')

        request = yield self.requests.get()
        self.assertEqual(request.method, b'DELETE')
        self.assertEqual(request.uri, self.uri('/v1/kv/foo', encode=True))

        request.setResponseCode(200)
        request.finish()

        yield d

    @inlineCallbacks
    def test_delete_kv_keys_recursive(self):
        """
        When we delete keys from the key/value store recursively, a request is
        made to the correct address with the "recurse" query parameter set.
        """
        d = self.client.delete_kv_keys('foo', recurse=True)

        request = yield self.requests.get()
        self.assertEqual(request.method, b'DELETE')
        self.assertEqual(request.path, self.uri('/v1/kv/foo', encode=True))
        self.assertEqual(self.parse_query(request.uri), {
            'recurse': [None]
        })

        request.setResponseCode(200)
        request.finish()

        yield d

    @inlineCallbacks
    def test_get_catalog_nodes(self):
        """
        When we get the list of nodes from the catalog, a request is made to
        the correct address and a list of nodes is returned.
        """
        d = self.client.get_catalog_nodes()

        request = yield self.requests.get()
        self.assertEqual(request.method, b'GET')
        self.assertEqual(request.uri,
                         self.uri('/v1/catalog/nodes', encode=True))

        nodes = [
            {
                'Node': 'baz',
                'Address': '10.1.10.11'
            },
            {
                'Node': 'foobar',
                'Address': '10.1.10.12'
            }
        ]
        request.setResponseCode(200)
        request.write(self.json_dumpb(nodes))
        request.finish()

        res = yield d
        self.assertEqual(res, nodes)

    @inlineCallbacks
    def test_get_agent_services(self):
        """
        When we get the list of services from an agent, a request is made to
        the correct address and a list of services is returned.
        """
        d = self.client.get_agent_services('foo.example.com')

        request = yield self.requests.get()
        self.assertEqual(request.method, b'GET')
        self.assertEqual(request.uri,
                         b'http://foo.example.com:8500/v1/agent/services')

        services = {
            'redis': {
                'ID': 'redis',
                'Service': 'redis',
                'Tags': None,
                'Address': 'http://foo.example.com',
                'Port': 8000
            }
        }
        request.setResponseCode(200)
        request.write(self.json_dumpb(services))
        request.finish()

        res = yield d
        self.assertEqual(res, services)
