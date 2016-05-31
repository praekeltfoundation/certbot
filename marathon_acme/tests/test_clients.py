from twisted.internet.defer import inlineCallbacks, DeferredQueue
from twisted.web.server import NOT_DONE_YET

from testtools.matchers import Equals
from testtools.twistedsupport import failed

from txfake import FakeHttpServer
from txfake.fake_connection import wait0

from marathon_acme.clients import (
    HTTPError, JsonClient, MarathonClient, raise_for_status)
from marathon_acme.server import read_request_json, write_request_json
from marathon_acme.tests.helpers import TestCase
from marathon_acme.tests.matchers import (
    HasHeader, HasRequestProperties, WithErrorTypeAndMessage)


def json_response(request, json_data, response_code=200):
    """ Set the response code, write encoded JSON, and finish() a request. """
    request.setResponseCode(response_code)
    write_request_json(request, json_data)
    request.finish()


class JsonClientTestBase(TestCase):
    def setUp(self):
        super(JsonClientTestBase, self).setUp()

        self.requests = DeferredQueue()
        fake_server = FakeHttpServer(self.handle_request)

        self.client = self.get_client(fake_server.get_agent())

    def handle_request(self, request):
        self.requests.put(request)
        return NOT_DONE_YET

    def get_client(self, agent):
        """To be implemented by subclass"""
        raise NotImplementedError()

    def uri(self, path):
        return '%s%s' % (self.client.url, path,)

    def cleanup_d(self, d):
        self.addCleanup(lambda: d)
        return d


class JsonClientTest(JsonClientTestBase):

    def get_client(self, agent):
        return JsonClient('http://localhost:8000', agent=agent)

    @inlineCallbacks
    def test_request(self):
        """
        When a request is made, it should be made with the correct method,
        address and headers, and should contain an empty body. The response
        should be returned.
        """
        d = self.cleanup_d(self.client.request('GET', path='/hello'))

        request = yield self.requests.get()
        self.assertThat(request, HasRequestProperties(
            method='GET', url=self.uri('/hello')))
        self.assertThat(request.requestHeaders,
                        HasHeader('accept', ['application/json']))
        self.assertThat(request.content.read(), Equals(b''))

        request.setResponseCode(200)
        request.write(b'hi\n')
        request.finish()

        response = yield d
        text = yield response.text()
        self.assertThat(text, Equals('hi\n'))

    @inlineCallbacks
    def test_request_json_data(self):
        """
        When a request is made with the json_data parameter set, that data
        should be sent as JSON and the content-type header should be set to
        indicate this.
        """
        self.cleanup_d(self.client.request(
            'GET', path='/hello', json_data={'test': 'hello'}))

        request = yield self.requests.get()
        self.assertThat(request, HasRequestProperties(
            method='GET', url=self.uri('/hello')))
        self.assertThat(request.requestHeaders, HasHeader(
            'content-type', ['application/json']))
        self.assertThat(request.requestHeaders,
                        HasHeader('accept', ['application/json']))
        self.assertThat(read_request_json(request), Equals({'test': 'hello'}))

        request.setResponseCode(200)
        request.finish()

    @inlineCallbacks
    def test_request_url(self):
        """
        When a request is made with the url parameter set, that parameter
        should be used as the base URL.
        """
        self.cleanup_d(self.client.request(
            'GET', path='/hello', url='http://localhost:9000'))

        request = yield self.requests.get()
        self.assertThat(request, HasRequestProperties(
            method='GET', url='http://localhost:9000/hello'))

        request.setResponseCode(200)
        request.finish()

    @inlineCallbacks
    def test_get_json(self):
        """
        When the get_json method is called, a GET request should be made and
        the response should be deserialized from JSON.
        """
        d = self.cleanup_d(self.client.get_json(path='/hello'))

        request = yield self.requests.get()
        self.assertThat(request, HasRequestProperties(
            method='GET', url=self.uri('/hello')))

        json_response(request, {'test': 'hello'})

        res = yield d
        self.assertThat(res, Equals({'test': 'hello'}))

    @inlineCallbacks
    def test_client_error_response(self):
        """
        When a request is made and the raise_for_status callback is added and a
        4xx response code is returned, a HTTPError should be raised to indicate
        a client error.
        """
        d = self.cleanup_d(self.client.request('GET', path='/hello'))
        d.addCallback(raise_for_status)

        request = yield self.requests.get()
        self.assertThat(request, HasRequestProperties(
            method='GET', url=self.uri('/hello')))

        request.setResponseCode(403)
        request.write(b'Unauthorized\n')
        request.finish()

        yield wait0()
        self.assertThat(d, failed(WithErrorTypeAndMessage(
            HTTPError, '403 Client Error for url: %s' % self.uri('/hello'))))

    @inlineCallbacks
    def test_server_error_response(self):
        """
        When a request is made and the raise_for_status callback is added and a
        5xx response code is returned, a HTTPError should be raised to indicate
        a server error.
        """
        d = self.cleanup_d(self.client.request('GET', path='/hello'))
        d.addCallback(raise_for_status)

        request = yield self.requests.get()
        self.assertThat(request, HasRequestProperties(
            method='GET', url=self.uri('/hello')))

        request.setResponseCode(502)
        request.write(b'Bad gateway\n')
        request.finish()

        yield wait0()
        self.assertThat(d, failed(WithErrorTypeAndMessage(
            HTTPError, '502 Server Error for url: %s' % self.uri('/hello'))))

    @inlineCallbacks
    def test_params(self):
        """
        When query parameters are specified as the params kwarg, those
        parameters are reflected in the request.
        """
        self.cleanup_d(self.client.request(
            'GET', path='/hello', params={'from': 'earth'}))

        request = yield self.requests.get()
        self.assertThat(request, HasRequestProperties(
            method='GET', url=self.uri('/hello'), query={'from': ['earth']}))

        request.setResponseCode(200)
        request.finish()

    @inlineCallbacks
    def test_url_query_as_params(self):
        """
        When query parameters are specified in the URL, those parameters are
        reflected in the request.
        """
        self.cleanup_d(self.client.request(
            'GET', self.uri('/hello?from=earth')))

        request = yield self.requests.get()
        self.assertThat(request, HasRequestProperties(
            method='GET', url=self.uri('/hello'), query={'from': ['earth']}))

        request.setResponseCode(200)
        request.finish()

    @inlineCallbacks
    def test_params_precedence_over_url_query(self):
        """
        When query parameters are specified as both the params kwarg and in the
        URL, the params kwarg takes precedence.
        """
        self.cleanup_d(self.client.request(
            'GET', self.uri('/hello?from=mars'), params={'from': 'earth'}))

        request = yield self.requests.get()
        self.assertThat(request, HasRequestProperties(
            method='GET', url=self.uri('/hello'), query={'from': ['earth']}))

        request.setResponseCode(200)
        request.finish()

    @inlineCallbacks
    def test_auth(self):
        """
        When basic auth credentials are specified as the auth kwarg, the
        encoded credentials are present in the request headers.
        """
        self.cleanup_d(self.client.request(
            'GET', path='/hello', auth=('user', 'pa$$word')))

        request = yield self.requests.get()
        self.assertThat(request, HasRequestProperties(
            method='GET', url=self.uri('/hello')))
        self.assertThat(
            request.requestHeaders,
            HasHeader('Authorization', ['Basic dXNlcjpwYSQkd29yZA==']))

        request.setResponseCode(200)
        request.finish()

    @inlineCallbacks
    def test_url_userinfo_as_auth(self):
        """
        When basic auth credentials are specified in the URL, the encoded
        credentials are present in the request headers.
        """
        self.cleanup_d(self.client.request(
            'GET', 'http://user:pa$$word@localhost:8000/hello'))

        request = yield self.requests.get()
        self.assertThat(request, HasRequestProperties(
            method='GET', url=self.uri('/hello')))
        self.assertThat(
            request.requestHeaders,
            HasHeader('Authorization', ['Basic dXNlcjpwYSQkd29yZA==']))

        request.setResponseCode(200)
        request.finish()

    @inlineCallbacks
    def test_auth_precedence_over_url_userinfo(self):
        """
        When basic auth credentials are specified as both the auth kwarg and in
        the URL, the credentials in the auth kwarg take precedence.
        """
        self.cleanup_d(self.client.request(
            'GET', 'http://usernator:password@localhost:8000/hello',
            auth=('user', 'pa$$word')))

        request = yield self.requests.get()
        self.assertThat(request, HasRequestProperties(
            method='GET', url=self.uri('/hello')))
        self.assertThat(
            request.requestHeaders,
            HasHeader('Authorization', ['Basic dXNlcjpwYSQkd29yZA==']))

        request.setResponseCode(200)
        request.finish()

    @inlineCallbacks
    def test_url_overrides(self):
        """
        When URL parts are overridden via keyword arguments, those overrides
        should be reflected in the request.
        """
        self.cleanup_d(self.client.request(
            'GET', 'http://example.com:8000/hello#section1',
            scheme='https', host='example2.com', port='9000', path='/goodbye',
            fragment='section2'))

        request = yield self.requests.get()
        self.assertThat(request, HasRequestProperties(
            method='GET', url='https://example2.com:9000/goodbye#section2'))

        request.setResponseCode(200)
        request.finish()


class MarathonClientTest(JsonClientTestBase):
    def get_client(self, agent):
        return MarathonClient('http://localhost:8080', agent=agent)

    @inlineCallbacks
    def test_get_json_field(self):
        """
        When get_json_field is used to make a request, the response is
        deserialized from JSON and the value of the specified field is
        returned.
        """
        d = self.cleanup_d(
            self.client.get_json_field('field-key', path='/my-path'))

        request = yield self.requests.get()
        self.assertThat(request, HasRequestProperties(
            method='GET', url=self.uri('/my-path')))

        json_response(request, {
            'field-key': 'field-value',
            'other-field-key': 'do-not-care'
        })

        res = yield d
        self.assertThat(res, Equals('field-value'))

    @inlineCallbacks
    def test_get_json_field_error(self):
        """
        When get_json_field is used to make a request but the response code
        indicates an error, an HTTPError should be raised.
        """
        d = self.cleanup_d(
            self.client.get_json_field('field-key', path='/my-path'))

        request = yield self.requests.get()
        self.assertThat(request, HasRequestProperties(
            method='GET', url=self.uri('/my-path')))

        request.setResponseCode(404)
        request.write(b'Not found\n')
        request.finish()

        yield wait0()
        self.assertThat(d, failed(WithErrorTypeAndMessage(
            HTTPError, '404 Client Error for url: %s' % self.uri('/my-path'))))

    @inlineCallbacks
    def test_get_json_field_missing(self):
        """
        When get_json_field is used to make a request, the response is
        deserialized from JSON and if the specified field is missing, an error
        is raised.
        """
        d = self.cleanup_d(
            self.client.get_json_field('field-key', path='/my-path'))

        request = yield self.requests.get()
        self.assertThat(request, HasRequestProperties(
            method='GET', url=self.uri('/my-path')))

        json_response(request, {'other-field-key': 'do-not-care'})

        yield wait0()
        self.assertThat(d, failed(WithErrorTypeAndMessage(
            KeyError,
            '\'Unable to get value for "field-key" from Marathon response: '
            '"{"other-field-key": "do-not-care"}"\''
        )))

    @inlineCallbacks
    def test_get_event_subscription(self):
        """
        When we request event subscriptions from Marathon, we should receive a
        list of callback URLs.
        """
        d = self.cleanup_d(self.client.get_event_subscriptions())

        request = yield self.requests.get()
        self.assertThat(request, HasRequestProperties(
            method='GET', url=self.uri('/v2/eventSubscriptions')))

        json_response(request, {
            'callbackUrls': [
                'http://localhost:7000/events?registration=localhost'
            ]
        })

        res = yield d
        self.assertThat(res, Equals([
            'http://localhost:7000/events?registration=localhost'
        ]))

    @inlineCallbacks
    def test_post_event_subscription(self):
        """
        When we post an event subscription with a callback URL, we should
        return True for a 200/OK response from Marathon.
        """
        d = self.cleanup_d(self.client.post_event_subscription(
            'http://localhost:7000/events?registration=localhost'))

        request = yield self.requests.get()
        self.assertThat(request, HasRequestProperties(
            method='POST',
            url=self.uri('/v2/eventSubscriptions'),
            query={
                'callbackUrl': [
                    'http://localhost:7000/events?registration=localhost'
                ]
            }
        ))

        json_response(request, {
            # TODO: Add check that callbackUrl is correct
            'callbackUrl':
                'http://localhost:7000/events?registration=localhost',
            'clientIp': '0:0:0:0:0:0:0:1',
            'eventType': 'subscribe_event'
        })

        res = yield d
        self.assertThat(res, Equals(True))

    @inlineCallbacks
    def test_post_event_subscription_not_ok(self):
        """
        When we post an event subscription with a callback URL, we should
        return False for a non-200/OK response from Marathon.
        """
        d = self.cleanup_d(self.client.post_event_subscription(
            'http://localhost:7000/events?registration=localhost'))

        request = yield self.requests.get()
        self.assertThat(request, HasRequestProperties(
            method='POST',
            url=self.uri('/v2/eventSubscriptions'),
            query={
                'callbackUrl': [
                    'http://localhost:7000/events?registration=localhost'
                ]
            }
        ))

        json_response(request, {}, response_code=201)

        res = yield d
        self.assertThat(res, Equals(False))

    @inlineCallbacks
    def test_delete_event_subscription(self):
        """
        When we delete an event subscription with a callback URL, we should
        return True for a 200/OK response from Marathon.
        """
        d = self.cleanup_d(self.client.delete_event_subscription(
            'http://localhost:7000/events?registration=localhost'))

        request = yield self.requests.get()
        self.assertThat(request, HasRequestProperties(
            method='DELETE',
            url=self.uri('/v2/eventSubscriptions'),
            query={
                'callbackUrl': [
                    'http://localhost:7000/events?registration=localhost'
                ]
            }
        ))

        json_response(request, {
            # TODO: Add check that callbackUrl is correct
            'callbackUrl':
                'http://localhost:7000/events?registration=localhost',
            'clientIp': '0:0:0:0:0:0:0:1',
            'eventType': 'subscribe_event'
        })

        res = yield d
        self.assertThat(res, Equals(True))

    @inlineCallbacks
    def test_delete_event_subscription_not_ok(self):
        """
        When we delete an event subscription with a callback URL, we should
        return False for a non-200/OK response from Marathon.
        """
        d = self.cleanup_d(self.client.delete_event_subscription(
            'http://localhost:7000/events?registration=localhost'))

        request = yield self.requests.get()
        self.assertThat(request, HasRequestProperties(
            method='DELETE',
            url=self.uri('/v2/eventSubscriptions'),
            query={
                'callbackUrl': [
                    'http://localhost:7000/events?registration=localhost'
                ]
            }
        ))

        json_response(request, {}, response_code=201)

        res = yield d
        self.assertThat(res, Equals(False))

    @inlineCallbacks
    def test_get_apps(self):
        """
        When we request the list of apps from Marathon, we should receive the
        list of apps with some information.
        """
        d = self.cleanup_d(self.client.get_apps())

        request = yield self.requests.get()
        self.assertThat(request, HasRequestProperties(
            method='GET', url=self.uri('/v2/apps')))

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
        json_response(request, apps)

        res = yield d
        self.assertThat(res, Equals(apps['apps']))

    @inlineCallbacks
    def test_get_app(self):
        """
        When we request information on a specific app from Marathon, we should
        receive information on that app.
        """
        d = self.cleanup_d(self.client.get_app('/my-app'))

        request = yield self.requests.get()
        self.assertThat(request, HasRequestProperties(
            method='GET', url=self.uri('/v2/apps/my-app')))

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
        json_response(request, app)

        res = yield d
        self.assertThat(res, Equals(app['app']))

    @inlineCallbacks
    def test_get_app_tasks(self):
        """
        When we request the list of tasks for an app from Marathon, we should
        receive a list of app tasks.
        """
        d = self.cleanup_d(self.client.get_app_tasks('/my-app'))

        request = yield self.requests.get()
        self.assertThat(request, HasRequestProperties(
            method='GET', url=self.uri('/v2/apps/my-app/tasks')))

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
        json_response(request, tasks)

        res = yield d
        self.assertThat(res, Equals(tasks['tasks']))
