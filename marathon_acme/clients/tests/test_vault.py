import uuid

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

from marathon_acme.clients.vault import VaultClient, VaultError
from marathon_acme.server import write_request_json
from marathon_acme.tests.helpers import read_request_json
from marathon_acme.tests.matchers import (
    HasHeader, HasRequestProperties, WithErrorTypeAndMessage)


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
        request.setResponseCode(200)
        write_request_json(request, dummy_response)
        request.finish()
        self.stub_client.flush()

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
        request.setResponseCode(200)
        write_request_json(request, dummy_response)
        request.finish()
        self.stub_client.flush()

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
        request.setResponseCode(403)
        write_request_json(request, {'errors': ['permission denied']})
        request.finish()
        self.stub_client.flush()

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
        request.setResponseCode(404)
        write_request_json(request, {'errors': []})
        request.finish()
        self.stub_client.flush()

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
        request.setResponseCode(200)
        write_request_json(request, dummy_response)
        request.finish()
        self.stub_client.flush()

        # Response should be returned
        assert_that(d, succeeded(Equals(dummy_response)))

    def test_read_kv2_with_version(self):
        """
        When data is read from the key/value version 2 API and a version is
        specified, the version parameter is sent.
        """
        self.client.read_kv2('hello', version=1)

        request_d = self.requests.get()
        assert_that(request_d, succeeded(MatchesAll(
            HasRequestProperties(method='GET', url='/v1/secret/data/hello',
                                 query={'version': ['1']}),
            MatchesStructure(
                requestHeaders=HasHeader('X-Vault-Token', [self.token]))
        )))

    def test_create_or_update_kv2(self):
        """
        When data is read from the key/value version 2 API, the response is
        returned.
        """
        data = {'data': {'foo': 'world'}}
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
        request.setResponseCode(200)
        write_request_json(request, dummy_response)
        request.finish()
        self.stub_client.flush()

        # Response should be returned
        assert_that(d, succeeded(Equals(dummy_response)))

    def test_create_or_update_kv2_with_cas(self):
        """
        When data is read from the key/value version 2 API and a cas value is
        specified, the cas parameter is sent.
        """
        data = {'data': {'foo': 'world'}}
        self.client.create_or_update_kv2('hello', data, cas=1)

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
