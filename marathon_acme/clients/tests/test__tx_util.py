import os

from testtools import TestCase
from testtools.twistedsupport import (
    AsynchronousDeferredRunTestForBrokenTwisted)

from treq.client import HTTPClient

from twisted.internet import ssl
from twisted.internet.defer import DeferredList
from twisted.internet.endpoints import SSL4ServerEndpoint
from twisted.internet.task import Clock
from twisted.python.filepath import FilePath
from twisted.web.client import Agent
from twisted.web.server import Site

from marathon_acme.clients._tx_util import ClientPolicyForHTTPS, default_client
from marathon_acme.clients.tests.helpers import QueueResource


class TestDefaultClientFunc(object):
    def test_default_client(self):
        """
        When default_client is passed a client it should return that client.
        """
        reactor = Clock()
        client = HTTPClient(Agent(reactor))

        actual_client, actual_reactor = default_client(reactor, client)

        assert actual_client is client
        assert actual_reactor is reactor

    def test_default_client_not_provided(self):
        """
        When default_agent is not passed an agent, it should return a default
        agent.
        """
        client, actual_reactor = default_client(None)

        assert isinstance(client, HTTPClient)

        from twisted.internet import reactor
        assert actual_reactor is reactor


FIXTURES = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'fixtures')
CA_CERT = os.path.join(FIXTURES, 'ca.pem')
CLIENT_CERT = os.path.join(FIXTURES, 'vault-client.pem')
CLIENT_KEY = os.path.join(FIXTURES, 'vault-client-key.pem')
CLIENT_COMMON_NAME = 'marathon-acme.example.org'
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

            # Actually make the request
            response_d = client.get(address)

            # Get the request server side
            request_d = resource.get()
            request_d.addBoth(assert_request)

            # Check the response
            response_d.addBoth(assert_response)

            # Make sure everything completes
            done_d = DeferredList([request_d, response_d],
                                  fireOnOneErrback=True, consumeErrors=True)

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
