from functools import partial

from acme import jose
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from treq.client import HTTPClient
from twisted.web.client import Agent
from twisted.web.resource import Resource
from txacme.challenges._http import HTTP01Responder
from txacme.client import Client as txacme_Client, JWSClient
from txacme.interfaces import ICertificateStore
from txacme.service import AcmeIssuingService
from txacme.util import generate_private_key
from zope.interface import implementer


def maybe_key(pem_path):
    """
    Set up a client key if one does not exist already.

    https://gist.github.com/glyph/27867a478bb71d8b6046fbfb176e1a33#file-local-certs-py-L32-L50

    :type pem_path: twisted.python.filepath.FilePath
    :param pem_path:
        The path to the certificate directory to use.
    """
    acme_key_file = pem_path.child(u'client.key')
    if acme_key_file.exists():
        key = serialization.load_pem_private_key(
            acme_key_file.getContent(),
            password=None,
            backend=default_backend()
        )
    else:
        key = generate_private_key(u'rsa')
        acme_key_file.setContent(
            key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption()
            )
        )
    return jose.JWKRSA(key=key)


def create_txacme_service(cert_store, mlb_client, txacme_client_creator, clock,
                          root_resource, **kwargs):
    """
    Create the txacme ``AcmeIssuingService``.

    :param cert_store: The ``txacme.interfaces.ICertificateStore`` to use.
    :param mlb_client:
        The ``marathon_acme.clients.MarathonLbClient`` instance to tie to store
        calls in the created certificate store.
    :param txacme_client_creator:
        No-args callable that returns a deferred that will be called with the
        created client.
    :param clock:
        ``IReactorTime`` provider; usually the reactor, when not testing.
    :param Resource root_resource: The HTTP server's root resource.
    :param kwargs: Other arguments to create the ``AcmeIssuingService`` with.
    """
    mlb_cert_store = MlbCertificateStore(cert_store, mlb_client)
    responders = [_create_txacme_responder(root_resource)]
    return AcmeIssuingService(
        mlb_cert_store, txacme_client_creator, clock, responders, **kwargs)


def _create_txacme_responder(root_resource):
    """
    Create the txacme HTTP01Responder and attach it to the resource tree under
    /.well-known/acme-challenge/<responder>.

    :param Resource root_resource: The HTTP server's root resource
    """
    well_known = Resource()
    root_resource.putChild(b'.well-known', well_known)
    responder = HTTP01Responder()
    well_known.putChild(b'acme-challenge', responder.resource)
    return responder


def create_txacme_client_creator(reactor, url, key, alg=jose.RS256):
    """
    Create a creator for txacme clients to provide to the txacme service. See
    ``txacme.client.Client.from_url()``. We create the underlying JWSClient
    with a non-persistent pool to avoid
    https://github.com/mithrandi/txacme/issues/86.

    :return: a callable that returns a deffered that returns the client
    """
    # Creating an Agent without specifying a pool gives us the default pool
    # which is non-persistent.
    jws_client = JWSClient(HTTPClient(agent=Agent(reactor)), key, alg)

    return partial(txacme_Client.from_url, reactor, url, key, alg, jws_client)


@implementer(ICertificateStore)
class MlbCertificateStore(object):
    """
    An ``ICertificateStore`` that wraps another ``ICertificateStore`` but
    calls marathon-lb for a USR1 signal to be triggered when a certificate is
    stored.
    """

    def __init__(self, certificate_store, mlb_client):
        self.certificate_store = certificate_store
        self.mlb_client = mlb_client

    def get(self, server_name):
        return self.certificate_store.get(server_name)

    def store(self, server_name, pem_objects):
        d = self.certificate_store.store(server_name, pem_objects)
        # Trigger a marathon-lb reload each time a certificate changes
        d.addCallback(self._trigger_signal_usr1)
        return d

    def _trigger_signal_usr1(self, certificate_store_response):
        if certificate_store_response is not None:
            raise RuntimeError(
                "Wrapped certificate store returned something non-None. Don't "
                'know what to do with %r.' % (certificate_store_response,))
        return self.mlb_client.mlb_signal_usr1()

    def as_dict(self):
        return self.certificate_store.as_dict()
