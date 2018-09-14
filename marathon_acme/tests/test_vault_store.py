import binascii
import json
import os

import pem

import pytest

from testtools.assertions import assert_that
from testtools.matchers import (
    AfterPreprocessing as After, Equals, IsInstance, MatchesDict)
from testtools.twistedsupport import failed, succeeded

from marathon_acme.clients import VaultClient
from marathon_acme.tests.fake_vault import FakeVault, FakeVaultAPI
from marathon_acme.tests.matchers import WithErrorTypeAndMessage
from marathon_acme.vault_store import VaultKvCertificateStore


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


def key_text(pem_objects):
    keys = filter(lambda p: isinstance(p, pem.Key), pem_objects)
    [key] = list(keys)
    return key.as_text()


def cert_chain_text(pem_objects):
    certs = filter(lambda p: isinstance(p, pem.Certificate), pem_objects)
    return ''.join([p.as_text() for p in certs])


@pytest.fixture(scope='module')
def bundle1():
    return bundle_pem_objects(BUNDLE1_FILENAME)


@pytest.fixture(scope='module')
def bundle2():
    return bundle_pem_objects(BUNDLE2_FILENAME)


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
        self.vault.set_kv_data('certificates/bundle1', {
            'domains': 'marathon-acme.example.org',
            'key': key_text(bundle1),
            'cert_chain': cert_chain_text(bundle1)
        })

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
        assert cert_data['data'] == {
            'domains': 'bundle1',
            'key': key_text(bundle1),
            'cert_chain': cert_chain_text(bundle1)
        }

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
        self.vault.set_kv_data('certificates/bundle', {
            'domains': 'bundle',
            'key': key_text(bundle1),
            'cert_chain': cert_chain_text(bundle1)
        })
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
        self.vault.set_kv_data('certificates/bundle1', {
            'domains': 'marathon-acme.example.org',
            'key': key_text(bundle1),
            'cert_chain': cert_chain_text(bundle1)
        })
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
