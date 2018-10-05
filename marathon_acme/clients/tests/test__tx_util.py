import os

from OpenSSL.SSL import Error as SSLError

from service_identity.exceptions import DNSMismatch, VerificationError

from testtools import TestCase
from testtools.twistedsupport import (
    AsynchronousDeferredRunTestForBrokenTwisted)

from treq.client import HTTPClient

from twisted.internet import ssl
from twisted.internet.defer import DeferredList
from twisted.internet.endpoints import SSL4ServerEndpoint
from twisted.internet.task import Clock
from twisted.python.filepath import FilePath
from twisted.web._newclient import ResponseNeverReceived
from twisted.web.client import Agent, HTTPConnectionPool
from twisted.web.server import Site

from marathon_acme.clients._tx_util import ClientPolicyForHTTPS, default_client
from marathon_acme.clients.tests.helpers import QueueResource


class TestDefaultClientFunc(object):
    def test_defaults(self):
        """
        When only a reactor is passed to default_client, a client is created
        with all the defaults we expect.
        """
        reactor = Clock()

        client, actual_reactor = default_client(reactor)

        # The reactor is the one we passed
        assert actual_reactor is reactor

        # We get a client
        assert isinstance(client, HTTPClient)

        # The client has the default agent and the agent has our reactor
        # NOTE: Accessing treq HTTPClient internals :-(
        agent = client._agent
        assert isinstance(agent, Agent)
        # NOTE: Twisted _AgentBase internals :-(
        assert agent._reactor is reactor
        pool = agent._pool

        # The agent has a connection pool that is not persistent
        assert isinstance(pool, HTTPConnectionPool)
        assert not pool.persistent
        # NOTE: Accessing Twisted HTTPConnectionPool internals :-(
        assert pool._reactor is reactor

    def test_client_provided(self):
        """
        When default_client is passed a client it should return that client
        and the reactor.
        """
        reactor = Clock()
        client = HTTPClient(Agent(reactor))

        actual_client, actual_reactor = default_client(reactor, client)

        assert actual_client is client
        assert actual_reactor is reactor

    def test_reactor_not_provided(self):
        """
        When default_client is not passed a reactor, if should use the default
        reactor.
        """
        client, actual_reactor = default_client(None)

        # NOTE: Accessing treq HTTPClient & Twisted _AgentBase internals :-(
        assert client._agent._reactor is actual_reactor

        from twisted.internet import reactor
        assert actual_reactor is reactor

    def test_agent_provided(self):
        """
        When default_client is passed an agent, it should create the client
        with that agent.
        """
        reactor = Clock()
        agent = Agent(reactor)

        client, _ = default_client(reactor, agent=agent)

        # NOTE: Accessing treq HTTPClient internals :-(
        assert client._agent == agent

    def test_agent_parts_provided(self):
        """
        When default_client is passed parameters for the parts that make up an
        agent, is should create an agent and client with those parameters.
        """
        reactor = Clock()
        contextFactory = ClientPolicyForHTTPS()

        client, actual_reactor = default_client(
            reactor, persistent=True, contextFactory=contextFactory)

        # NOTE: Accessing treq HTTPClient internals :-(
        agent = client._agent
        assert isinstance(agent, Agent)

        # NOTE: Accessing Twisted _AgentBase internals :-(
        assert agent._reactor is reactor
        pool = agent._pool

        assert isinstance(pool, HTTPConnectionPool)
        assert pool.persistent
        # NOTE: Accessing Twisted HTTPConnectionPool internals :-(
        assert pool._reactor is reactor


FIXTURES = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'fixtures')
CA_CERT = os.path.join(FIXTURES, 'ca.pem')
CA2_CERT = os.path.join(FIXTURES, 'ca2.pem')
CLIENT_CERT = os.path.join(FIXTURES, 'vault-client.pem')
CLIENT_KEY = os.path.join(FIXTURES, 'vault-client-key.pem')
CLIENT2_CERT = os.path.join(FIXTURES, 'vault-client2.pem')
CLIENT2_KEY = os.path.join(FIXTURES, 'vault-client2-key.pem')
SERVER_CERT = os.path.join(FIXTURES, 'vault-server.pem')
SERVER_KEY = os.path.join(FIXTURES, 'vault-server-key.pem')
SERVER_COMMON_NAME = 'vault.example.org'


class TestClientPolicyForHTTPS(TestCase):
    # FIXME: Twisted's (18.7.0) TLSMemoryBIOProtocol seems to hang around in
    # the reactor unless we use AsynchronousDeferredRunTestForBrokenTwisted:
    # https://testtools.readthedocs.io/en/latest/api.html#testtools.twistedsupport.AsynchronousDeferredRunTestForBrokenTwisted
    run_tests_with = (
        AsynchronousDeferredRunTestForBrokenTwisted.make_factory(timeout=1.0))

    def create_client(self, **policy_kwargs):
        policy = ClientPolicyForHTTPS.from_pem_files(**policy_kwargs)
        client, _ = default_client(None, contextFactory=policy)
        return client

    def create_ssl_server_endpoint(
            self, caKey=None, privateKey=SERVER_KEY, certKey=SERVER_CERT):
        # This is somewhat copied from the endpoint description parsing code:
        # https://github.com/twisted/twisted/blob/twisted-18.7.0/src/twisted/internet/endpoints.py#L1325-L1408
        # But we can't use endpoint descriptions because we want to verify the
        # client certificate (add the trustRoot param to CertificateOptions).
        certPEM = FilePath(certKey).getContent()
        keyPEM = FilePath(privateKey).getContent()
        privateCertificate = (
            ssl.PrivateCertificate.loadPEM(certPEM + b'\n' + keyPEM))

        trustRoot = None
        if caKey is not None:
            caPEM = FilePath(caKey).getContent()
            trustRoot = ssl.Certificate.loadPEM(caPEM)

        cf = ssl.CertificateOptions(
            privateKey=privateCertificate.privateKey.original,
            certificate=privateCertificate.original,
            trustRoot=trustRoot
        )

        from twisted.internet import reactor
        return SSL4ServerEndpoint(reactor, 0, cf, interface='127.0.0.1')

    def _test_request(self, client, endpoint, assert_request,
                      assert_response, hostname=None):
        resource = QueueResource()
        d = endpoint.listen(Site(resource))

        def make_request(listening_port):
            host = listening_port.getHost()
            addr = hostname if hostname is not None else host.host
            address = 'https://{}:{}'.format(addr, host.port)

            deferreds = []

            # Actually make the request
            response_d = client.get(address)
            deferreds.append(response_d)

            # Get the request server side
            if assert_request is not None:
                request_d = resource.get()
                deferreds.append(request_d)
                request_d.addBoth(assert_request)

            # Check the response
            response_d.addBoth(assert_response)

            # Make sure everything completes
            done_d = DeferredList(
                deferreds, fireOnOneErrback=True, consumeErrors=True)

            # Make sure there are no pending requests
            done_d.addCallback(lambda _: resource.assert_empty())

            # Finally, shutdown
            done_d.addCallback(lambda _: listening_port.stopListening())
            return done_d

        return d.addCallback(make_request)

    def _test_request_success(self, client, endpoint, hostname=None):
        # Do a very simple check that the connection is secure and the response
        # code works.
        def assert_request(request):
            assert request.isSecure()

            request.setResponseCode(418)
            request.finish()

        def assert_response(response):
            assert response.code == 418

        return self._test_request(
            client, endpoint, assert_request, assert_response,
            hostname=hostname)

    def test_ca_cert(self):
        """
        When a client is created with a custom CA certificate, that certificate
        is used to validate the server's certificate.
        """
        client = self.create_client(caKey=CA_CERT)
        endpoint = self.create_ssl_server_endpoint()

        return self._test_request_success(
            client, endpoint, hostname='localhost')

    def test_wrong_ca_cert(self):
        """
        When a client is created with a custom CA certificate, that certificate
        is used to validate the server's certificate and is rejected if the
        CA does not match.
        """
        client = self.create_client(caKey=CA2_CERT)
        endpoint = self.create_ssl_server_endpoint()

        # A request should never arrive since the request fails
        assert_request = None

        def assert_response(failure):
            assert isinstance(failure.value, ResponseNeverReceived)

            [reason] = failure.value.reasons
            assert isinstance(reason.value, SSLError)
            assert reason.value.args == ([(
                'SSL routines',
                'tls_process_server_certificate',
                'certificate verify failed'
            )],)

        return self._test_request(
            client, endpoint, assert_request, assert_response,
            hostname='localhost')

    def test_client_certs(self):
        """
        When a client is created with a custom client certificates, those
        certificates can be validated by the server.
        """
        client = self.create_client(
            caKey=CA_CERT, privateKey=CLIENT_KEY, certKey=CLIENT_CERT)

        # NOTE: The caKey parameter here means the server checks the client
        # cert against this CA cert.
        endpoint = self.create_ssl_server_endpoint(caKey=CA_CERT)

        return self._test_request_success(
            client, endpoint, hostname='localhost')

    def test_wrong_client_certs(self):
        """
        When a client is created with a custom client certificates, those
        certificates can be validated by the server and are rejected if they
        are invalid.
        """
        client = self.create_client(
            caKey=CA_CERT, privateKey=CLIENT2_KEY, certKey=CLIENT2_CERT)

        # NOTE: The caKey parameter here means the server checks the client
        # cert against this CA cert.
        endpoint = self.create_ssl_server_endpoint(caKey=CA_CERT)

        # A request should never arrive since the request fails
        assert_request = None

        def assert_response(failure):
            assert isinstance(failure.value, ResponseNeverReceived)

            [reason] = failure.value.reasons
            assert isinstance(reason.value, SSLError)
            assert reason.value.args == ([(
                'SSL routines',
                'ssl3_read_bytes',
                'tlsv1 alert unknown ca'
            )],)

        return self._test_request(
            client, endpoint, assert_request, assert_response,
            hostname='localhost')

    def test_tls_server_name(self):
        """
        When a client is created with a custom TLS server name, that server
        name is used for SSL verification.
        """
        client = self.create_client(
            caKey=CA_CERT, tls_server_name=SERVER_COMMON_NAME)
        endpoint = self.create_ssl_server_endpoint()

        # NOTE: Not passing hostname here, which means we connect by the
        # address (127.0.0.1). This would fail with Twisted 18.7.0 as it
        # doesn't like IP addresses for SSL verification, but we pass
        # tls_server_name so it should be ok.
        return self._test_request_success(client, endpoint)

    def test_wrong_tls_server_name(self):
        """
        When a client is created with a custom TLS server name, that server
        name is used for SSL verification and verification will fail if there
        is a mismatch.
        """
        client = self.create_client(
            caKey=CA_CERT, tls_server_name='www.google.com')
        endpoint = self.create_ssl_server_endpoint()

        assert_request = None

        def assert_response(failure):
            assert isinstance(failure.value, ResponseNeverReceived)

            [reason] = failure.value.reasons
            assert isinstance(reason.value, VerificationError)

            [error] = reason.value.errors
            assert isinstance(error, DNSMismatch)
            assert error.mismatched_id.hostname == b'www.google.com'

        return self._test_request(
            client, endpoint, assert_request, assert_response)
