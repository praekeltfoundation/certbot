from testtools.assertions import assert_that
from testtools.matchers import AfterPreprocessing as After
from testtools.matchers import Equals, MatchesAll
from testtools.twistedsupport import succeeded

from treq.content import json_content

from marathon_acme.tests.fake_vault import FakeVault, FakeVaultAPI
from marathon_acme.tests.matchers import IsJsonResponseWithCode


class TestFakeVaultAPI(object):
    def setup_method(self):
        self.vault = FakeVault()
        self.vault_api = FakeVaultAPI(self.vault)
        self.client = self.vault_api.client

    def test_no_token(self):
        """
        When a request is made without a Vault token, an error is returned by
        all API endpoints.
        """
        response = self.client.get('http://localhost/v1/secret/data/my-secret')
        assert_that(response, succeeded(MatchesAll(
            IsJsonResponseWithCode(400),
            After(json_content, succeeded(Equals(
                {'errors': ['missing client token']}
            )))
        )))

        response = self.client.put(
            'http://localhost/v1/secret/data/my-secret', json={'foo': 'bar'}
        )
        assert_that(response, succeeded(MatchesAll(
            IsJsonResponseWithCode(400),
            After(json_content, succeeded(Equals(
                {'errors': ['missing client token']}
            )))
        )))

    def test_invalid_token(self):
        """
        When a request is made with an invalid Vault token, an error is
        returned by all API endpoints.
        """
        response = self.client.get(
            'http://localhost/v1/secret/data/my-secret',
            headers={'X-Vault-Token': 'invalid'}
        )
        assert_that(response, succeeded(MatchesAll(
            IsJsonResponseWithCode(403),
            After(json_content, succeeded(Equals(
                {'errors': ['permission denied']}
            )))
        )))

        response = self.client.put(
            'http://localhost/v1/secret/data/my-secret',
            headers={'X-Vault-Token': 'invalid'},
            json={'foo': 'bar'}
        )
        assert_that(response, succeeded(MatchesAll(
            IsJsonResponseWithCode(403),
            After(json_content, succeeded(Equals(
                {'errors': ['permission denied']}
            )))
        )))

    def test_read_kv_not_found(self):
        """
        When a request is made to read KV data for a path with no data stored,
        an error is returned.
        """
        response = self.client.get(
            'http://localhost/v1/secret/data/my-secret',
            headers={'X-Vault-Token': self.vault.token}
        )
        assert_that(response, succeeded(MatchesAll(
            IsJsonResponseWithCode(404),
            After(json_content, succeeded(Equals({'errors': []})))
        )))

    def test_read_kv(self):
        """
        When a request is made to read KV data for a path with data, that data
        and its metadata is returned.
        """
        self.vault.set_kv_data('my-secret', {'foo': 'bar'})

        response = self.client.get(
            'http://localhost/v1/secret/data/my-secret',
            headers={'X-Vault-Token': self.vault.token}
        )
        assert_that(response, succeeded(MatchesAll(
            IsJsonResponseWithCode(200),
            After(json_content, succeeded(MatchesAll(
                After(lambda d: d['data']['data'], Equals({'foo': 'bar'})),
                After(lambda d: d['data']['metadata']['version'], Equals(1))
            )))
        )))

    def test_create_kv(self):
        """
        When a request is made to update KV data for a path without data, the
        data is stored and the metadata is returned.
        """
        response = self.client.put(
            'http://localhost/v1/secret/data/my-secret',
            headers={'X-Vault-Token': self.vault.token},
            json={'data': {'foo': 'bar'}}
        )
        assert_that(response, succeeded(MatchesAll(
            IsJsonResponseWithCode(200),
            After(json_content, succeeded(
                After(lambda d: d['data']['version'], Equals(1))
            ))
        )))

        data = self.vault.get_kv_data('my-secret')
        assert_that(data['data'], Equals({'foo': 'bar'}))
        assert_that(data['metadata']['version'], Equals(1))

    def test_update_kv(self):
        """
        When a request is made to update KV data for a path with data, the
        data is stored and the new metadata is returned with a new version.
        """
        self.vault.set_kv_data('my-secret', {'foo': 'bar'})

        response = self.client.put(
            'http://localhost/v1/secret/data/my-secret',
            headers={'X-Vault-Token': self.vault.token},
            json={'data': {'foo': 'baz'}}
        )
        assert_that(response, succeeded(MatchesAll(
            IsJsonResponseWithCode(200),
            After(json_content, succeeded(
                After(lambda d: d['data']['version'], Equals(2))
            ))
        )))

        data = self.vault.get_kv_data('my-secret')
        assert_that(data['data'], Equals({'foo': 'baz'}))
        assert_that(data['metadata']['version'], Equals(2))