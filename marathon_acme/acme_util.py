import uuid
from datetime import datetime, timedelta

from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.x509.oid import NameOID

from josepy.jwa import RS256
from josepy.jwk import JWKRSA

from treq.client import HTTPClient

from twisted.internet.defer import maybeDeferred
from twisted.web.client import Agent

from txacme.client import Client as txacme_Client, JWSClient
from txacme.interfaces import ICertificateStore
from txacme.util import generate_private_key

from zope.interface import implementer


def _load_pem_private_key_bytes(key_bytes):
    return serialization.load_pem_private_key(
        key_bytes, password=None, backend=default_backend())


def _dump_pem_private_key_bytes(key):
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption()
    )


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
        key = _load_pem_private_key_bytes(acme_key_file.getContent())
    else:
        key = generate_private_key(u'rsa')
        acme_key_file.setContent(_dump_pem_private_key_bytes(key))
    return JWKRSA(key=key)


def maybe_key_vault(client, mount_path):
    """
    Set up a client key in Vault if one does not exist already.

    :param client:
        The Vault API client to use.
    :param mount_path:
        The Vault key/value mount path to use.
    """
    d = client.read_kv2('client_key', mount_path=mount_path)

    def get_or_create_key(client_key):
        if client_key is not None:
            key_data = client_key['data']['data']
            key = _load_pem_private_key_bytes(key_data['key'].encode('utf-8'))
            return JWKRSA(key=key)
        else:
            key = generate_private_key(u'rsa')
            key_data = {
                'key': _dump_pem_private_key_bytes(key).decode('utf-8')
            }
            d = client.create_or_update_kv2(
                'client_key', key_data, mount_path=mount_path)

            return d.addCallback(lambda _result: JWKRSA(key=key))

    return d.addCallback(get_or_create_key)


def create_txacme_client_creator(reactor, url, key_func, alg=RS256):
    """
    Create a creator for txacme clients to provide to the txacme service. See
    ``txacme.client.Client.from_url()``. We create the underlying JWSClient
    with a non-persistent pool to avoid
    https://github.com/mithrandi/txacme/issues/86.

    :param key_func:
        A 0-args callable to create a client key. May return a Deferred.
    :return: a callable that returns a deffered that returns the client
    """
    def key_cb(key):
        # Creating an Agent without specifying a pool gives us the default pool
        # which is non-persistent.
        jws_client = JWSClient(HTTPClient(agent=Agent(reactor)), key, alg)
        return txacme_Client.from_url(reactor, url, key, alg, jws_client)

    def creator():
        return maybeDeferred(key_func).addCallback(key_cb)

    return creator


def generate_wildcard_pem_bytes():
    """
    Generate a wildcard (subject name '*') self-signed certificate valid for
    10 years.

    https://cryptography.io/en/latest/x509/tutorial/#creating-a-self-signed-certificate

    :return: Bytes representation of the PEM certificate data
    """
    key = generate_private_key(u'rsa')
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, u'*')])
    cert = (
        x509.CertificateBuilder()
        .issuer_name(name)
        .subject_name(name)
        .not_valid_before(datetime.today() - timedelta(days=1))
        .not_valid_after(datetime.now() + timedelta(days=3650))
        .serial_number(int(uuid.uuid4()))
        .public_key(key.public_key())
        .sign(
            private_key=key,
            algorithm=hashes.SHA256(),
            backend=default_backend())
        )

    return b''.join((
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption()),
        cert.public_bytes(serialization.Encoding.PEM)
    ))


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
