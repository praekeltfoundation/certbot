# -*- coding: utf-8 -*-
from testtools.assertions import assert_that
from testtools.matchers import AfterPreprocessing as After
from testtools.matchers import Equals, MatchesAll
from testtools.twistedsupport import succeeded
from treq.testing import StubTreq

from marathon_acme.clients import json_content
from marathon_acme.server import HealthServer, Health
from marathon_acme.tests.matchers import IsJsonResponseWithCode


class TestHealthServer(object):
    def setup_method(self):
        self.event_server = HealthServer()
        self.client = StubTreq(self.event_server.app.resource())

    def test_health_healthy(self):
        """
        When a GET request is made to the health endpoint, and the health
        handler reports that the service is healthy, a 200 status code should
        be returned together with the JSON message from the handler.
        """
        self.event_server.set_health_handler(
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
        self.event_server.set_health_handler(
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
        self.event_server.set_health_handler(
            lambda: Health(False, {'error': u"I'm sad 🙁"}))

        response = self.client.get('http://localhost/health')
        assert_that(response, succeeded(MatchesAll(
            IsJsonResponseWithCode(503),
            After(json_content, succeeded(Equals({'error': u"I'm sad 🙁"})))
        )))
