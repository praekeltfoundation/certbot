import json

from testtools.matchers import Equals
from testtools.twistedsupport import failed, flush_logged_errors

from treq.client import HTTPClient as treq_HTTPClient

from twisted.internet.defer import inlineCallbacks
from twisted.web._newclient import ResponseDone

from txfake.fake_connection import wait0

from marathon_acme.clients._base import HTTPError
from marathon_acme.clients.marathon import MarathonClient
from marathon_acme.clients.tests.helpers import PerLocationAgent
from marathon_acme.clients.tests.matchers import HasRequestProperties
from marathon_acme.clients.tests.test__base import TestHTTPClientBase
from marathon_acme.server import write_request_json
from marathon_acme.tests.helpers import FailingAgent
from marathon_acme.tests.matchers import HasHeader, WithErrorTypeAndMessage


def json_response(request, json_data, response_code=200):
    """ Set the response code, write encoded JSON, and finish() a request. """
    request.setResponseCode(response_code)
    write_request_json(request, json_data)
    request.finish()


def write_json_event(request, event, json_data):
    request.write('event: {}\n'.format(event).encode('utf-8'))
    request.write('data: {}\n'.format(json.dumps(json_data)).encode('utf-8'))
    request.write(b'\n')


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
            method='GET', url=self.uri('/v2/events'),
            query={'event_type': ['test']}))
        self.assertThat(request.requestHeaders,
                        HasHeader('accept', ['text/event-stream']))

        request.setResponseCode(200)
        request.setHeader('Content-Type', 'text/event-stream')

        json_data = {'hello': 'world'}
        request.write(b'event: test\n')
        request.write(
            'data: {}\n'.format(json.dumps(json_data)).encode('utf-8'))
        request.write(b'\n')

        yield wait0()
        self.assertThat(data, Equals([json_data]))

        request.finish()
        yield d

        # Expect request.finish() to result in a logged failure
        flush_logged_errors(ResponseDone)

    @inlineCallbacks
    def test_get_events_no_callback(self):
        """
        When a request is made to Marathon's event stream, a callback should
        not receive event data if there is no callback for the event type.
        """
        data = []
        d = self.cleanup_d(self.client.get_events({'test': data.append}))

        request = yield self.requests.get()
        self.assertThat(request, HasRequestProperties(
            method='GET', url=self.uri('/v2/events'),
            query={'event_type': ['test']}))
        self.assertThat(request.requestHeaders,
                        HasHeader('accept', ['text/event-stream']))

        request.setResponseCode(200)
        request.setHeader('Content-Type', 'text/event-stream')

        json_data = {'hello': 'world'}
        request.write(b'event: not_test\n')
        request.write(
            'data: {}\n'.format(json.dumps(json_data)).encode('utf-8'))
        request.write(b'\n')

        yield wait0()
        self.assertThat(data, Equals([]))

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
            method='GET', url=self.uri('/v2/events'),
            query={'event_type': ['test']}))
        self.assertThat(request.requestHeaders,
                        HasHeader('accept', ['text/event-stream']))

        request.setResponseCode(200)
        request.setHeader('Content-Type', 'text/event-stream')

        json_data1 = {'hello': 'world'}
        request.write(b'event: test\n')
        request.write(
            'data: {}\n'.format(json.dumps(json_data1)).encode('utf-8'))
        request.write(b'\n')

        json_data2 = {'hi': 'planet'}
        request.write(
            'data: {}\n'.format(json.dumps(json_data2)).encode('utf-8'))
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
            method='GET', url=self.uri('/v2/events'),
            query={'event_type': ['test1', 'test2']}))
        self.assertThat(request.requestHeaders,
                        HasHeader('accept', ['text/event-stream']))

        request.setResponseCode(200)
        request.setHeader('Content-Type', 'text/event-stream')

        json_data1 = {'hello': 'world'}
        write_json_event(request, 'test1', json_data1)

        json_data2 = {'hello': 'computer'}
        write_json_event(request, 'test2', json_data2)

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
            method='GET', url=self.uri('/v2/events'),
            query={'event_type': ['test']}))
        self.assertThat(request.requestHeaders,
                        HasHeader('accept', ['text/event-stream']))

        request.setResponseCode(202)
        request.setHeader('Content-Type', 'text/event-stream')

        json_data = {'hello': 'world'}
        write_json_event(request, 'test', json_data)

        yield wait0()
        self.assertThat(d, failed(WithErrorTypeAndMessage(
            HTTPError, 'Non-200 response code (202) for url: '
                       'http://localhost:8080/v2/events?event_type=test')))

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
            method='GET', url=self.uri('/v2/events'),
            query={'event_type': ['test']}))
        self.assertThat(request.requestHeaders,
                        HasHeader('accept', ['text/event-stream']))

        request.setResponseCode(200)
        request.setHeader('Content-Type', 'application/json')

        json_data = {'hello': 'world'}
        write_json_event(request, 'test', json_data)

        yield wait0()
        self.assertThat(d, failed(WithErrorTypeAndMessage(
            HTTPError,
            'Expected header "Content-Type" to be "text/event-stream" but '
            'found "application/json" instead')))

        self.assertThat(data, Equals([]))

        request.finish()
        yield d
