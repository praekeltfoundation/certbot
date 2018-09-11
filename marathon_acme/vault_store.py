import pem

from twisted.internet.defer import Deferred

from txacme.interfaces import ICertificateStore

from zope.interface import implementer


def to_pem_objects(kv2_response):
    """
    Given a non-None response from the Vault key/value store, convert the
    key/values into a list of PEM objects.
    """
    data = kv2_response['data']['data']
    key = pem.parse(data['key'].encode('utf-8'))
    cert_chain = pem.parse(data['cert_chain'].encode('utf-8'))

    return key + cert_chain


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
        # First store the certificate
        data = from_pem_objects(server_name, pem_objects)
        d = self._client.create_or_update_kv2(
            'certificates/' + server_name, data, mount_path=self._mount_path)

        # Then update the live mapping
        # TODO: Store the actual fingerprint
        return d.addCallback(self._update_live, server_name, 'FINGERPRINT')

    def _update_live(self, _result, server_name, fingerprint):
        d = self._read_live()

        def update(read_response):
            if read_response is not None:
                data = read_response['data']['data']
                version = read_response['data']['metadata']['version']
            else:
                data = {}
                version = 0

            data[server_name] = fingerprint

            # TODO: Retry on version/cas error
            return self._client.create_or_update_kv2(
                'live', data, cas=version, mount_path=self._mount_path)

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
        for name, fingerprint in live.items():
            d.addCallback(read_cert, name)
            # TODO: Warn on certificate fingerprint mismatch
            d.addCallback(collect_cert, name)

        d.addCallback(lambda _result: certs)
        # First deferred does nothing. Callback it to get the chain going.
        d.callback(None)
        return d
