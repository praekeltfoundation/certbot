import binascii
import json

from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes

import pem

from twisted.internet.defer import Deferred
from twisted.logger import Logger

from txacme.interfaces import ICertificateStore

from zope.interface import implementer

from marathon_acme.clients.vault import CasError


def sort_pem_objects(pem_objects):
    """
    Given a list of pem objects, sort the objects into the private key, leaf
    certificate, and list of CA certificates in the trust chain. This function
    assumes that the list of pem objects will contain exactly one private key
    and exactly one leaf certificate and that only key and certificate type
    objects are provided.
    """
    keys, certs, ca_certs = [], [], []
    for pem_object in pem_objects:
        if isinstance(pem_object, pem.Key):
            keys.append(pem_object)
        else:
            # This assumes all pem objects provided are either of type pem.Key
            # or pem.Certificate. Technically, there are CSR and CRL types, but
            # we should never be passed those.
            if _is_ca(pem_object):
                ca_certs.append(pem_object)
            else:
                certs.append(pem_object)

    [key], [cert] = keys, certs
    return key, cert, ca_certs


def _is_ca(cert_pem_object):
    cert = x509.load_pem_x509_certificate(
        cert_pem_object.as_bytes(), default_backend())

    basic_constraints = (
        cert.extensions.get_extension_for_class(x509.BasicConstraints).value)
    return basic_constraints.ca


def _cert_data_from_pem_objects(key, cert, ca_certs):
    privkey = key.as_text()
    cert = cert.as_text()
    chain = ''.join([c.as_text() for c in ca_certs])
    return {'privkey': privkey, 'cert': cert, 'chain': chain}


def _cert_data_to_pem_objects(cert_data):
    """
    Given a non-None response from the Vault key/value store, convert the
    key/values into a list of PEM objects.
    """
    pem_objects = []
    for key in ['privkey', 'cert', 'chain']:
        pem_objects.extend(pem.parse(cert_data[key].encode('utf-8')))

    return pem_objects


def _live_value(cert_pem_object, version):
    # https://cryptography.io/en/stable/x509/reference/#cryptography.x509.load_pem_x509_certificate
    cert = x509.load_pem_x509_certificate(
        cert_pem_object.as_bytes(), default_backend())

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

    log = Logger()

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

        def get_data(response):
            return response['data']['data']

        d.addCallback(handle_not_found)
        d.addCallback(get_data)
        d.addCallback(_cert_data_to_pem_objects)
        return d

    def store(self, server_name, pem_objects):
        """
        The procedure for storing certificates is as follows:

        1.  The new certificate is stored without a CAS parameter. This assumes
            that the certificate we are storing is always up-to-date.
            1.1 From Vault's response, take the new certificate version:
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
        key, cert, ca_certs = sort_pem_objects(pem_objects)
        data = _cert_data_from_pem_objects(key, cert, ca_certs)

        self.log.debug("Storing certificate '{server_name}'...",
                       server_name=server_name)

        d = self._client.create_or_update_kv2(
            'certificates/' + server_name, data, mount_path=self._mount_path)

        def live_value(cert_response):
            cert_version = cert_response['data']['version']
            return _live_value(cert, cert_version)

        d.addCallback(live_value)

        # Then update the live mapping
        return d.addCallback(self._update_live, server_name)

    def _update_live(self, new_live_value, server_name):
        d = self._read_live_data_and_version()

        # When we fail to update the live mapping due to a Check-And-Set
        # mismatch, try again from scratch
        def retry_on_cas_error(failure):
            failure.trap(CasError)
            self.log.warn('Check-And-Set mismatch while updating live '
                          'mapping. Retrying...')
            return self._update_live(new_live_value, server_name)

        def update(live_data_and_version):
            live, version = live_data_and_version

            # Get the existing version of the cert in the live mapping
            existing_live_value = live.get(server_name)
            if existing_live_value is not None:
                existing_cert_version = (
                    json.loads(existing_live_value)['version'])
            else:
                self.log.debug(
                    "Certificate '{server_name}' not previously stored",
                    server_name=server_name)
                existing_cert_version = 0

            # If the existing cert version is lower than what we want to update
            # it to, then try update it
            new_cert_version = new_live_value['version']
            if existing_cert_version < new_cert_version:
                self.log.debug(
                    "Updating live mapping for certificate '{server_name}' "
                    'from version {v1} to {v2}', server_name=server_name,
                    v1=existing_cert_version, v2=new_cert_version)
                live[server_name] = json.dumps(new_live_value)

                d = self._client.create_or_update_kv2(
                    'live', live, cas=version, mount_path=self._mount_path)
                d.addErrback(retry_on_cas_error)
                return d
            else:
                # Else assume somebody else updated the live mapping and stop
                self.log.warn(
                    'Existing certificate version ({v1}) >= version we are '
                    'trying to store ({v2}). Not updating...',
                    v1=existing_cert_version, v2=new_cert_version)
                return

        d.addCallback(update)
        return d

    def _read_live_data_and_version(self):
        d = self._client.read_kv2('live', mount_path=self._mount_path)

        def get_data_and_version(response):
            if response is not None:
                data = response['data']['data']
                version = response['data']['metadata']['version']
            else:
                data = {}
                version = 0

            self.log.debug('Read live mapping version {v} with {len_live} '
                           'entries.', v=version, len_live=len(data))

            return data, version

        return d.addCallback(get_data_and_version)

    def as_dict(self):
        d = self._read_live_data_and_version()
        d.addCallback(self._read_all_certs)
        return d

    def _read_all_certs(self, live_data_and_version):
        live, _ = live_data_and_version
        certs = {}

        def read_cert(_result, name):
            self.log.debug("Reading certificate '{name}'...", name=name)
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
