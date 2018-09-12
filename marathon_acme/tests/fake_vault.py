import uuid

from klein import Klein

from treq.testing import StubTreq

from marathon_acme.clients import get_single_header
from marathon_acme.server import write_request_json
from marathon_acme.tests.helpers import read_request_json


class FakeVault(object):
    """
    A very simple fake Vault with only the ability to store key/value v2 data
    and metadata.
    """
    def __init__(self):
        self.token = str(uuid.uuid4())
        self._kv_data = {}

    def get_kv_data(self, path):
        """
        Read KV data at the given path. Returns the data and metadata.
        """
        return self._kv_data.get(path)

    def set_kv_data(self, path, data):
        """
        Create or update KV data at the given path. Returns the metadata for
        the newly stored data.
        """
        existing_data = self.get_kv_data(path)
        if existing_data is not None:
            # If there is existing data, bump the version.
            existing_version = existing_data['metadata']['version']
            value = self._kv_v2(data, existing_version + 1)
        else:
            value = self._kv_v2(data)

        self._kv_data[path] = value
        return value['metadata']

    def _kv_v2(self, data, version=1):
        # NOTE: This ignores a bunch of response fields that are poorly
        # documented and that we don't care about anyway. It also uses some
        # hardcoded metadata because we don't care about that either, but
        # probably want it to at least be present.
        return {
            'data': data,
            'metadata': {
                'created_time': '2018-05-29T10:24:30.181952826Z',
                'deletion_time': '',
                'destroyed': False,
                'version': version
            }
        }


class FakeVaultAPI(object):
    """
    A very simple fake Vault API. Only supports the key/value v2 read and
    create/update APIs. Only supports a fixed mount path (``secret``).
    """
    app = Klein()

    def __init__(self, vault):
        self._vault = vault
        self.client = StubTreq(self.app.resource())

    @app.route('/v1/secret/data/', methods=['GET'], branch=True)
    def read_secret(self, request):
        if not self._check_token(request):
            return

        path = self._get_path(request)

        data = self._vault.get_kv_data(path)
        if data is not None:
            self._reply(request, data)
        else:
            self._reply_error(request, 404, [])

    @app.route('/v1/secret/data/', methods=['POST', 'PUT'], branch=True)
    def create_update_secret(self, request):
        if not self._check_token(request):
            return

        path = self._get_path(request)
        request_json = read_request_json(request)

        if not self._check_cas(path, request_json):
            self._reply_error(request, 400, [
                'check-and-set parameter did not match the current version'])
            return

        metadata = self._vault.set_kv_data(path, request_json['data'])

        self._reply(request, metadata)

    def _get_path(self, request, prefix='/v1/secret/data/'):
        # This is a workaround to get the full request path. Klein gives us
        # only the next path segment as the extra parameter to routes when
        # using variable paths, even if branch=True. Read the remaining path
        # directly from the request
        path = request.path.decode('ascii')
        return path[len(prefix):]

    def _reply(self, request, data):
        request.setResponseCode(200)
        write_request_json(request, {'data': data})

    def _reply_error(self, request, code, errors):
        request.setResponseCode(code)
        write_request_json(request, {'errors': errors})

    def _check_token(self, request):
        token = get_single_header(request.requestHeaders, 'X-Vault-Token')

        if not token:
            self._reply_error(request, 400, ['missing client token'])
            return False

        if token != self._vault.token:
            self._reply_error(request, 403, ['permission denied'])
            return False

        return True

    def _check_cas(self, path, request_json):
        cas = request_json.get('options', {}).get('cas')
        if cas is None:
            return True

        existing_data = self._vault.get_kv_data(path)
        if existing_data is None:
            # cas = 0 means the data must not exist
            return cas == 0

        return existing_data['metadata']['version'] == cas
