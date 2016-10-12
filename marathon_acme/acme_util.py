from acme.jose import JWKRSA
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization

from txacme.util import generate_private_key


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
