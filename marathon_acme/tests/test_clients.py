import json

import testtools

from twisted.internet import reactor
from twisted.internet.task import Clock
from twisted.internet.defer import inlineCallbacks, DeferredQueue
from twisted.web.client import Agent
from twisted.web.http_headers import Headers
from twisted.web.server import NOT_DONE_YET

from testtools.matchers import Equals, Is, IsInstance
from testtools.twistedsupport import failed

from txfake import FakeHttpServer
from txfake.fake_connection import wait0

from marathon_acme.clients import (
    default_agent, default_reactor, get_single_header, HTTPError, json_content,
    JsonClient, MarathonClient, raise_for_status)
from marathon_acme.server import write_request_json
from marathon_acme.tests.helpers import TestCase
from marathon_acme.tests.matchers import (
    HasHeader, HasRequestProperties, WithErrorTypeAndMessage)


def read_request_json(request):
    return json.loads(request.content.read().decode('utf-8'))


def json_response(request, json_data, response_code=200):
    """ Set the response code, write encoded JSON, and finish() a request. """
    request.setResponseCode(response_code)
    write_request_json(request, json_data)
    request.finish()


class TestGetSingleHeader(testtools.TestCase):
    def test_single_value(self):
        """
        When a single value is set for a header key and we use
        get_single_header to get that value, the correct value is returned.
        """
        headers = Headers({'Content-Type': ['application/json']})
        content_type = get_single_header(headers, 'Content-Type')

        self.assertThat(content_type, Equals('application/json'))

    def test_multiple_values(self):
        """
        When multiple values are set for a header key and we use
        get_single_header to get the value, the last value is returned.
        """
        headers = Headers({'Content-Type': [
            'application/json',
            'text/event-stream',
            'text/html'
        ]})
        content_type = get_single_header(headers, 'Content-Type')

        self.assertThat(content_type, Equals('text/html'))

    def test_value_with_params(self):
        """
        When the value set for a header key include parameters and we use
        get_single_header to get the value, the value without the parameters
        is returned.
        """
        headers = Headers({'Accept': ['application/json; charset=utf-8']})
        accept = get_single_header(headers, 'Accept')

        self.assertThat(accept, Equals('application/json'))

    def test_value_missing(self):
        """
        When the requested header key is not present in the set of headers,
        get_single_header returns None.
        """
        headers = Headers({'Content-Type': ['application/json']})
        content_type = get_single_header(headers, 'Accept')

        self.assertThat(content_type, Is(None))


class TestDefaultReactor(testtools.TestCase):
    def test_default_reactor(self):
        """
        When default_reactor is passed a reactor it should return that reactor.
        """
        clock = Clock()

        self.assertThat(default_reactor(clock), Is(clock))

    def test_default_reactor_not_provided(self):
        """
        When default_reactor is not passed a reactor, it should return the
        default reactor.
        """
        self.assertThat(default_reactor(None), Is(reactor))


class TestDefaultAgent(testtools.TestCase):
    def test_default_agent(self):
        """
        When default_agent is passed an agent it should return that agent.
        """
        agent = Agent(reactor)

        self.assertThat(default_agent(agent, reactor), Is(agent))

    def test_default_agent_not_provided(self):
        """
        When default_agent is not passed an agent, it should return a default
        agent.
        """
        self.assertThat(default_agent(None, reactor), IsInstance(Agent))


class TestJsonClientBase(TestCase):
    def setUp(self):
        super(TestJsonClientBase, self).setUp()

        self.requests = DeferredQueue()
        fake_server = FakeHttpServer(self.handle_request)

        self.client = self.get_client(fake_server.get_agent())

        # Spin the reactor once at the end of each test to clean up any
        # cancelled deferreds
        self.addCleanup(wait0)

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


class TestJsonClient(TestJsonClientBase):

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

    @inlineCallbacks
    def test_json_content(self):
        """
        When a request is made with the json_content callback and the
        'application/json' content type is set in the response headers then the
        JSON should be successfully parsed.
        """
        d = self.cleanup_d(self.client.request('GET', path='/hello'))
        d.addCallback(json_content)

        request = yield self.requests.get()
        self.assertThat(request, HasRequestProperties(
            method='GET', url=self.uri('/hello')))
        self.assertThat(request.requestHeaders,
                        HasHeader('accept', ['application/json']))

        request.setResponseCode(200)
        request.setHeader('Content-Type', 'application/json')
        request.write(json.dumps({}).encode('utf-8'))
        request.finish()

        response = yield d
        self.assertThat(response, Equals({}))

    @inlineCallbacks
    def test_json_content_incorrect_content_type(self):
        """
        When a request is made with the json_content callback and the
        content-type header is set to a value other than 'application/json' in
        the response headers then an error should be raised.
        """
        d = self.cleanup_d(self.client.request('GET', path='/hello'))
        d.addCallback(json_content)

        request = yield self.requests.get()
        self.assertThat(request, HasRequestProperties(
            method='GET', url=self.uri('/hello')))
        self.assertThat(request.requestHeaders,
                        HasHeader('accept', ['application/json']))

        request.setResponseCode(200)
        request.setHeader('Content-Type', 'application/octet-stream')
        request.write(json.dumps({}).encode('utf-8'))
        request.finish()

        yield wait0()
        self.assertThat(d, failed(WithErrorTypeAndMessage(
            HTTPError,
            'Expected header "Content-Type" to be "application/json" but '
            'found "application/octet-stream" instead')))

    @inlineCallbacks
    def test_json_content_missing_content_type(self):
        """
        When a request is made with the json_content callback and the
        content-type header is not set in the response headers then an error
        should be raised.
        """
        d = self.cleanup_d(self.client.request('GET', path='/hello'))
        d.addCallback(json_content)

        request = yield self.requests.get()
        self.assertThat(request, HasRequestProperties(
            method='GET', url=self.uri('/hello')))
        self.assertThat(request.requestHeaders,
                        HasHeader('accept', ['application/json']))

        request.setResponseCode(200)
        # Twisted will set the content type to "text/html" by default but this
        # can be disabled by setting the default content type to None:
        # https://twistedmatrix.com/documents/current/api/twisted.web.server.Request.html#defaultContentType
        request.defaultContentType = None
        request.write(json.dumps({}).encode('utf-8'))
        request.finish()

        yield wait0()
        self.assertThat(d, failed(WithErrorTypeAndMessage(
            HTTPError, 'Expected header "Content-Type" to be '
                       '"application/json" but header not found in response')))


class TestMarathonClient(TestJsonClientBase):
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

    @inlineCallbacks
    def test_get_events(self):
        """
        When a request is made to Marathon's event stream, a callback should
        receive JSON-decoded data before the connection is closed.
        """
        data = []
        d = self.cleanup_d(self.client.get_events({'test': data.append}))

        request = yield self.requests.get()
        self.assertThat(request, HasRequestProperties(
            method='GET', url=self.uri('/v2/events')))
        self.assertThat(request.requestHeaders,
                        HasHeader('accept', ['text/event-stream']))

        request.setResponseCode(200)
        request.setHeader('Content-Type', 'text/event-stream')

        json_data = {'hello': 'world'}
        request.write(b'event: test\n')
        request.write(b'data: %s\n' % (json.dumps(json_data).encode('utf-8'),))
        request.write(b'\n')

        yield wait0()
        self.assertThat(data, Equals([json_data]))

        request.finish()
        yield d

    @inlineCallbacks
    def test_get_events_multiple_events(self):
        """
        When a request is made to Marathon's event stream, and there are
        multiple events for a single callback, that callback should receive
        JSON-decoded data for each event.
        """
        data = []
        d = self.cleanup_d(self.client.get_events({'test': data.append}))

        request = yield self.requests.get()
        self.assertThat(request, HasRequestProperties(
            method='GET', url=self.uri('/v2/events')))
        self.assertThat(request.requestHeaders,
                        HasHeader('accept', ['text/event-stream']))

        request.setResponseCode(200)
        request.setHeader('Content-Type', 'text/event-stream')

        json_data1 = {'hello': 'world'}
        request.write(b'event: test\n')
        request.write(b'data: %s\n' % (json.dumps(json_data1).encode('utf-8')))
        request.write(b'\n')

        json_data2 = {'hi': 'planet'}
        request.write(b'data: %s\n' % (json.dumps(json_data2).encode('utf-8')))
        request.write(b'event: test\n')
        request.write(b'\n')

        yield wait0()
        self.assertThat(data, Equals([json_data1, json_data2]))

        request.finish()
        yield d

    @inlineCallbacks
    def test_get_events_multiple_callbacks(self):
        """
        When a request is made to Marathon's event stream, and there are
        events for multiple callbacks, those callbacks should receive
        JSON-decoded data for each event.
        """
        data1 = []
        data2 = []
        d = self.cleanup_d(self.client.get_events({
            'test1': data1.append,
            'test2': data2.append
        }))

        request = yield self.requests.get()
        self.assertThat(request, HasRequestProperties(
            method='GET', url=self.uri('/v2/events')))
        self.assertThat(request.requestHeaders,
                        HasHeader('accept', ['text/event-stream']))

        request.setResponseCode(200)
        request.setHeader('Content-Type', 'text/event-stream')

        json_data1 = {'hello': 'world'}
        request.write(b'event: test1\n')
        request.write(b'data: %s\n' % (json.dumps(json_data1).encode('utf-8')))
        request.write(b'\n')

        json_data2 = {'hello': 'computer'}
        request.write(b'event: test2\n')
        request.write(b'data: %s\n' % (json.dumps(json_data2).encode('utf-8')))
        request.write(b'\n')

        yield wait0()
        self.assertThat(data1, Equals([json_data1]))
        self.assertThat(data2, Equals([json_data2]))

        request.finish()
        yield d

    @inlineCallbacks
    def test_get_events_non_200(self):
        """
        When a request is made to Marathon's event stream, and a non-200
        response code is returned, an error should be raised.
        """
        data = []
        d = self.cleanup_d(self.client.get_events({'test': data.append}))

        request = yield self.requests.get()
        self.assertThat(request, HasRequestProperties(
            method='GET', url=self.uri('/v2/events')))
        self.assertThat(request.requestHeaders,
                        HasHeader('accept', ['text/event-stream']))

        request.setResponseCode(202)
        request.setHeader('Content-Type', 'text/event-stream')

        json_data = {'hello': 'world'}
        request.write(b'event: test\n')
        request.write(b'data: %s\n' % (json.dumps(json_data).encode('utf-8'),))
        request.write(b'\n')

        yield wait0()
        self.assertThat(d, failed(WithErrorTypeAndMessage(
            HTTPError, 'Non-200 response code (202) for url: '
                       'http://localhost:8080/v2/events')))

        self.assertThat(data, Equals([]))

        request.finish()
        yield d

    @inlineCallbacks
    def test_get_events_incorrect_content_type(self):
        """
        When a request is made to Marathon's event stream, and the content-type
        header value returned is not "text/event-stream", an error should be
        raised.
        """
        data = []
        d = self.cleanup_d(self.client.get_events({'test': data.append}))

        request = yield self.requests.get()
        self.assertThat(request, HasRequestProperties(
            method='GET', url=self.uri('/v2/events')))
        self.assertThat(request.requestHeaders,
                        HasHeader('accept', ['text/event-stream']))

        request.setResponseCode(200)
        request.setHeader('Content-Type', 'application/json')

        json_data = {'hello': 'world'}
        request.write(b'event: test\n')
        request.write(b'data: %s\n' % (json.dumps(json_data).encode('utf-8'),))
        request.write(b'\n')

        yield wait0()
        self.assertThat(d, failed(WithErrorTypeAndMessage(
            HTTPError,
            'Expected header "Content-Type" to be "text/event-stream" but '
            'found "application/json" instead')))

        self.assertThat(data, Equals([]))

        request.finish()
        yield d
