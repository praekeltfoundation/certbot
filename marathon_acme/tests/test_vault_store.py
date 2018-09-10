import pem

from testtools.assertions import assert_that
from testtools.matchers import Equals, IsInstance
from testtools.twistedsupport import failed, succeeded

from marathon_acme.clients import VaultClient
from marathon_acme.tests.fake_vault import FakeVault, FakeVaultAPI
from marathon_acme.tests.matchers import WithErrorTypeAndMessage
from marathon_acme.vault_store import (
    VaultKvCertificateStore, from_pem_objects, to_pem_objects)


TEST_KEY = """-----BEGIN RSA PRIVATE KEY-----
MIIEpAIBAAKCAQEA6+vi8A5o9OuYN7ScRnfxqsGRK182AqU7IVw+CRypy6BfhoII
90pEuJtll7hgwcprsUuNWRhrJYQoXQWhmJbpTGZ6DaAlcOgWQZvwCtSH01vsvK/v
lSDM2ug+M3J1UmLpn8UDjJTsCyXkvmyNE2ENAUxFrrBXxJas1iYrd36KuotYrwoJ
L4reVohTWjhrlCGMTdaTYhaUOjgyAoWctTcWtWMofORJs/1mGoiQ1CavZhyyASAQ
1+BzHPX43Y9HM9GjSQLhpiMkfFbLWhhpyFnrfoQbmGQyDbE2PKB9d/jnNcwpoUeh
2SNxe+AkkkpKnvUhdZyXlpdiBNpCUl6LP2q96QIDAQABAoIBAFeMMarjrg81XkdN
vrBn0kaLjlOKAYD5z/eRQ3QeLuRhnxFLMAiUhuv6vriOs1k2xMAGSW3GofxKDrB2
ZoE5f1narXBg/YPonFm8hFeAhuboNfHPWBj/EwYpKOvujZsFGa0wbyC8ItwAM+J2
ZePLIAhbRYCN8AQD5h+SCo9NZi3S0aqxnwM3OeqU/hofFq3LUKHIL7k11lPK8Wi2
c1wWw3A3Fr9CmDfFvbQjo9yy6VBye/b8NVerQMfH7HCyQUKQyRZ6SBqzl7GufQMF
fG0yM/IrGcJow8ItGl2HCgI1IJ2dmqZ8ScurRKLKEb8pEFEC1TI42Z5bG7JTvQaE
0XbqgAECgYEA+a1kXM7YHsege0m9aEcOEeQjuaKmRN6HD0WEdYPZsMjoNUaYlCq2
XrFJH9znblActdCy04VMnoS8qiOePd9eCbG1E7V04TQnvcc+6XpuJkDzgQO9acKt
BlTF5tYER1ai1PjdVzKwlUGZXWUAlh7uAri1cLbkjaWUJk6GjDACK3ECgYEA8eVR
XFOqBUP4QgKzFrPKvKIG4HhOdlSa2W/I8RpaXx0LC5D58jokG6+iOF9trNcOAHfr
bPHlwzcfKGdt0NusERfxMBPB8V+ymoaybu3EWRFy1g88Rn5gLnJH+5aDFDjHuldU
5i/+0KCFjSSVqyGCrQAfnd8kvqw/jD5vUqRVzfkCgYEAw3A6s3smKVHSCS+7l7in
BtIyNMlgpWAbEJU2DlbbPErHmYxdOv4EKzNTLiHY9ry2/IsUsAYT57G3jOa8o2oJ
TkVQnNDZYL9WrHMeh9xSBJerBD5NMlA06FPLZdn5F251n4f+mpcPKoZi6nx5bQlg
/bhgLo67cTU/No0ZPPsHd8ECgYBvF1PgRQQmWure1gKNgJCxRPBHkrjmG0Dqby4n
nGS4ncv+ydwgZJdEp8qmfR0PbcyeZnSWmhldKCmFEssaSmihiQ9Zdxlw0vRhh07X
JxcvmJXWvTR/Y3aknhN09dDJLrJ7X7Q76vrpsW7kPVMHPuKWtSHQDTUA5HZi4CGc
IKDPcQKBgQCO4ul0i5JPFVsvuAOAFGWm3uVTCRRKI5NSBK2LLS5hFycASQrRR1Z/
KpDNUDLEsF7n8iMG0npvKunVL9TKixfjRqbXYIn1U3KnCJv0g+GoN067xWUqCwRX
VIK/oO/fvHNH7P/HLuKrgdeYenvNhDKKRFy9OKgAF2ZN03nEXohSSw==
-----END RSA PRIVATE KEY-----"""

TEST_CERT = """-----BEGIN CERTIFICATE-----
MIIEMzCCAxugAwIBAgIUUmeTbND119hQ/XSC5NZ7TEuk91wwDQYJKoZIhvcNAQEL
BQAwfjELMAkGA1UEBhMCWkExCzAJBgNVBAgTAkdQMRUwEwYDVQQHEwxKb2hhbm5l
c2J1cmcxGTAXBgNVBAoTEGs4cy10aGUtaGFyZC13YXkxHjAcBgNVBAsTFUNlcnRp
ZmljYXRlIEF1dGhvcml0eTEQMA4GA1UEAxMHUm9vdCBDQTAeFw0xODA0MDExNzEz
MDBaFw0xODA0MDgxNzEzMDBaMGAxCzAJBgNVBAYTAlpBMQswCQYDVQQIEwJHUDEV
MBMGA1UEBxMMSm9oYW5uZXNidXJnMRkwFwYDVQQKExBrOHMtdGhlLWhhcmQtd2F5
MRIwEAYDVQQDEwlldGNkLXBlZXIwggEiMA0GCSqGSIb3DQEBAQUAA4IBDwAwggEK
AoIBAQDr6+LwDmj065g3tJxGd/GqwZErXzYCpTshXD4JHKnLoF+Gggj3SkS4m2WX
uGDBymuxS41ZGGslhChdBaGYlulMZnoNoCVw6BZBm/AK1IfTW+y8r++VIMza6D4z
cnVSYumfxQOMlOwLJeS+bI0TYQ0BTEWusFfElqzWJit3foq6i1ivCgkvit5WiFNa
OGuUIYxN1pNiFpQ6ODIChZy1Nxa1Yyh85Emz/WYaiJDUJq9mHLIBIBDX4HMc9fjd
j0cz0aNJAuGmIyR8VstaGGnIWet+hBuYZDINsTY8oH13+Oc1zCmhR6HZI3F74CSS
Skqe9SF1nJeWl2IE2kJSXos/ar3pAgMBAAGjgcYwgcMwDgYDVR0PAQH/BAQDAgWg
MB0GA1UdJQQWMBQGCCsGAQUFBwMBBggrBgEFBQcDAjAMBgNVHRMBAf8EAjAAMB0G
A1UdDgQWBBTpwxt6C6wnKK+pNiEKXSjfLzpd3zAfBgNVHSMEGDAWgBQDt8vdvkbW
2A02trK2n2FIQDa9QDBEBgNVHREEPTA7ggxjb250cm9sbGVyLTCCH2NvbnRyb2xs
ZXItMC5rOHMuamFtaWUuY29tcHV0ZXKHBKdjgXOHBAqHSRkwDQYJKoZIhvcNAQEL
BQADggEBAHnCF6ITWYSvERkIaW9dU7kV9ebvRgZ6Zn2d0jKDhYrjMBb8ozmgvsVP
w1JkI6Z/ve3N/NzJrKKTseb/JWR7SdLFgjez8L0bH8ylIXps97kYH05l8oKQNBjv
u6A1Y78U3F6CVYNAzNABTipolWOVCxPIuUI4IMPxlKbnYk8edbkiXC+i9Ls05agV
n7cpq4SZxNwvRZx+jFc4346dVBXjZrwhlMcgF917m1a+r75kIIWuggptrVyVY+/1
axT0MX8gyGefQta0t/988otZtR19V3iC9oGHzWpBRisfBvdYBFgenPJFGi28lkU6
ry2+Fp9RCYPTfNrLYt2zNLP/2bJN/zY=
-----END CERTIFICATE-----"""

TEST_CA_CERT = """-----BEGIN CERTIFICATE-----
MIIDzDCCArSgAwIBAgIUQFogPHX+7gr9e6ERzmo8WO5Q8SAwDQYJKoZIhvcNAQEL
BQAwfjELMAkGA1UEBhMCWkExCzAJBgNVBAgTAkdQMRUwEwYDVQQHEwxKb2hhbm5l
c2J1cmcxGTAXBgNVBAoTEGs4cy10aGUtaGFyZC13YXkxHjAcBgNVBAsTFUNlcnRp
ZmljYXRlIEF1dGhvcml0eTEQMA4GA1UEAxMHUm9vdCBDQTAeFw0xODAzMjExODQy
MDBaFw0yMzAzMjAxODQyMDBaMH4xCzAJBgNVBAYTAlpBMQswCQYDVQQIEwJHUDEV
MBMGA1UEBxMMSm9oYW5uZXNidXJnMRkwFwYDVQQKExBrOHMtdGhlLWhhcmQtd2F5
MR4wHAYDVQQLExVDZXJ0aWZpY2F0ZSBBdXRob3JpdHkxEDAOBgNVBAMTB1Jvb3Qg
Q0EwggEiMA0GCSqGSIb3DQEBAQUAA4IBDwAwggEKAoIBAQDLv+2Las4F06042fCr
JGcE2N8KPkKGCOk8DuOX06EI+O53VlmXWj+RnRhejt9ifGwjZA/XGKSF4RxL6Duh
lonbDDBpR2ImmuNMw9RuF7gcXzhIUZEOPgBOyhaUzEC1H2JslKuWpdmSlfvU650H
5ThOBQBLtr4abF8qA352oKlxWPxCKOMhx+Tqw/0HHZkdrD2zkIO1OeoHc+Mv3CvB
B778OkeDUASCB8zRGiyl/ATxCMOM58QZRXjQFgcwFqkzdrISaRqRqC+aDcBQtWrv
HuK/w6RsyO7lMuFybkQfJXnrfEAuBfGwlslURf+kpFuiuOKUewG2fBDaBwvJ85Eo
P3l3AgMBAAGjQjBAMA4GA1UdDwEB/wQEAwIBBjAPBgNVHRMBAf8EBTADAQH/MB0G
A1UdDgQWBBQDt8vdvkbW2A02trK2n2FIQDa9QDANBgkqhkiG9w0BAQsFAAOCAQEA
sTbcKu2x1I4b6hkaLUj32C5Ze6IVpA5NKtm4zBj1dDcFw3jygZ4qFijtMNN96nA7
cbK58az2a091wVoMM2RidH/OCpW7/ucNSCpmmqsQSejDsPcIxXMWWDvkEp4tsCnz
w5Zln+v+dClTl0lRjtFKIxUe2HHKaAhd58FD5/AxQrZv9GihtbJtr+kE/KJMPh2b
PWBSJSgCCxYGVg+JJOgCv92ncKpbH6ARMvvrH5HFTaCI5Oo/etLe2F3CAH+fCTnj
L7aglSEDZuTHQG0XYjICwPhEdj0NMS0NSYyFWkUb/1AjDNr0zfeNDUl6QXqZH20W
dKQSIS96RIVMceGYUsP1gg==
-----END CERTIFICATE-----"""

TEST_CERT_CHAIN = '\n'.join([TEST_CERT, TEST_CA_CERT])

TEST_PEM_OBJECTS = (pem.parse(TEST_KEY.encode('utf-8'))
                    + pem.parse(TEST_CERT_CHAIN.encode('utf-8')))


def test_to_pem_object():
    pem_objects = to_pem_objects({
        'data': {
            'data': {
                'domains': "doesn't matter",
                'key': TEST_KEY,
                'cert_chain': TEST_CERT_CHAIN
            }
        }
    })

    assert pem_objects == TEST_PEM_OBJECTS


def test_from_pem_objects():
    data = from_pem_objects('www.p16n.org', TEST_PEM_OBJECTS)

    assert data == {
        'domains': 'www.p16n.org',
        'key': TEST_KEY,
        'cert_chain': TEST_CERT_CHAIN
    }


class TestVaultKvCertificateStore(object):
    def setup_method(self):
        self.vault = FakeVault()
        vault_api = FakeVaultAPI(self.vault)

        self.client = vault_api.client
        vault_client = VaultClient(
            'http://localhost:8200', self.vault.token, client=self.client)

        self.store = VaultKvCertificateStore(vault_client, 'secret')

    def test_get(self):
        """
        When a certificate is fetched from the store and it exists, the
        certificate is returned as a list of PEM objects.
        """
        self.vault.set_kv_data('certificates/www.p16n.org', {
            'domains': 'www.p16n.org',
            'key': TEST_KEY,
            'cert_chain': TEST_CERT_CHAIN
        })

        d = self.store.get('www.p16n.org')
        assert_that(d, succeeded(Equals(TEST_PEM_OBJECTS)))

    def test_get_not_exists(self):
        """
        When a certificate is fetched from the store but it does not exist, a
        KeyError is raised as specified by the txacme interface.
        """
        d = self.store.get('www.p16n.org')
        assert_that(d, failed(WithErrorTypeAndMessage(
            KeyError, repr('www.p16n.org')
        )))

    def test_store_create_live(self):
        """
        When a certificate is stored in the store, the certificate is saved and
        the live data is created when it does not exist.
        """
        d = self.store.store('www.p16n.org', TEST_PEM_OBJECTS)
        # We return the final kv write response from Vault, but txacme doesn't
        # care what the result of the deferred is
        assert_that(d, succeeded(IsInstance(dict)))

        cert_data = self.vault.get_kv_data('certificates/www.p16n.org')
        assert cert_data['data'] == {
            'domains': 'www.p16n.org',
            'key': TEST_KEY,
            'cert_chain': TEST_CERT_CHAIN
        }
        assert cert_data['metadata']['version'] == 1

        live_data = self.vault.get_kv_data('live')
        assert live_data['data'] == {'www.p16n.org': 'FINGERPRINT'}
        assert live_data['metadata']['version'] == 1

    def test_store_update_live(self):
        """
        When a certificate is stored in the store, the certificate is saved and
        the live data is updated when it does exist.
        """
        self.vault.set_kv_data('live', {'p16n.org': 'FINGERPRINT'})

        d = self.store.store('www.p16n.org', TEST_PEM_OBJECTS)
        # We return the final kv write response from Vault, but txacme doesn't
        # care what the result of the deferred is
        assert_that(d, succeeded(IsInstance(dict)))

        live_data = self.vault.get_kv_data('live')
        assert live_data['data'] == {
            'p16n.org': 'FINGERPRINT',
            'www.p16n.org': 'FINGERPRINT'
        }
        assert live_data['metadata']['version'] == 2

    def test_as_dict(self):
        """
        When the certificates are fetched as a dict, all certificates are
        returned in a dict.
        """
        self.vault.set_kv_data('certificates/www.p16n.org', {
            'domains': 'www.p16n.org',
            'key': TEST_KEY,
            'cert_chain': TEST_CERT_CHAIN
        })
        self.vault.set_kv_data('live', {'www.p16n.org': 'FINGERPRINT'})

        d = self.store.as_dict()
        assert_that(d, succeeded(Equals({'www.p16n.org': TEST_PEM_OBJECTS})))

    def test_as_dict_empty(self):
        """
        When the certificates are fetched as a dict, and the live mapping does
        not exist, an empty dict is returned.
        """
        d = self.store.as_dict()
        assert_that(d, succeeded(Equals({})))
