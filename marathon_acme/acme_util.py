from acme.jose import JWKRSA
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from txacme.interfaces import ICertificateStore
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
    return JWKRSA(key=key)


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
                'know what to do with it.')
        return self.mlb_client.mlb_signal_usr1()

    def as_dict(self):
        return self.certificate_store.as_dict()
