import binascii
import json

from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes

import pem

from twisted.internet.defer import Deferred

from txacme.interfaces import ICertificateStore

from zope.interface import implementer

from marathon_acme.clients.vault import CasError


def to_pem_objects(kv2_response):
    """
    Given a non-None response from the Vault key/value store, convert the
    key/values into a list of PEM objects.
    """
    data = kv2_response['data']['data']
    key = pem.parse(data['key'].encode('utf-8'))
    cert_chain = pem.parse(data['cert_chain'].encode('utf-8'))

    return key + cert_chain


# TODO: Read domains from certificates
def from_pem_objects(server_name, pem_objects):
    """
    Given a server name and list of PEM objects, create the key/value data that
    will be stored in Vault.
    """
    [key] = [p.as_text() for p in pem_objects if isinstance(p, pem.Key)]
    # The pem library adds newlines to the ends of PEMs, so we just concat
    cert_chain = ''.join(
        [p.as_text() for p in pem_objects if isinstance(p, pem.Certificate)]
    )

    return {
        'domains': server_name,
        'key': key,
        'cert_chain': cert_chain
    }


def _live_value(pem_objects, version):
    pem_data = b'\n'.join([p.as_bytes() for p in pem_objects])
    # https://cryptography.io/en/stable/x509/reference/#cryptography.x509.load_pem_x509_certificate
    cert = x509.load_pem_x509_certificate(pem_data, default_backend())

    # https://cryptography.io/en/stable/x509/reference/#cryptography.x509.Certificate.fingerprint
    fingerprint = cert.fingerprint(hashes.SHA256())
    fingerprint = binascii.hexlify(fingerprint).decode('utf-8')

    # https://cryptography.io/en/stable/x509/reference/#cryptography.x509.Extensions.get_extension_for_class
    # https://cryptography.io/en/stable/x509/reference/#cryptography.x509.SubjectAlternativeName.get_values_for_type
    sans = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
    dns_names = sans.value.get_values_for_type(x509.DNSName)

    return {
        'version': version,
        'fingerprint': fingerprint,
        'dns_names': dns_names
    }


@implementer(ICertificateStore)
class VaultKvCertificateStore(object):
    """
    A ``txacme.interfaces.ICertificatStore`` implementation that stores
    certificates in a Vault key/value version 2 secret engine.
    """

    def __init__(self, client, mount_path):
        self._client = client
        self._mount_path = mount_path

    def get(self, server_name):
        d = self._client.read_kv2(
            'certificates/' + server_name, mount_path=self._mount_path)

        def handle_not_found(response):
            if response is None:
                raise KeyError(server_name)
            return response

        d.addCallback(handle_not_found)
        d.addCallback(to_pem_objects)
        return d

    def store(self, server_name, pem_objects):
        """
        The procedure for storing certificates is as follows:

        1.  The new certificate is stored without a CAS parameter. This assumes
            that the certificate we are storing is always up-to-date.
            1.1 From Vault’s response, take the new certificate version:
                ``v_cert_new``.
        2. The live map is read.
            2.1 The version of the live map is kept: ``v_live``
            2.2 Check if the certificate version in the live map is
                ``>= v_cert_new``.
                2.2.1 If so, assume somebody else updated the live map. Finish.
                2.2.2 If not, continue.
        3. Update the live map and write it with ``cas=v_live``.
            3.1 If the CAS fails, go back to step 2.
        """
        # First store the certificate
        data = from_pem_objects(server_name, pem_objects)
        d = self._client.create_or_update_kv2(
            'certificates/' + server_name, data, mount_path=self._mount_path)

        def live_value(cert_response):
            cert_version = cert_response['data']['version']
            return _live_value(pem_objects, cert_version)

        d.addCallback(live_value)

        # Then update the live mapping
        return d.addCallback(self._update_live, server_name)

    def _update_live(self, new_live_value, server_name):
        d = self._read_live()

        # When we fail to update the live mapping due to a Check-And-Set
        # mismatch, try again from scratch
        def retry_on_cas_error(failure):
            failure.trap(CasError)
            return self._update_live(new_live_value, server_name)

        def update(read_response):
            # Get the live mapping data and its version
            if read_response is not None:
                data = read_response['data']['data']
                version = read_response['data']['metadata']['version']
            else:
                data = {}
                version = 0

            # Get the existing version of the cert in the live mapping
            existing_live_value = data.get(server_name)
            if existing_live_value is not None:
                existing_cert_version = (
                    json.loads(existing_live_value)['version'])
            else:
                existing_cert_version = 0

            # If the existing cert version is lower than what we want to update
            # it to, then try update it
            if existing_cert_version < new_live_value['version']:
                data[server_name] = json.dumps(new_live_value)

                d = self._client.create_or_update_kv2(
                    'live', data, cas=version, mount_path=self._mount_path)
                d.addErrback(retry_on_cas_error)
                return d
            else:
                # Else assume somebody else updated the live mapping and stop
                return

        d.addCallback(update)
        return d

    def _read_live(self):
        return self._client.read_kv2('live', mount_path=self._mount_path)

    def as_dict(self):
        d = self._read_live()
        d.addCallback(self._read_all_certs)
        return d

    def _read_all_certs(self, live_response):
        if live_response is None:
            return {}

        certs = {}
        live = live_response['data']['data']

        def read_cert(_result, name):
            return self.get(name)

        def collect_cert(pem_objects, name):
            certs[name] = pem_objects

        # Chain some deferreds to execute in series so we don't DoS Vault
        d = Deferred()
        for name, value in live.items():
            d.addCallback(read_cert, name)
            # TODO: Try update live mapping on version mismatchs
            # TODO: Warn on certificate fingerprint, or dns_names mismatch
            d.addCallback(collect_cert, name)

        d.addCallback(lambda _result: certs)
        # First deferred does nothing. Callback it to get the chain going.
        d.callback(None)
        return d
