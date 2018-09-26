from testtools.assertions import assert_that
from testtools.matchers import (
    AfterPreprocessing as After, Equals, Is, MatchesAll)
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

    def test_read_kv_nested(self):
        """
        When a request is made to read KV data for a nested path with data,
        that data and its metadata is returned.
        """
        self.vault.set_kv_data('certificates/www.p16n.org', {'foo': 'bar'})

        response = self.client.get(
            'http://localhost/v1/secret/data/certificates/www.p16n.org',
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

    def test_create_kv_nested(self):
        """
        When a request is made to update KV data for a nested path without
        data, the data is stored and the metadata is returned.
        """
        response = self.client.put(
            'http://localhost/v1/secret/data/certificates/www.p16n.org',
            headers={'X-Vault-Token': self.vault.token},
            json={'data': {'foo': 'baz'}}
        )
        assert_that(response, succeeded(MatchesAll(
            IsJsonResponseWithCode(200),
            After(json_content, succeeded(
                After(lambda d: d['data']['version'], Equals(1))
            ))
        )))

        data = self.vault.get_kv_data('certificates/www.p16n.org')
        assert_that(data['data'], Equals({'foo': 'baz'}))
        assert_that(data['metadata']['version'], Equals(1))

    def test_create_kv_with_cas(self):
        """
        When a request is made to update KV data for a path without data, and
        the CAS option is sent and matches, the data is stored and the metadata
        is returned.
        """
        response = self.client.put(
            'http://localhost/v1/secret/data/my-secret',
            headers={'X-Vault-Token': self.vault.token},
            json={'data': {'foo': 'bar'}, 'options': {'cas': 0}}
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

    def test_create_kv_with_cas_mismatch(self):
        """
        When a request is made to update KV data for a path without data, and
        the CAS option is sent but it does not match, the data is not stored
        and an error is returned.
        """
        response = self.client.put(
            'http://localhost/v1/secret/data/my-secret',
            headers={'X-Vault-Token': self.vault.token},
            json={'data': {'foo': 'bar'}, 'options': {'cas': 1}}
        )
        assert_that(response, succeeded(MatchesAll(
            IsJsonResponseWithCode(400),
            After(json_content, succeeded(Equals(
                {'errors': [
                    'check-and-set parameter did not match the current version'
                ]}
            )))
        )))

        data = self.vault.get_kv_data('my-secret')
        # No data set since CAS didn't match
        assert_that(data, Is(None))

    def test_pre_create_update(self):
        """
        When a request is made to update KV data and a pre-create/update
        callback has been set, that callback is called before the request is
        processed and afterwards the request proceeds as usual.
        """
        called = [False]

        def pre_create_update():
            # Check that the data hasn't been updated yet
            data = self.vault.get_kv_data('my-secret')
            assert_that(data, Is(None))

            called[0] = True

        self.vault_api.set_pre_create_update(pre_create_update)

        response = self.client.put(
            'http://localhost/v1/secret/data/my-secret',
            headers={'X-Vault-Token': self.vault.token},
            json={'data': {'foo': 'bar'}}
        )
        assert_that(response, succeeded(IsJsonResponseWithCode(200)))

        assert_that(called, Equals([True]))

        # After the callback, the data is stored
        data = self.vault.get_kv_data('my-secret')
        assert_that(data['data'], Equals({'foo': 'bar'}))

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

    def test_update_kv_with_cas(self):
        """
        When a request is made to update KV data for a path with data, and the
        CAS option is sent and matches, the data is stored and the new
        metadata is returned with a new version.
        """
        self.vault.set_kv_data('my-secret', {'foo': 'bar'})

        response = self.client.put(
            'http://localhost/v1/secret/data/my-secret',
            headers={'X-Vault-Token': self.vault.token},
            json={'data': {'foo': 'baz'}, 'options': {'cas': 1}}
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

    def test_update_kv_with_cas_mismatch(self):
        """
        When a request is made to update KV data for a path with data, and the
        CAS option is sent but it does not match, the data is not updated and
        an error is returned.
        """
        self.vault.set_kv_data('my-secret', {'foo': 'bar'})

        response = self.client.put(
            'http://localhost/v1/secret/data/my-secret',
            headers={'X-Vault-Token': self.vault.token},
            json={'data': {'foo': 'baz'}, 'options': {'cas': 0}}
        )
        assert_that(response, succeeded(MatchesAll(
            IsJsonResponseWithCode(400),
            After(json_content, succeeded(Equals(
                {'errors': [
                    'check-and-set parameter did not match the current version'
                ]}
            )))
        )))

        data = self.vault.get_kv_data('my-secret')
        # Data unchanged since CAS didn't match
        assert_that(data['data'], Equals({'foo': 'bar'}))
        assert_that(data['metadata']['version'], Equals(1))
