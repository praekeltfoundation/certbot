import json

from testtools import ExpectedException, TestCase
from testtools.assertions import assert_that
from testtools.matchers import (
    Equals, Is, IsInstance, HasLength, MatchesStructure)
from testtools.twistedsupport import (
    AsynchronousDeferredRunTest, failed, flush_logged_errors)
from treq.client import HTTPClient as treq_HTTPClient
from twisted.internet import reactor
from twisted.internet.defer import inlineCallbacks, DeferredQueue
from twisted.internet.task import Clock
from twisted.web._newclient import ResponseDone
from twisted.web.client import Agent
from twisted.web.http_headers import Headers
from twisted.web.server import NOT_DONE_YET
from txfake import FakeHttpServer
from txfake.fake_connection import wait0

from marathon_acme.clients import (
    default_client, default_reactor, get_single_header, HTTPClient, HTTPError,
    JsonClient, MarathonClient, MarathonLbClient, raise_for_status)
from marathon_acme.server import write_request_json
from marathon_acme.tests.helpers import (
    failing_client, FailingAgent, PerLocationAgent)
from marathon_acme.tests.matchers import (
    HasHeader, HasRequestProperties, WithErrorTypeAndMessage)


def read_request_json(request):
    return json.loads(request.content.read().decode('utf-8'))


def json_response(request, json_data, response_code=200):
    """ Set the response code, write encoded JSON, and finish() a request. """
    request.setResponseCode(response_code)
    write_request_json(request, json_data)
    request.finish()


class TestGetSingleHeader(object):
    def test_single_value(self):
        """
        When a single value is set for a header key and we use
        get_single_header to get that value, the correct value is returned.
        """
        headers = Headers({'Content-Type': ['application/json']})
        content_type = get_single_header(headers, 'Content-Type')

        assert_that(content_type, Equals('application/json'))

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

        assert_that(content_type, Equals('text/html'))

    def test_value_with_params(self):
        """
        When the value set for a header key include parameters and we use
        get_single_header to get the value, the value without the parameters
        is returned.
        """
        headers = Headers({'Accept': ['application/json; charset=utf-8']})
        accept = get_single_header(headers, 'Accept')

        assert_that(accept, Equals('application/json'))

    def test_value_missing(self):
        """
        When the requested header key is not present in the set of headers,
        get_single_header returns None.
        """
        headers = Headers({'Content-Type': ['application/json']})
        content_type = get_single_header(headers, 'Accept')

        assert_that(content_type, Is(None))


class TestDefaultReactor(object):
    def test_default_reactor(self):
        """
        When default_reactor is passed a reactor it should return that reactor.
        """
        clock = Clock()

        assert_that(default_reactor(clock), Is(clock))

    def test_default_reactor_not_provided(self):
        """
        When default_reactor is not passed a reactor, it should return the
        default reactor.
        """
        assert_that(default_reactor(None), Is(reactor))


class TestDefaultClient(object):
    def test_default_client(self):
        """
        When default_client is passed a client it should return that client.
        """
        client = treq_HTTPClient(Agent(reactor))

        assert_that(default_client(client, reactor), Is(client))

    def test_default_client_not_provided(self):
        """
        When default_agent is not passed an agent, it should return a default
        agent.
        """
        assert_that(default_client(None, reactor), IsInstance(treq_HTTPClient))


class TestHTTPClientBase(TestCase):
    # TODO: Run client tests synchronously with treq.testing tools (#38)
    run_tests_with = AsynchronousDeferredRunTest.make_factory(timeout=0.1)

    def setUp(self):
        super(TestHTTPClientBase, self).setUp()

        self.requests = DeferredQueue()
        self.fake_server = FakeHttpServer(self.handle_request)

        fake_client = treq_HTTPClient(self.fake_server.get_agent())
        self.client = self.get_client(fake_client)

        # Spin the reactor once at the end of each test to clean up any
        # cancelled deferreds
        self.addCleanup(wait0)

    def handle_request(self, request):
        self.requests.put(request)
        return NOT_DONE_YET

    def get_client(self, client):
        """To be implemented by subclass"""
        raise NotImplementedError()

    def uri(self, path):
        return '%s%s' % (self.client.url, path,)

    def cleanup_d(self, d):
        self.addCleanup(lambda: d)
        return d


class TestHTTPClient(TestHTTPClientBase):
    def get_client(self, client):
        return HTTPClient('http://localhost:8000', client=client)

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
        self.assertThat(request.content.read(), Equals(b''))

        request.setResponseCode(200)
        request.write(b'hi\n')
        request.finish()

        response = yield d
        text = yield response.text()
        self.assertThat(text, Equals('hi\n'))

    @inlineCallbacks
    def test_request_debug_log(self):
        """
        When a request is made in debug mode, things should run smoothly.
        (Don't really want to check the log output here, just that things don't
        break.)
        """
        self.client.debug = True
        d = self.cleanup_d(self.client.request('GET', path='/hello'))

        request = yield self.requests.get()
        self.assertThat(request, HasRequestProperties(
            method='GET', url=self.uri('/hello')))
        self.assertThat(request.content.read(), Equals(b''))

        request.setResponseCode(200)
        request.write(b'hi\n')
        request.finish()

        response = yield d
        text = yield response.text()
        self.assertThat(text, Equals('hi\n'))

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

    def test_failure_during_request(self):
        """
        When a failure occurs during a request, the exception is propagated
        to the request's deferred.
        """
        client = self.get_client(failing_client)

        d = client.request('GET', path='/hello')
        self.assertThat(d, failed(MatchesStructure(
            value=IsInstance(RuntimeError))))

        flush_logged_errors(RuntimeError)


class TestJsonClient(TestHTTPClientBase):

    def get_client(self, client):
        return JsonClient('http://localhost:8000', client=client)

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

    def test_json_data_and_data_not_allowed(self):
        """
        When both ``data`` and ``json_data`` keyword arguments are provided
        when making a request, an exception should be raised.
        """
        with ExpectedException(ValueError, "Cannot specify both 'data' and "
                                           "'json_data' keyword arguments"):
            self.client.request(
                'GET', path='/hello', json_data={'hi': 'bye'}, data='somedata')


class TestMarathonClient(TestHTTPClientBase):
    def get_client(self, client):
        return MarathonClient(['http://localhost:8080'], client=client)

    def uri(self, path, index=0):
        return ''.join((self.client.endpoints[index], path))

    @inlineCallbacks
    def test_request_success(self):
        """
        When we make a request and there are multiple Marathon endpoints
        specified, the first endpoint is used.
        """
        agent = PerLocationAgent()
        agent.add_agent(b'localhost:8080', self.fake_server.get_agent())
        agent.add_agent(b'localhost:9090', FailingAgent())
        client = MarathonClient(
            ['http://localhost:8080', 'http://localhost:9090'],
            client=treq_HTTPClient(agent))

        d = self.cleanup_d(client.request('GET', path='/my-path'))

        request = yield self.requests.get()
        self.assertThat(request, HasRequestProperties(
            method='GET', url='http://localhost:8080/my-path'))

        request.setResponseCode(200)
        request.finish()

        yield d

    @inlineCallbacks
    def test_request_fallback(self):
        """
        When we make a request and there are multiple Marathon endpoints
        specified, and an endpoint fails, the next endpoint is used.
        """
        agent = PerLocationAgent()
        agent.add_agent(b'localhost:8080', FailingAgent())
        agent.add_agent(b'localhost:9090', self.fake_server.get_agent())
        client = MarathonClient(
            ['http://localhost:8080', 'http://localhost:9090'],
            client=treq_HTTPClient(agent))

        d = self.cleanup_d(client.request('GET', path='/my-path'))

        request = yield self.requests.get()
        self.assertThat(request, HasRequestProperties(
            method='GET', url='http://localhost:9090/my-path'))

        request.setResponseCode(200)
        request.finish()

        yield d

        flush_logged_errors(RuntimeError)

    @inlineCallbacks
    def test_request_fallback_all_failed(self):
        """
        When we make a request and there are multiple Marathon endpoints
        specified, and all the endpoints fail, the last failure should be
        returned.
        """
        agent = PerLocationAgent()
        agent.add_agent(b'localhost:8080', FailingAgent(RuntimeError('8080')))
        agent.add_agent(b'localhost:9090', FailingAgent(RuntimeError('9090')))
        client = MarathonClient(
            ['http://localhost:8080', 'http://localhost:9090'],
            client=treq_HTTPClient(agent))

        d = self.cleanup_d(client.request('GET', path='/my-path'))

        yield wait0()
        self.assertThat(d, failed(WithErrorTypeAndMessage(
            RuntimeError, '9090')))

        flush_logged_errors(RuntimeError)

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
    def test_get_json_field_incorrect_content_type(self):
        """
        When get_json_field is used to make a request and the content-type
        header is set to a value other than 'application/json' in the response
        headers then an error should be raised.
        """
        d = self.cleanup_d(
            self.client.get_json_field('field-key', path='/my-path'))

        request = yield self.requests.get()
        self.assertThat(request, HasRequestProperties(
            method='GET', url=self.uri('/my-path')))

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
    def test_get_json_field_missing_content_type(self):
        """
        When get_json_field is used to make a request and the content-type
        header is not set in the response headers then an error should be
        raised.
        """
        d = self.cleanup_d(
            self.client.get_json_field('field-key', path='/my-path'))

        request = yield self.requests.get()
        self.assertThat(request, HasRequestProperties(
            method='GET', url=self.uri('/my-path')))

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

        # Expect request.finish() to result in a logged failure
        flush_logged_errors(ResponseDone)

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

        # Expect request.finish() to result in a logged failure
        flush_logged_errors(ResponseDone)

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

        # Expect request.finish() to result in a logged failure
        flush_logged_errors(ResponseDone)

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


class TestMarathonLbClient(TestHTTPClientBase):
    def get_client(self, client):
        return MarathonLbClient(['http://lb1:9090', 'http://lb2:9090'],
                                client=client)

    @inlineCallbacks
    def test_request_success(self):
        """
        When a request is made, it is made to all marathon-lb instances and
        the responses are returned.
        """
        d = self.cleanup_d(self.client.request('GET', path='/my-path'))

        for lb in ['lb1', 'lb2']:
            request = yield self.requests.get()
            self.assertThat(request, HasRequestProperties(
                method='GET', url='http://%s:9090/my-path' % (lb,)))

            request.setResponseCode(200)
            request.finish()

        responses = yield d
        self.assertThat(responses, HasLength(2))
        for response in responses:
            self.assertThat(response.code, Equals(200))

    @inlineCallbacks
    def test_request_partial_failure(self):
        """
        When a request is made and an error status code is returned from some
        (but not all) of the matathon-lb instances, then the request returns
        the list of responses with a None value for the unhappy request.
        """
        d = self.cleanup_d(self.client.request('GET', path='/my-path'))

        lb1_request = yield self.requests.get()
        self.assertThat(lb1_request, HasRequestProperties(
            method='GET', url='http://lb1:9090/my-path'))

        lb2_request = yield self.requests.get()
        self.assertThat(lb2_request, HasRequestProperties(
            method='GET', url='http://lb2:9090/my-path'))

        # Fail the first one
        lb1_request.setResponseCode(500)
        lb1_request.setHeader('content-type', 'text/plain')
        lb1_request.write(b'Internal Server Error')
        lb1_request.finish()

        # ...but succeed the second
        lb2_request.setResponseCode(200)
        lb2_request.setHeader('content-type', 'text/plain')
        lb2_request.write(b'Yes, I work')
        lb2_request.finish()

        responses = yield d
        self.assertThat(responses, HasLength(2))
        lb1_response, lb2_response = responses

        self.assertThat(lb1_response, Is(None))
        self.assertThat(lb2_response, MatchesStructure(
            code=Equals(200),
            headers=HasHeader('content-type', ['text/plain'])
        ))

        lb2_response_content = yield lb2_response.content()
        self.assertThat(lb2_response_content, Equals(b'Yes, I work'))

        flush_logged_errors(HTTPError)

    @inlineCallbacks
    def test_request_failure(self):
        """
        When the requests to all the marathon-lb instances have a bad status
        code then an error should be raised.
        """
        d = self.cleanup_d(self.client.request('GET', path='/my-path'))

        for lb in ['lb1', 'lb2']:
            request = yield self.requests.get()
            self.assertThat(request, HasRequestProperties(
                method='GET', url='http://%s:9090/my-path' % (lb,)))

            request.setResponseCode(500)
            request.setHeader('content-type', 'text/plain')
            request.write(b'Internal Server Error')
            request.finish()

        yield wait0()
        self.assertThat(d, failed(WithErrorTypeAndMessage(
            RuntimeError,
            'Failed to make a request to all marathon-lb instances'
        )))

        flush_logged_errors(HTTPError)

    @inlineCallbacks
    def test_mlb_signal_hup(self):
        """
        When the marathon-lb client is used to send a SIGHUP signal to
        marathon-lb, all the correct API endpoints are called.
        """
        d = self.cleanup_d(self.client.mlb_signal_hup())

        for lb in ['lb1', 'lb2']:
            request = yield self.requests.get()
            self.assertThat(request, HasRequestProperties(
                method='POST', url='http://%s:9090/_mlb_signal/hup' % (lb,)))

            request.setResponseCode(200)
            request.setHeader('content-type', 'text/plain')
            request.write(b'Sent SIGHUP signal to marathon-lb')
            request.finish()

        responses = yield d
        self.assertThat(len(responses), Equals(2))
        for response in responses:
            self.assertThat(response.code, Equals(200))
            self.assertThat(response.headers, HasHeader(
                'content-type', ['text/plain']))

            response_text = yield response.text()
            self.assertThat(response_text,
                            Equals('Sent SIGHUP signal to marathon-lb'))

    @inlineCallbacks
    def test_mlb_signal_usr1(self):
        """
        When the marathon-lb client is used to send a SIGUSR1 signal to
        marathon-lb, all the correct API endpoint is called.
        """
        d = self.cleanup_d(self.client.mlb_signal_usr1())

        for lb in ['lb1', 'lb2']:
            request = yield self.requests.get()
            self.assertThat(request, HasRequestProperties(
                method='POST', url='http://%s:9090/_mlb_signal/usr1' % (lb,)))

            request.setResponseCode(200)
            request.setHeader('content-type', 'text/plain')
            request.write(b'Sent SIGUSR1 signal to marathon-lb')
            request.finish()

        responses = yield d
        self.assertThat(len(responses), Equals(2))
        for response in responses:
            self.assertThat(response.code, Equals(200))
            self.assertThat(response.headers, HasHeader(
                'content-type', ['text/plain']))

            response_text = yield response.text()
            self.assertThat(response_text,
                            Equals('Sent SIGUSR1 signal to marathon-lb'))
