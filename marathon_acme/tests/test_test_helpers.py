import pytest
from testtools import ExpectedException
from testtools.assertions import assert_that
from testtools.matchers import (
    Equals, Is, IsInstance, MatchesAll, MatchesDict, MatchesListwise,
    MatchesPredicate, MatchesStructure)
from testtools.twistedsupport import failed, succeeded
from twisted.internet.defer import succeed

from marathon_acme.tests.helpers import FailingAgent, PerLocationAgent


class DummyAgent(object):
    def request(self, *args, **kwargs):
        return succeed((args, kwargs))


class TestPerLocationAgent(object):
    @pytest.fixture
    def agent(self):
        return PerLocationAgent()

    def test_keyerror_if_location_unset(self, agent):
        """
        When a request is made using the agent and no delegate agent has been
        added for the URI location/authority, a KeyError is expected.
        """
        with ExpectedException(KeyError, r"b?'foo:8080'"):
            agent.request(b'GET', b'http://foo:8080')

    def test_delegates_to_agent_for_location(self, agent):
        """
        When a request is made using the agent, the added agents are delegated
        to based on the URI location/authority.
        """
        agent.add_agent(b'foo:8080', DummyAgent())
        agent.add_agent(b'bar:8080', FailingAgent(RuntimeError('bar')))
        agent.add_agent(b'foo:9090', FailingAgent(RuntimeError('9090')))

        d = agent.request(b'GET', b'http://foo:8080')
        assert_that(d, succeeded(MatchesListwise([
            MatchesListwise([Equals(b'GET'), Equals(b'http://foo:8080')]),
            MatchesDict({'headers': Is(None), 'bodyProducer': Is(None)})
        ])))

        # Scheme doesn't matter
        d = agent.request(b'GET', b'https://foo:8080')
        assert_that(d, succeeded(MatchesListwise([
            MatchesListwise([Equals(b'GET'), Equals(b'https://foo:8080')]),
            MatchesDict({'headers': Is(None), 'bodyProducer': Is(None)})
        ])))

        # Path doesn't matter
        d = agent.request(b'GET', b'http://foo:8080/bar/baz')
        assert_that(d, succeeded(MatchesListwise([
            MatchesListwise([
                Equals(b'GET'), Equals(b'http://foo:8080/bar/baz')]),
            MatchesDict({'headers': Is(None), 'bodyProducer': Is(None)})
        ])))

        # Hostname *does* matter
        d = agent.request(b'GET', b'http://bar:8080')
        assert_that(d, failed(MatchesStructure(value=MatchesAll(
            IsInstance(RuntimeError),
            MatchesPredicate(str, Equals('bar'))
        ))))

        # Port *does* matter
        d = agent.request(b'GET', b'http://foo:9090')
        assert_that(d, failed(MatchesStructure(value=MatchesAll(
            IsInstance(RuntimeError),
            MatchesPredicate(str, Equals('9090'))
        ))))

        # Other args passed through
        d = agent.request(b'GET', b'http://foo:8080', 'bar', 'baz')
        assert_that(d, succeeded(MatchesListwise([
            MatchesListwise([Equals(b'GET'), Equals(b'http://foo:8080')]),
            MatchesDict(
                {'headers': Equals('bar'), 'bodyProducer': Equals('baz')})
        ])))
