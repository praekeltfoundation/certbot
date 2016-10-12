from acme.jose import JWKRSA
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from fixtures import TempDir
from testtools import TestCase
from testtools.matchers import Equals
from twisted.python.filepath import FilePath
from txacme.util import generate_private_key

from marathon_acme.acme_util import maybe_key


class TestMaybeKey(TestCase):
    def setUp(self):
        super(TestMaybeKey, self).setUp()

        self.pem_path = FilePath(self.useFixture(TempDir()).path)

    def test_key_exists(self):
        """
        When we get the client key and the key file already exists, the file
        should be read and the existing key returned.
        """
        raw_key = generate_private_key(u'rsa')
        expected_key = JWKRSA(key=raw_key)

        pem_file = self.pem_path.child(u'client.key')
        pem_file.setContent(raw_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption()
        ))

        actual_key = maybe_key(self.pem_path)
        self.assertThat(actual_key, Equals(expected_key))

    def test_key_not_exists(self):
        """
        When we get the client key and no key file exists, a new key should be
        generated and the key should be saved in a key file.
        """
        key = maybe_key(self.pem_path)

        pem_file = self.pem_path.child(u'client.key')
        self.assertThat(pem_file.exists(), Equals(True))

        file_key = serialization.load_pem_private_key(
            pem_file.getContent(),
            password=None,
            backend=default_backend()
        )
        file_key = JWKRSA(key=file_key)

        self.assertThat(key, Equals(file_key))
