import os
import uuid

import pytest

from testtools.assertions import assert_that
from testtools.matchers import (
    AfterPreprocessing as After, Equals, Is, IsInstance, MatchesAll,
    MatchesStructure)
from testtools.twistedsupport import failed, succeeded

from treq.testing import StubTreq

from twisted.internet.defer import DeferredQueue
from twisted.web.resource import IResource
from twisted.web.server import NOT_DONE_YET

from zope.interface import implementer

from marathon_acme.clients.tests.matchers import HasRequestProperties
from marathon_acme.clients.vault import (
    CasError, VaultClient, VaultError, strconv_ParseBool)
from marathon_acme.server import write_request_json
from marathon_acme.tests.helpers import read_request_json
from marathon_acme.tests.matchers import HasHeader, WithErrorTypeAndMessage


@implementer(IResource)
class QueueResource(object):
    isLeaf = True

    def __init__(self):
        self.queue = DeferredQueue()

    def render(self, request):
        self.queue.put(request)
        return NOT_DONE_YET

    def get(self):
        return self.queue.get()


class TestVaultClient(object):
    # NOTE: Unlike the other client tests, these tests use treq's testing
    # machinery, which we didn't know about before. This means we don't have to
    # use testtools' TestCase or AsynchronousDeferredRunTest, or jerith's
    # txfake. The tests are synchronous.

    def setup_method(self):
        self.requests = QueueResource()
        self.stub_client = StubTreq(self.requests)
        self.token = str(uuid.uuid4())

        self.client = VaultClient(
            'http://localhost:8200', self.token, client=self.stub_client)

    def json_response(self, request, json_response, code=200):
        request.setResponseCode(code)
        write_request_json(request, json_response)
        request.finish()
        self.stub_client.flush()

    def test_read(self):
        """
        When data is read, a GET request is made and the data in the response
        is returned.
        """
        d = self.client.read('secret/data/hello')

        request_d = self.requests.get()
        assert_that(request_d, succeeded(MatchesAll(
            HasRequestProperties(method='GET', url='/v1/secret/data/hello'),
            MatchesStructure(
                requestHeaders=HasHeader('X-Vault-Token', [self.token]))
        )))

        # Write the response
        dummy_response = {
            "request_id": "08b0ba90-b6e4-afab-de6a-d2fbf8f480b3",
            "lease_id": "",
            "renewable": False,
            "lease_duration": 0,
            "data": {
                "data": {"foo": "world"},
                "metadata": {
                    "created_time": "2018-09-05T12:49:52.722404Z",
                    "deletion_time": "",
                    "destroyed": False,
                    "version": 1
                }
            },
            "wrap_info": None,
            "warnings": None,
            "auth": None
        }

        request = request_d.result
        self.json_response(request, dummy_response)

        # Response should be returned
        assert_that(d, succeeded(Equals(dummy_response)))

    def test_write(self):
        """
        When data is written, a PUT request is made with the data encoded as
        JSON. The data in the response is returned.
        """
        data = {'data': {'foo': 'world'}}
        d = self.client.write('secret/data/hello', **data)

        request_d = self.requests.get()
        assert_that(request_d, succeeded(MatchesAll(
            HasRequestProperties(method='PUT', url='/v1/secret/data/hello'),
            MatchesStructure(
                requestHeaders=HasHeader('X-Vault-Token', [self.token])),
            After(read_request_json, Equals(data))
        )))

        # Write the response
        dummy_response = {
            "request_id": "c5512c45-cace-ed90-1630-bbf2608aefea",
            "lease_id": "",
            "renewable": False,
            "lease_duration": 0,
            "data": {
                "created_time": "2018-09-05T12:53:41.405819Z",
                "deletion_time": "",
                "destroyed": False,
                "version": 2
            },
            "wrap_info": None,
            "warnings": None,
            "auth": None
        }

        request = request_d.result
        self.json_response(request, dummy_response)

        # Response should be returned
        assert_that(d, succeeded(Equals(dummy_response)))

    def test_client_error(self):
        """
        When Vault returns an error status code with a JSON response, an
        error is raised with the contents of the ``errors`` field of the JSON.
        """
        d = self.client.read('secret/data/hello')

        request_d = self.requests.get()
        assert_that(request_d, succeeded(
            HasRequestProperties(method='GET', url='/v1/secret/data/hello')
        ))

        request = request_d.result
        self.json_response(
            request, {'errors': ['permission denied']}, code=403)

        assert_that(d, failed(MatchesStructure(value=MatchesAll(
            IsInstance(VaultError),
            After(str, Equals('permission denied')),
            MatchesStructure(errors=Equals(['permission denied']))
        ))))

    def test_server_error(self):
        """
        When Vault returns an error status code without a JSON response, an
        error is raised with the contents of the response body.
        """
        d = self.client.read('secret/data/hello')

        request_d = self.requests.get()
        assert_that(request_d, succeeded(
            HasRequestProperties(method='GET', url='/v1/secret/data/hello')
        ))

        request = request_d.result
        request.setResponseCode(503)
        request.write(b'service unavailable')
        request.finish()
        self.stub_client.flush()

        assert_that(d, failed(
            WithErrorTypeAndMessage(VaultError, 'service unavailable')))

    def test_not_found(self):
        """
        When Vault returns a 404 with no messages in the ``errors`` JSON field,
        None is returned by the client.
        """
        d = self.client.read('secret/data/hello')

        request_d = self.requests.get()
        assert_that(request_d, succeeded(
            HasRequestProperties(method='GET', url='/v1/secret/data/hello')
        ))

        request = request_d.result
        self.json_response(request, {'errors': []}, code=404)

        assert_that(d, succeeded(Is(None)))

    def test_read_kv2(self):
        """
        When data is read from the key/value version 2 API, the response is
        returned.
        """
        d = self.client.read_kv2('hello')

        request_d = self.requests.get()
        assert_that(request_d, succeeded(MatchesAll(
            HasRequestProperties(method='GET', url='/v1/secret/data/hello',
                                 query={}),
            MatchesStructure(
                requestHeaders=HasHeader('X-Vault-Token', [self.token]))
        )))

        # Write the response
        dummy_response = {
            "request_id": "08b0ba90-b6e4-afab-de6a-d2fbf8f480b3",
            "lease_id": "",
            "renewable": False,
            "lease_duration": 0,
            "data": {
                "data": {"foo": "world"},
                "metadata": {
                    "created_time": "2018-09-05T12:49:52.722404Z",
                    "deletion_time": "",
                    "destroyed": False,
                    "version": 1
                }
            },
            "wrap_info": None,
            "warnings": None,
            "auth": None
        }

        request = request_d.result
        self.json_response(request, dummy_response)

        # Response should be returned
        assert_that(d, succeeded(Equals(dummy_response)))

    def test_read_kv2_with_version(self):
        """
        When data is read from the key/value version 2 API and a version is
        specified, the version parameter is sent.
        """
        d = self.client.read_kv2('hello', version=1)

        request_d = self.requests.get()
        assert_that(request_d, succeeded(MatchesAll(
            HasRequestProperties(method='GET', url='/v1/secret/data/hello',
                                 query={'version': ['1']}),
            MatchesStructure(
                requestHeaders=HasHeader('X-Vault-Token', [self.token]))
        )))

        # We don't care much about the response but we have to see the request
        # to completion or else the DelayedCall from the request timeout will
        # interfere with other tests.
        request = request_d.result
        self.json_response(request, {'errors': []}, code=404)

        assert_that(d, succeeded(Is(None)))

    def test_create_or_update_kv2(self):
        """
        When data is read from the key/value version 2 API, the response is
        returned.
        """
        data = {'foo': 'world'}
        d = self.client.create_or_update_kv2('hello', data)

        request_d = self.requests.get()
        assert_that(request_d, succeeded(MatchesAll(
            HasRequestProperties(method='PUT', url='/v1/secret/data/hello'),
            MatchesStructure(
                requestHeaders=HasHeader('X-Vault-Token', [self.token])),
            After(read_request_json, Equals({
                'data': data,
                'options': {}
            }))
        )))

        # Write the response
        dummy_response = {
            "request_id": "c5512c45-cace-ed90-1630-bbf2608aefea",
            "lease_id": "",
            "renewable": False,
            "lease_duration": 0,
            "data": {
                "created_time": "2018-09-05T12:53:41.405819Z",
                "deletion_time": "",
                "destroyed": False,
                "version": 2
            },
            "wrap_info": None,
            "warnings": None,
            "auth": None
        }

        request = request_d.result
        self.json_response(request, dummy_response)

        # Response should be returned
        assert_that(d, succeeded(Equals(dummy_response)))

    def test_create_or_update_kv2_with_cas(self):
        """
        When data is read from the key/value version 2 API and a cas value is
        specified, the cas parameter is sent.
        """
        data = {'foo': 'world'}
        d = self.client.create_or_update_kv2('hello', data, cas=1)

        request_d = self.requests.get()
        assert_that(request_d, succeeded(MatchesAll(
            HasRequestProperties(method='PUT', url='/v1/secret/data/hello'),
            MatchesStructure(
                requestHeaders=HasHeader('X-Vault-Token', [self.token])),
            After(read_request_json, Equals({
                'data': data,
                'options': {'cas': 1}
            }))
        )))

        # We don't care much about the response but we have to see the request
        # to completion or else the DelayedCall from the request timeout will
        # interfere with other tests.
        request = request_d.result
        self.json_response(request, {'errors': []}, code=404)

        assert_that(d, succeeded(Is(None)))

    def test_create_or_update_kv2_with_cas_mismatch(self):
        """
        When data is read from the key/value version 2 API and a cas value is
        specified, but the server rejects the CAS value, the correct error
        type should be raised.
        """
        data = {'foo': 'world'}
        d = self.client.create_or_update_kv2('hello', data, cas=1)

        request_d = self.requests.get()
        assert_that(request_d, succeeded(MatchesAll(
            After(read_request_json, Equals({
                'data': data,
                'options': {'cas': 1}
            }))
        )))

        request = request_d.result
        self.json_response(request, {'errors': [
                'check-and-set parameter did not match the current version'
            ]}, code=400)

        assert_that(d, failed(WithErrorTypeAndMessage(
            CasError,
            'check-and-set parameter did not match the current version'
        )))


FIXTURES = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'fixtures')
CA_FILENAME = 'ca.pem'
CLIENT_CERT_FILENAME = 'vault-client.pem'
CLIENT_KEY_FILENAME = 'vault-client-key.pem'
SERVER_CERT_FILENAME = 'vault-server.pem'
SERVER_KEY_FILENAME = 'vault-server-key.pem'


class TestVaultClientFromEnviron(object):
    def test_empty_environ(self):
        vault_client = VaultClient.from_environ(env={})

        # TODO: Figure out how to test this better?
        assert vault_client.url == 'https://127.0.0.1:8200'
        assert vault_client._token == 'TEST'

    def test_insecure_not_implemented(self):
        with pytest.raises(NotImplementedError):
            VaultClient.from_environ(env={'VAULT_SKIP_VERIFY': '1'})

    def test_certs(self):
        VaultClient.from_environ(env={
            'VAULT_CACERT': os.path.join(FIXTURES, CA_FILENAME),
            'VAULT_CLIENT_CERT': os.path.join(FIXTURES, CLIENT_CERT_FILENAME),
            'VAULT_CLIENT_KEY': os.path.join(FIXTURES, CLIENT_KEY_FILENAME),
        })

        # TODO: Figure out how to assert things...


class TestStrconvParseBoolFunc(object):
    def test_true(self):
        for s in ['1', 't', 'T', 'true', 'TRUE', 'True']:
            assert strconv_ParseBool(s)

    def test_false(self):
        for s in ['0', 'f', 'F', 'false', 'FALSE', 'False']:
            assert not strconv_ParseBool(s)

    def test_invalid(self):
        with pytest.raises(ValueError) as e_info:
            strconv_ParseBool('TrUe')

        assert str(e_info.value) == "Unable to parse boolean value from 'TrUe'"
