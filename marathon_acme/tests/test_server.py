# -*- coding: utf-8 -*-
from operator import methodcaller

from testtools.assertions import assert_that
from testtools.matchers import AfterPreprocessing as After
from testtools.matchers import Equals, MatchesAll, MatchesStructure
from testtools.twistedsupport import succeeded
from treq.content import json_content
from treq.testing import StubTreq
from twisted.web.resource import Resource
from twisted.web.static import Data

from marathon_acme.server import MarathonAcmeServer, Health
from marathon_acme.tests.matchers import HasHeader, IsJsonResponseWithCode


class TestMarathonAcmeServer(object):
    def setup_method(self):
        self.responder_resource = Resource()
        self.server = MarathonAcmeServer(self.responder_resource)
        self.client = StubTreq(self.server.app.resource())

    def test_responder_resource_empty(self):
        """
        When a GET request is made to the ACME challenge path, but the
        responder resource is empty, a 404 response code should be returned.
        """
        response = self.client.get(
            'http://localhost/.well-known/acme-challenge/foo')
        assert_that(response, succeeded(MatchesStructure(code=Equals(404))))

    def test_responder_resource_child(self):
        """
        When a GET request is made to the ACME challenge path, and the
        responder resource has a child resource at the correct path, the value
        of the resource should be returned.
        """
        self.responder_resource.putChild(b'foo', Data(b'bar', 'text/plain'))

        response = self.client.get(
            'http://localhost/.well-known/acme-challenge/foo')
        assert_that(response, succeeded(MatchesAll(
            MatchesStructure(
                code=Equals(200),
                headers=HasHeader('Content-Type', ['text/plain'])),
            After(methodcaller('content'), succeeded(Equals(b'bar')))
        )))

        # Sanity check that a request to a different subpath does not succeed
        response = self.client.get(
            'http://localhost/.well-known/acme-challenge/baz')
        assert_that(response, succeeded(MatchesStructure(code=Equals(404))))

    def test_health_healthy(self):
        """
        When a GET request is made to the health endpoint, and the health
        handler reports that the service is healthy, a 200 status code should
        be returned together with the JSON message from the handler.
        """
        self.server.set_health_handler(
            lambda: Health(True, {'message': "I'm 200/OK!"}))

        response = self.client.get('http://localhost/health')
        assert_that(response, succeeded(MatchesAll(
            IsJsonResponseWithCode(200),
            After(json_content, succeeded(Equals({'message': "I'm 200/OK!"})))
        )))

    def test_health_unhealthy(self):
        """
        When a GET request is made to the health endpoint, and the health
        handler reports that the service is unhealthy, a 503 status code should
        be returned together with the JSON message from the handler.
        """
        self.server.set_health_handler(
            lambda: Health(False, {'error': "I'm sad :("}))

        response = self.client.get('http://localhost/health')
        assert_that(response, succeeded(MatchesAll(
            IsJsonResponseWithCode(503),
            After(json_content, succeeded(Equals({'error': "I'm sad :("})))
        )))

    def test_health_handler_unset(self):
        """
        When a GET request is made to the health endpoint, and the health
        handler hasn't been set, a 501 status code should be returned together
        with a JSON message that explains that the handler is not set.
        """
        response = self.client.get('http://localhost/health')
        assert_that(response, succeeded(MatchesAll(
            IsJsonResponseWithCode(501),
            After(json_content, succeeded(Equals({
                'error': 'Cannot determine service health: no handler set'
            })))
        )))

    def test_health_handler_unicode(self):
        """
        When a GET request is made to the health endpoint, and the health
        handler reports that the service is unhealthy, a 503 status code should
        be returned together with the JSON message from the handler.
        """
        self.server.set_health_handler(
            lambda: Health(False, {'error': u"I'm sad 🙁"}))

        response = self.client.get('http://localhost/health')
        assert_that(response, succeeded(MatchesAll(
            IsJsonResponseWithCode(503),
            After(json_content, succeeded(Equals({'error': u"I'm sad 🙁"})))
        )))
