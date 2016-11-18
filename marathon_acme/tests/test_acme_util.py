from datetime import datetime, timedelta

import pem
import pytest
from acme.jose import JWKRSA
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from testtools.assertions import assert_that
from testtools.matchers import (
    Equals, HasLength, IsInstance, MatchesListwise, MatchesStructure)
from testtools.twistedsupport import succeeded, failed
from twisted.internet.defer import succeed
from twisted.python.filepath import FilePath
from txacme.testing import MemoryStore
from txacme.util import generate_private_key

from marathon_acme.acme_util import (
    generate_wildcard_pem_bytes, maybe_key, MlbCertificateStore)
from marathon_acme.clients import MarathonLbClient
from marathon_acme.tests.fake_marathon import FakeMarathonLb
from marathon_acme.tests.matchers import (
    matches_time_or_just_before, WithErrorTypeAndMessage)


class TestMaybeKey(object):
    @pytest.fixture
    def pem_path(self, tmpdir):
        return FilePath(str(tmpdir))

    def test_key_exists(self, pem_path):
        """
        When we get the client key and the key file already exists, the file
        should be read and the existing key returned.
        """
        raw_key = generate_private_key(u'rsa')
        expected_key = JWKRSA(key=raw_key)

        pem_file = pem_path.child(u'client.key')
        pem_file.setContent(raw_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption()
        ))

        actual_key = maybe_key(pem_path)
        assert_that(actual_key, Equals(expected_key))

    def test_key_not_exists(self, pem_path):
        """
        When we get the client key and no key file exists, a new key should be
        generated and the key should be saved in a key file.
        """
        key = maybe_key(pem_path)

        pem_file = pem_path.child(u'client.key')
        assert_that(pem_file.exists(), Equals(True))

        file_key = serialization.load_pem_private_key(
            pem_file.getContent(),
            password=None,
            backend=default_backend()
        )
        file_key = JWKRSA(key=file_key)

        assert_that(key, Equals(file_key))


def test_generate_wildcard_pem_bytes():
    """
    When we generate a self-signed wildcard certificate's PEM data, that data
    should be deserializable and the deserilized certificate should have the
    expected parameters.
    """
    pem_bytes = generate_wildcard_pem_bytes()

    # Parse the concatenated bytes into a list of object
    pem_objects = pem.parse(pem_bytes)

    assert_that(pem_objects, HasLength(2))

    # Deserialize the private key and assert that it is the right type (the
    # other details we trust txacme with)
    key = serialization.load_pem_private_key(
        pem_objects[0].as_bytes(),
        password=None,
        backend=default_backend()
    )
    assert_that(key, IsInstance(rsa.RSAPrivateKey))

    # Deserialize the certificate and validate all the options we set
    cert = x509.load_pem_x509_certificate(
        pem_objects[1].as_bytes(), backend=default_backend()
    )
    expected_before = datetime.today() - timedelta(days=1)
    expected_after = datetime.now() + timedelta(days=3650)
    assert_that(cert, MatchesStructure(
        issuer=MatchesListwise([
            MatchesStructure(value=Equals(u'*'))
        ]),
        subject=MatchesListwise([
            MatchesStructure(value=Equals(u'*'))
        ]),
        not_valid_before=matches_time_or_just_before(expected_before),
        not_valid_after=matches_time_or_just_before(expected_after),
        signature_hash_algorithm=IsInstance(hashes.SHA256)
    ))
    assert_that(cert.public_key().public_numbers(), Equals(
                key.public_key().public_numbers()))


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


class TestMlbCertificateStore(object):
    def setup_method(self):
        self.fake_marathon_lb = FakeMarathonLb()
        self.client = MarathonLbClient(
            ['http://lb1:9090'], client=self.fake_marathon_lb.client)

        certificate_store = MemoryStore()
        self.mlb_store = MlbCertificateStore(certificate_store, self.client)

    def test_store(self):
        """
        When PEM objects are stored in the directory store, marathon-lb should
        be told to send the USR1 signal, and the certificate should be stored.
        """
        d = self.mlb_store.store('example.com', EXAMPLE_PEM_OBJECTS)

        # Check that the one request succeeds
        assert_that(d, succeeded(MatchesListwise([
            MatchesStructure(code=Equals(200))
        ])))

        # Check that marathon-lb was signalled
        assert_that(self.fake_marathon_lb.check_signalled_usr1(), Equals(True))

        # Check that the certificate was stored
        assert_that(self.mlb_store.get('example.com'),
                    succeeded(Equals(EXAMPLE_PEM_OBJECTS)))
        assert_that(self.mlb_store.as_dict(),
                    succeeded(Equals({'example.com': EXAMPLE_PEM_OBJECTS})))

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

        assert_that(d, failed(WithErrorTypeAndMessage(
            RuntimeError,
            "Wrapped certificate store returned something non-None. Don't "
            "know what to do with 'foo'.")))
