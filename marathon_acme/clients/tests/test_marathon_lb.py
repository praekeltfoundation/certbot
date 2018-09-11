from testtools.matchers import Equals, HasLength, Is, MatchesStructure
from testtools.twistedsupport import failed, flush_logged_errors

from twisted.internet.defer import inlineCallbacks

from txfake.fake_connection import wait0

from marathon_acme.clients._base import HTTPError
from marathon_acme.clients.marathon_lb import MarathonLbClient
from marathon_acme.clients.tests.test__base import TestHTTPClientBase
from marathon_acme.tests.matchers import (
    HasHeader, HasRequestProperties, WithErrorTypeAndMessage)


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
