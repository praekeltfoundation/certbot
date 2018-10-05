from treq.client import HTTPClient

from twisted.internet import ssl
from twisted.python.compat import unicode
from twisted.python.filepath import FilePath
from twisted.web.client import (
    Agent, BrowserLikePolicyForHTTPS, HTTPConnectionPool)
from twisted.web.iweb import IPolicyForHTTPS

from zope.interface import implementer


def default_client(reactor, client=None, agent=None, contextFactory=None,
                   pool=None, persistent=False):
    reactor = _default_reactor(reactor)

    if client is not None:
        return client, reactor

    if agent is None:
        pool = HTTPConnectionPool(reactor, persistent=persistent)
        contextFactory = _default_contextFactory(contextFactory)
        agent = Agent(reactor, contextFactory=contextFactory, pool=pool)

    return HTTPClient(agent), reactor


def _default_reactor(reactor=None):
    if reactor is None:
        from twisted.internet import reactor
    return reactor


def _default_contextFactory(contextFactory=None, **kwargs):
    if contextFactory is not None:
        return contextFactory

    return BrowserLikePolicyForHTTPS(**kwargs)


@implementer(IPolicyForHTTPS)
class ClientPolicyForHTTPS(object):
    """
    Copy of twisted.web.client.BrowserLikePolicyForHTTPS but with 2 additions:
    * Allows passing the clientCertificate option to
      twisted.internet.ssl.optionsForClientTLS.
    * The hostname used for verification and SNI can be changed.

    https://github.com/twisted/twisted/blob/twisted-18.7.0/src/twisted/web/client.py#L915
    https://twistedmatrix.com/documents/current/api/twisted.internet.ssl.optionsForClientTLS.html
    """

    def __init__(self, trustRoot=None, clientCertificate=None,
                 tls_server_name=None):
        self._trustRoot = trustRoot
        self._clientCertificate = clientCertificate

        if tls_server_name and not isinstance(tls_server_name, unicode):
            tls_server_name = tls_server_name.decode('utf-8')
        self._tls_server_name = tls_server_name

    @classmethod
    def from_pem_files(cls, caKey=None, privateKey=None, certKey=None,
                       tls_server_name=None):
        """
        Load certificates from PEM files to create a ClientPolicyForHTTPS
        instance.

        :param caKey:
            Path to the CA certificate file. If not provided, the system trust
            chain will be used.
        :param privateKey:
            Path to the client private key file. If either this or certKey are
            not provided, a client-side certificate will not be used.
        :param certKey:
            Path to the client certificate file. If either this or privateKey
            are not provided, a client-side certificate will not be used.
        """
        trust_root, client_certificate = None, None
        if caKey:
            trust_root = ssl.Certificate.loadPEM(FilePath(caKey).getContent())

        if privateKey and certKey:
            # This is similar to this code:
            # https://github.com/twisted/twisted/blob/twisted-18.7.0/src/twisted/internet/endpoints.py#L1376-L1379
            certPEM = FilePath(certKey).getContent()
            keyPEM = FilePath(privateKey).getContent()
            client_certificate = (
                ssl.PrivateCertificate.loadPEM(certPEM + b'\n' + keyPEM))

        return cls(trustRoot=trust_root, clientCertificate=client_certificate,
                   tls_server_name=tls_server_name)

    def creatorForNetloc(self, hostname, port):
        if self._tls_server_name is not None:
            ssl_hostname = self._tls_server_name
        else:
            ssl_hostname = hostname.decode("ascii")

        return ssl.optionsForClientTLS(
            ssl_hostname, trustRoot=self._trustRoot,
            clientCertificate=self._clientCertificate)
