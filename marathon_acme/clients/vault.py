import json
import os

from requests.exceptions import RequestException

from treq.client import HTTPClient as treq_HTTPClient

from twisted.internet.ssl import (
    Certificate, PrivateCertificate, optionsForClientTLS)
from twisted.python.filepath import FilePath
from twisted.web.client import Agent
from twisted.web.http import BAD_REQUEST, NOT_FOUND
from twisted.web.iweb import IPolicyForHTTPS

from zope.interface import implementer

from marathon_acme.clients._base import (
    HTTPClient, default_reactor, get_single_header)


class VaultError(RequestException):
    """
    Exception type for Vault response errors. The ``errors`` parameter contains
    a list of error messages. Roughly copies hvac's ``VaultError`` type:
    https://github.com/hvac/hvac/blob/v0.6.4/hvac/exceptions.py#L1-L8
    """
    def __init__(self, message=None, errors=None, response=None):
        if errors:
            message = ', '.join(errors)

        self.errors = errors

        super(VaultError, self).__init__(message, response=response)


class CasError(VaultError):
    """Exception type to indicate a Check-And-Set mismatch error. """


class VaultClient(HTTPClient):
    """
    A very simple Vault client that can read and write to paths.
    """

    def __init__(self, url, token, *args, **kwargs):
        """
        :param url: the URL for Vault
        :param token: the Vault auth token
        """
        super(VaultClient, self).__init__(*args, url=url, **kwargs)
        self._token = token

    @classmethod
    def from_environ(cls, reactor=None, env=os.environ):
        # Support a limited number of the available config options:
        # https://github.com/hashicorp/vault/blob/v0.11.2/api/client.go#L28-L40
        address = _get_environ_str(env, 'VAULT_ADDR', 'https://127.0.0.1:8200')
        # This seems to be what the Vault CLI defaults to
        token = _get_environ_str(env, 'VAULT_TOKEN', 'TEST')

        insecure = _get_environ_bool(env, 'VAULT_SKIP_VERIFY')
        ca_cert = _get_environ_str(env, 'VAULT_CACERT')
        tls_server_name = _get_environ_str(env, 'VAULT_TLS_SERVER_NAME')
        client_cert = _get_environ_str(env, 'VAULT_CLIENT_CERT')
        client_key = _get_environ_str(env, 'VAULT_CLIENT_KEY')
        agent = _create_agent(
            reactor, insecure, ca_cert, tls_server_name, client_cert,
            client_key
        )

        return VaultClient(address, token, client=treq_HTTPClient(agent))

    def request(self, method, path, *args, **kwargs):
        headers = kwargs.pop('headers', {})
        headers['X-Vault-Token'] = self._token
        return super(VaultClient, self).request(
            method, *args, path=path, headers=headers, **kwargs)

    def _handle_response(self, response, check_cas=False):
        if 400 <= response.code < 600:
            return self._handle_error(response, check_cas)

        return response.json()

    def _handle_error(self, response, check_cas):
        # Decode as utf-8. treq's text() method uses ISO-8859-1 which is
        # correct for random text over HTTP, but not for JSON. Cross fingers
        # that we don't receive anything non-utf-8.
        d = response.text(encoding='utf-8')

        def to_error(text):
            # This logic is inspired by hvac as well:
            # https://github.com/hvac/hvac/blob/v0.6.4/hvac/adapters.py#L227-L233
            exc_type = VaultError
            errors = None
            if get_single_header(
                    response.headers, 'Content-Type') == 'application/json':
                errors = json.loads(text).get('errors')

            # Special case for 404s without extra errors: return None (hvac
            # doesn't do this)
            if response.code == NOT_FOUND and errors == []:
                return None

            # Special case for CAS mismatch errors: raise a CasError
            # Unfortunately, Vault doesn't make it easy to differentiate
            # between CAS errors and other errors so we have to check a few
            # things.
            if (check_cas and response.code == BAD_REQUEST and
                    errors and 'check-and-set' in errors[0]):
                exc_type = CasError

            # hvac returns more specific errors that are subclasses of its
            # VaultError. For simplicity we just return fewer error types.
            raise exc_type(text, errors=errors, response=response)

        return d.addCallback(to_error)

    def read(self, path, **params):
        """
        Read data from Vault. Returns the JSON-decoded response.
        """
        d = self.request('GET', '/v1/' + path, params=params)
        return d.addCallback(self._handle_response)

    def write(self, path, **data):
        """
        Write data to Vault. Returns the JSON-decoded response.
        """
        d = self.request('PUT', '/v1/' + path, json=data)
        return d.addCallback(self._handle_response, check_cas=True)

    def read_kv2(self, path, version=None, mount_path='secret'):
        """
        Read some data from a key/value version 2 secret engine.
        """
        params = {}
        if version is not None:
            params['version'] = version

        read_path = '{}/data/{}'.format(mount_path, path)
        return self.read(read_path, **params)

    def create_or_update_kv2(self, path, data, cas=None, mount_path='secret'):
        """
        Create or update some data in a key/value version 2 secret engine.

        :raises CasError:
            Raises an error if the ``cas`` value, when provided, doesn't match
            Vault's version for the key.
        """
        params = {
            'options': {},
            'data': data
        }
        if cas is not None:
            params['options']['cas'] = cas

        write_path = '{}/data/{}'.format(mount_path, path)
        return self.write(write_path, **params)


def _create_agent(reactor, insecure, ca_cert, tls_server_name, client_cert,
                  client_key):
    if insecure:
        context_factory = _insecure_context_factory()
    else:
        context_factory = _secure_context_factory(
            ca_cert, tls_server_name, client_cert, client_key)

    return Agent(default_reactor(reactor), contextFactory=context_factory)


def _insecure_context_factory():
    # TODO: Figure out how to do this?
    # https://github.com/twisted/treq/issues/65
    raise NotImplementedError()


def _secure_context_factory(ca_cert, tls_server_name, client_cert, client_key):
    trust_root, client_certificate = None, None
    if ca_cert:
        trust_root = Certificate.loadPEM(FilePath(ca_cert).getContent())

    if client_cert and client_key:
        # This is similar to this code:
        # https://github.com/twisted/twisted/blob/twisted-18.7.0/src/twisted/internet/endpoints.py#L1376-L1379
        certPEM = FilePath(client_cert).getContent()
        keyPEM = FilePath(client_key).getContent()
        client_certificate = (
            PrivateCertificate.loadPEM(certPEM + b'\n' + keyPEM))

    return _BrowserLikePolicyForHTTPS(
        trustRoot=trust_root, clientCertificate=client_certificate,
        tls_server_name=tls_server_name)


def _get_environ_str(env, env_key, default=None):
    # Works like the logic in Vault--ignores values that are set but empty
    env_value = env.get(env_key)
    return env_value if env_value else default


def _get_environ_bool(env, env_key):
    env_value = env.get(env_key)
    return env_value and strconv_ParseBool(env_value)


def strconv_ParseBool(s):
    """
    A port of Go's ParseBool function in the strconv package:
    https://github.com/golang/go/blob/release-branch.go1.11/src/strconv/atob.go#L7-L18
    """
    if s in ['1', 't', 'T', 'true', 'TRUE', 'True']:
        return True

    if s in ['0', 'f', 'F', 'false', 'FALSE', 'False']:
        return False

    raise ValueError("Unable to parse boolean value from '{}'".format(s))


@implementer(IPolicyForHTTPS)
class _BrowserLikePolicyForHTTPS(object):
    """
    Copy of twisted.web.client.BrowserLikePolicyForHTTPS but with 2 additions:
    * Allows passing the clientCertificate option to
      twisted.internet.ssl.optionsForClientTLS.
    * The hostname used for verification and SNI can be changed.

    https://github.com/twisted/twisted/blob/twisted-18.7.0/src/twisted/web/client.py#L915
    https://twistedmatrix.com/documents/current/api/twisted.internet.ssl.optionsForClientTLS.html
    """

    def __init__(self, trustRoot=None, clientCertificate=None,
                 tls_server_name=None):
        self._trustRoot = trustRoot
        self._clientCertificate = clientCertificate
        self._tls_server_name = tls_server_name

    def creatorForNetloc(self, hostname, port):
        if self._tls_server_name is not None:
            hostname = self._tls_server_name

        return optionsForClientTLS(hostname.decode("ascii"),
                                   trustRoot=self._trustRoot,
                                   clientCertificate=self._clientCertificate)
