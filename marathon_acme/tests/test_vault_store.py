import binascii
import json
import os

from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.x509.oid import NameOID

import pem

import pytest

from testtools.assertions import assert_that
from testtools.matchers import (
    AfterPreprocessing as After, Equals, Is, IsInstance, MatchesDict)
from testtools.twistedsupport import failed, succeeded

from marathon_acme.clients import VaultClient
from marathon_acme.tests.fake_vault import FakeVault, FakeVaultAPI
from marathon_acme.tests.matchers import WithErrorTypeAndMessage
from marathon_acme.vault_store import VaultKvCertificateStore, sort_pem_objects


FIXTURES = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'fixtures')
BUNDLE1_FILENAME = 'marathon-acme.example.org.pem'
BUNDLE1_FINGERPRINT = (
    'BA09FBE7D87BF98800F3EA73F8A47271104C5036140E267ECF4BCA64DF6EE2A2')
BUNDLE1_DNS_NAMES = ['marathon-acme.example.org']
BUNDLE2_FILENAME = 'mc2.example.org.pem'
BUNDLE2_FINGERPRINT = (
    'C2220107708F22E74CAB2A168DFC6082D44B8DCD33EDB01659C605D4F5FE9519')
BUNDLE2_DNS_NAMES = ['mc2.example.org']


def bundle_pem_objects(filename):
    with open(os.path.join(FIXTURES, filename), 'rb') as bundle:
        return pem.parse(bundle.read())


@pytest.fixture(scope='module')
def bundle1():
    return bundle_pem_objects(BUNDLE1_FILENAME)


@pytest.fixture(scope='module')
def bundle2():
    return bundle_pem_objects(BUNDLE2_FILENAME)


def test_sort_pem_objects(bundle1):
    """
    ``sort_pem_objects`` can divide up a list of pem objects into the private
    key, leaf certificate, and a list of CA certificates in the chain of trust.
    """
    key, cert, ca_certs = sort_pem_objects(bundle1)

    # Check the private key
    assert isinstance(key, pem.Key)

    # Check the certificate
    assert isinstance(cert, pem.Certificate)

    x509_cert = x509.load_pem_x509_certificate(
        cert.as_bytes(), default_backend())
    basic_constraints = x509_cert.extensions.get_extension_for_class(
        x509.BasicConstraints).value
    assert not basic_constraints.ca
    # https://cryptography.io/en/latest/x509/reference/#cryptography.x509.Name.get_attributes_for_oid
    [common_name] = (
        x509_cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME))
    assert common_name.value == BUNDLE1_DNS_NAMES[0]

    # Check the CA certificates
    assert len(ca_certs) == 1
    x509_ca_cert = x509.load_pem_x509_certificate(
        ca_certs[0].as_bytes(), default_backend())
    basic_constraints = x509_ca_cert.extensions.get_extension_for_class(
        x509.BasicConstraints).value
    assert basic_constraints.ca
    [common_name] = (
        x509_ca_cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME))
    assert common_name.value == 'Test Certificate Authority'


def hex_str_to_bytes(hex_str):
    return binascii.unhexlify(hex_str.encode('utf-8'))


def EqualsFingerprint(fingerprint):
    # Account for uppercase/lowercase and do a bytes-wise comparison
    return After(hex_str_to_bytes, Equals(hex_str_to_bytes(fingerprint)))


def EqualsLiveValue(version, fingerprint, dns_names):
    return After(json.loads, MatchesDict({
        'version': Equals(version),
        'fingerprint': EqualsFingerprint(fingerprint),
        'dns_names': Equals(dns_names)
    }))


def live_value(version, fingerprint, dns_names):
    return json.dumps({
        'version': version,
        'fingerprint': fingerprint,
        'dns_names': dns_names
    })


def certificate_value(pem_objects):
    key, cert, ca_chain = sort_pem_objects(pem_objects)
    return {
        'privkey': key.as_text(),
        'cert': cert.as_text(),
        'chain': ''.join([c.as_text() for c in ca_chain])
    }


class TestVaultKvCertificateStore(object):
    def setup_method(self):
        self.vault = FakeVault()
        self.vault_api = FakeVaultAPI(self.vault)

        self.client = self.vault_api.client
        vault_client = VaultClient(
            'http://localhost:8200', self.vault.token, client=self.client)

        self.store = VaultKvCertificateStore(vault_client, 'secret')

    def test_get(self, bundle1):
        """
        When a certificate is fetched from the store and it exists, the
        certificate is returned as a list of PEM objects.
        """
        self.vault.set_kv_data(
            'certificates/bundle1', certificate_value(bundle1))

        d = self.store.get('bundle1')
        assert_that(d, succeeded(Equals(bundle1)))

    def test_get_not_exists(self):
        """
        When a certificate is fetched from the store but it does not exist, a
        KeyError is raised as specified by the txacme interface.
        """
        d = self.store.get('www.p16n.org')
        assert_that(d, failed(WithErrorTypeAndMessage(
            KeyError, repr('www.p16n.org')
        )))

    def test_store_create_live(self, bundle1):
        """
        When a certificate is stored in the store, the certificate is saved and
        the live data is created when it does not exist.
        """
        d = self.store.store('bundle1', bundle1)
        # We return the final kv write response from Vault, but txacme doesn't
        # care what the result of the deferred is
        assert_that(d, succeeded(IsInstance(dict)))

        cert_data = self.vault.get_kv_data('certificates/bundle1')
        assert cert_data['data'] == certificate_value(bundle1)

        live_data = self.vault.get_kv_data('live')
        assert_that(live_data['data'], MatchesDict({
            'bundle1': EqualsLiveValue(cert_data['metadata']['version'],
                                       BUNDLE1_FINGERPRINT, BUNDLE1_DNS_NAMES)
        }))
        assert live_data['metadata']['version'] == 1

    def test_store_update_live(self, bundle1):
        """
        When a certificate is stored in the store, the certificate is saved and
        the live data is updated when it does exist.
        """
        self.vault.set_kv_data('live', {'p16n.org': 'dummy_data'})

        d = self.store.store('bundle1', bundle1)
        # We return the final kv write response from Vault, but txacme doesn't
        # care what the result of the deferred is
        assert_that(d, succeeded(IsInstance(dict)))

        cert_data = self.vault.get_kv_data('certificates/bundle1')
        live_data = self.vault.get_kv_data('live')
        assert_that(live_data['data'], MatchesDict({
            'p16n.org': Equals('dummy_data'),
            'bundle1': EqualsLiveValue(cert_data['metadata']['version'],
                                       BUNDLE1_FINGERPRINT, BUNDLE1_DNS_NAMES)
        }))
        assert live_data['metadata']['version'] == 2

    def test_store_update_existing(self, bundle1, bundle2):
        """
        When a certificate is stored in the store, and a certificate already
        exists for the server name, the certificate and live mapping are
        updated.
        """
        self.vault.set_kv_data(
            'certificates/bundle', certificate_value(bundle1))
        self.vault.set_kv_data('live', {
            'bundle': json.dumps({
                'version': 1,
                'fingerprint': BUNDLE1_FINGERPRINT,
                'dns_names': BUNDLE1_DNS_NAMES
            })
        })

        d = self.store.store('bundle', bundle2)
        # We return the final kv write response from Vault, but txacme doesn't
        # care what the result of the deferred is
        assert_that(d, succeeded(IsInstance(dict)))

        cert_data = self.vault.get_kv_data('certificates/bundle')
        live_data = self.vault.get_kv_data('live')
        assert_that(live_data['data'], MatchesDict({
            'bundle': EqualsLiveValue(cert_data['metadata']['version'],
                                      BUNDLE2_FINGERPRINT, BUNDLE2_DNS_NAMES)
        }))
        assert live_data['metadata']['version'] == 2

    def test_store_update_existing_live_updated(self, bundle1, bundle2):
        """
        When a certificate is stored in the store, and a certificate already
        exists for the server name, the certificate should be updated, and if
        another writer updates the live mapping for that certificate, the store
        operation should still succeed.
        """
        self.vault.set_kv_data(
            'certificates/bundle', certificate_value(bundle1))
        self.vault.set_kv_data('live', {
            'bundle': live_value(1, BUNDLE1_FINGERPRINT, BUNDLE1_DNS_NAMES)
        })

        writes = [0]

        def pre_create_update():
            # The first write to Vault should be storing the certificate. We
            # want to intercept the write to the live mapping, which should be
            # the second write.
            if writes == [1]:
                self.vault.set_kv_data('live', {
                    'bundle':
                        live_value(2, BUNDLE2_FINGERPRINT, BUNDLE2_DNS_NAMES)
                })
            writes[0] += 1
        self.vault_api.set_pre_create_update(pre_create_update)

        d = self.store.store('bundle', bundle2)
        # We return a nothing if we skip the final live mapping update, but
        # txacme doesn't care what the result of the deferred is
        assert_that(d, succeeded(Is(None)))

        # There should've been 2 writes:
        # 1. Storing the certificate
        # 2. The first attempt at updating the live mapping (CAS mismatch)
        # - A third write should never happen since the live mapping is already
        #   up to date.
        assert_that(writes, Equals([2]))

        cert_data = self.vault.get_kv_data('certificates/bundle')
        live_data = self.vault.get_kv_data('live')
        assert_that(live_data['data'], MatchesDict({
            'bundle': EqualsLiveValue(cert_data['metadata']['version'],
                                      BUNDLE2_FINGERPRINT, BUNDLE2_DNS_NAMES)
        }))
        assert live_data['metadata']['version'] == 2

    def test_store_update_live_cas_retry(self, bundle1):
        """
        When a certificate is stored in the store, and the live map is updated
        between the read and the write of the live mapping, the live map
        update is attempted again.
        """
        writes = [0]

        def pre_create_update():
            # The first write to Vault should be storing the certificate. We
            # want to intercept the write to the live mapping, which should be
            # the second write.
            if writes == [1]:
                self.vault.set_kv_data('live', {'p16n.org': 'dummy_data'})
            writes[0] += 1

        self.vault_api.set_pre_create_update(pre_create_update)

        d = self.store.store('bundle1', bundle1)
        # We return the final kv write response from Vault, but txacme doesn't
        # care what the result of the deferred is
        assert_that(d, succeeded(IsInstance(dict)))

        # There should've been 3 writes:
        # 1. Storing the certificate
        # 2. The first attempt at updating the live mapping (CAS mismatch)
        # 3. The second attempt at updating the live mapping (success)
        assert_that(writes, Equals([3]))

        cert_data = self.vault.get_kv_data('certificates/bundle1')
        live_data = self.vault.get_kv_data('live')
        assert_that(live_data['data'], MatchesDict({
            'p16n.org': Equals('dummy_data'),
            'bundle1': EqualsLiveValue(cert_data['metadata']['version'],
                                       BUNDLE1_FINGERPRINT, BUNDLE1_DNS_NAMES)
        }))
        assert live_data['metadata']['version'] == 2

    def test_as_dict(self, bundle1):
        """
        When the certificates are fetched as a dict, all certificates are
        returned in a dict.
        """
        self.vault.set_kv_data(
            'certificates/bundle1', certificate_value(bundle1))
        self.vault.set_kv_data('live', {'bundle1': 'FINGERPRINT'})

        d = self.store.as_dict()
        assert_that(d, succeeded(Equals({'bundle1': bundle1})))

    def test_as_dict_empty(self):
        """
        When the certificates are fetched as a dict, and the live mapping does
        not exist, an empty dict is returned.
        """
        d = self.store.as_dict()
        assert_that(d, succeeded(Equals({})))
