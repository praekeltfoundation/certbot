import pem
from acme.jose import JWKRSA
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from fixtures import TempDir
from testtools import TestCase
from testtools.matchers import Equals, MatchesListwise, MatchesStructure
from testtools.twistedsupport import succeeded, failed
from treq.testing import StubTreq
from twisted.python.filepath import FilePath
from twisted.internet.defer import succeed
from txacme.testing import MemoryStore
from txacme.util import generate_private_key

from marathon_acme.acme_util import MlbCertificateStore, maybe_key
from marathon_acme.clients import MarathonLbClient
from marathon_acme.tests.fake_marathon import FakeMarathonLb
from marathon_acme.tests.matchers import WithErrorTypeAndMessage


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


# From txacme
EXAMPLE_PEM_OBJECTS = [
    pem.RSAPrivateKey(
        b'-----BEGIN RSA PRIVATE KEY-----\n'
        b'iq63EP+H3w==\n'
        b'-----END RSA PRIVATE KEY-----\n'),
    pem.Certificate(
        b'-----BEGIN CERTIFICATE-----\n'
        b'yns=\n'
        b'-----END CERTIFICATE-----\n'),
    pem.Certificate(
        b'-----BEGIN CERTIFICATE-----\n'
        b'pNaiqhAT\n'
        b'-----END CERTIFICATE-----\n'),
    ]


class TestMlbCertificateStore(TestCase):
    def setUp(self):
        super(TestMlbCertificateStore, self).setUp()
        self.fake_marathon_lb = FakeMarathonLb()
        self.client = MarathonLbClient(
            ['http://lb1:9090'],
            client=StubTreq(self.fake_marathon_lb.app.resource()))

        certificate_store = MemoryStore()
        self.mlb_store = MlbCertificateStore(certificate_store, self.client)

    def test_store(self):
        """
        When PEM objects are stored in the directory store, marathon-lb should
        be told to send the USR1 signal, and the certificate should be stored.
        """
        d = self.mlb_store.store('example.com', EXAMPLE_PEM_OBJECTS)

        # Check that the one request succeeds
        self.assertThat(d, succeeded(MatchesListwise([
            MatchesStructure(code=Equals(200))
        ])))

        # Check that marathon-lb was signalled
        self.assertThat(self.fake_marathon_lb.check_signalled_usr1(),
                        Equals(True))

        # Check that the certificate was stored
        self.assertThat(self.mlb_store.get('example.com'),
                        succeeded(Equals(EXAMPLE_PEM_OBJECTS)))
        self.assertThat(self.mlb_store.as_dict(),
                        succeeded(
                            Equals({'example.com': EXAMPLE_PEM_OBJECTS})))

    def test_store_unexpected_response(self):
        """
        When the wrapped certificate store returns something other than None,
        an error should be raised as this is unexpected.
        """
        class BrokenCertificateStore(object):
            def store(self, server_name, pem_objects):
                # Return something other than None
                return succeed('foo')

        mlb_store = MlbCertificateStore(BrokenCertificateStore(), self.client)

        d = mlb_store.store('example.com', EXAMPLE_PEM_OBJECTS)

        self.assertThat(d, failed(WithErrorTypeAndMessage(
            RuntimeError,
            "Wrapped certificate store returned something non-None. Don't "
            "know what to do with 'foo'.")))
