from datetime import datetime

from acme import challenges
from acme.jose import JWKRSA
from testtools.assertions import assert_that
from testtools.matchers import (
    AfterPreprocessing, Equals, Is, MatchesAll, MatchesDict, MatchesListwise,
    MatchesStructure, Not)
from testtools.twistedsupport import succeeded
from treq.testing import StubTreq
from twisted.internet.defer import succeed
from twisted.internet.task import Clock
from txacme.testing import FakeClient, MemoryStore
from txacme.util import generate_private_key

from marathon_acme.clients import MarathonClient, MarathonLbClient
from marathon_acme.service import MarathonAcme, parse_domain_label
from marathon_acme.tests.fake_marathon import (
    FakeMarathon, FakeMarathonAPI, FakeMarathonLb)


class TestParseDomainLabel(object):
    def test_single_domain(self):
        """
        When the domain label contains just a single domain, that domain should
        be parsed into a list containing just the one domain.
        """
        domains = parse_domain_label('example.com')
        assert_that(domains, Equals(['example.com']))

    def test_whitespace(self):
        """
        When the domain label contains whitespace, the whitespace should be
        ignored.
        """
        domains = parse_domain_label(' ')
        assert_that(domains, Equals([]))

    def test_multiple_domains(self):
        """
        When the domain label contains multiple comma-separated domains, the
        domains should be parsed into a list of domains.
        """
        domains = parse_domain_label('example.com,example2.com')
        assert_that(domains, Equals(['example.com', 'example2.com']))

    def test_multiple_domains_whitespace(self):
        """
        When the domain label contains multiple comma-separated domains with
        whitespace inbetween, the domains should be parsed into a list of
        domains without the whitespace.
        """
        domains = parse_domain_label(' example.com, example2.com ')
        assert_that(domains, Equals(['example.com', 'example2.com']))


is_marathon_lb_sigusr_response = MatchesListwise([  # Per marathon-lb instance
    MatchesAll(
        MatchesStructure(code=Equals(200)),
        AfterPreprocessing(
            lambda r: r.text(), succeeded(
                Equals('Sent SIGUSR1 signal to marathon-lb'))))
])


class TestMarathonAcme(object):

    def setup_method(self):
        self.fake_marathon = FakeMarathon()
        fake_marathon_api = FakeMarathonAPI(self.fake_marathon)
        self.marathon_inner_client = StubTreq(fake_marathon_api.app.resource())
        marathon_client = MarathonClient(
            'http://localhost:8080',
            client=self.marathon_inner_client)

        self.cert_store = MemoryStore()

        self.fake_marathon_lb = FakeMarathonLb()
        mlb_client = MarathonLbClient(
            ['http://localhost:9090'],
            client=StubTreq(self.fake_marathon_lb.app.resource()))

        key = JWKRSA(key=generate_private_key(u'rsa'))
        self.clock = Clock()
        self.clock.rightNow = (
            datetime.now() - datetime(1970, 1, 1)).total_seconds()
        txacme_client = FakeClient(key, self.clock)
        # Patch on support for HTTP challenge types
        txacme_client._challenge_types.append(challenges.HTTP01)

        self.marathon_acme = MarathonAcme(
            marathon_client,
            'external',
            self.cert_store,
            mlb_client,
            lambda: succeed(txacme_client),
            self.clock
        )

    def test_sync_app(self):
        """
        When a sync is run and there is an app with a domain label and no
        existing certificate, then a new certificate should be issued for the
        domain. The certificate should be stored in the certificate store and
        marathon-lb should be notified.
        """
        # Store an app in Marathon with a marathon-acme domain
        self.fake_marathon.add_app({
            'id': '/my-app_1',
            'labels': {
                'HAPROXY_GROUP': 'external',
                'MARATHON_ACME_0_DOMAIN': 'example.com'
            },
            'portDefinitions': [
                {'port': 9000, 'protocol': 'tcp', 'labels': {}}
            ]
        })

        d = self.marathon_acme.sync()
        assert_that(d, succeeded(MatchesListwise([  # Per domain
            is_marathon_lb_sigusr_response
        ])))

        assert_that(self.cert_store.as_dict(), succeeded(MatchesDict({
            'example.com': Not(Is(None))
        })))

        assert_that(self.fake_marathon_lb.check_signalled_usr1(), Equals(True))

    def test_sync_app_multiple_ports(self):
        """
        When a sync is run and there is an app with domain labels for multiple
        ports, then certificates should be fetched for each port.
        """
        # Store an app in Marathon with a marathon-acme domain
        self.fake_marathon.add_app({
            'id': '/my-app_1',
            'labels': {
                'HAPROXY_GROUP': 'external',
                'MARATHON_ACME_0_DOMAIN': 'example.com',
                'MARATHON_ACME_1_DOMAIN': 'example2.com'
            },
            'portDefinitions': [
                {'port': 9000, 'protocol': 'tcp', 'labels': {}},
                {'port': 9001, 'protocol': 'tcp', 'labels': {}}
            ]
        })

        d = self.marathon_acme.sync()
        assert_that(d, succeeded(MatchesListwise([  # Per domain
            is_marathon_lb_sigusr_response,
            is_marathon_lb_sigusr_response
        ])))

        assert_that(self.cert_store.as_dict(), succeeded(MatchesDict({
            'example.com': Not(Is(None)),
            'example2.com': Not(Is(None))
        })))

        assert_that(self.fake_marathon_lb.check_signalled_usr1(), Equals(True))

    def test_sync_multiple_apps(self):
        """
        When a sync is run and there are multiple apps, certificates are
        fetched for the domains of all the apps.
        """
        self.fake_marathon.add_app({
            'id': '/my-app_1',
            'labels': {
                'HAPROXY_GROUP': 'external',
                'MARATHON_ACME_0_DOMAIN': 'example.com',
            },
            'portDefinitions': [
                {'port': 9000, 'protocol': 'tcp', 'labels': {}}
            ]
        })
        self.fake_marathon.add_app({
            'id': '/my-app_2',
            'labels': {
                'HAPROXY_GROUP': 'external',
                'MARATHON_ACME_0_DOMAIN': 'example2.com',
            },
            'portDefinitions': [
                {'port': 8000, 'protocol': 'tcp', 'labels': {}},
            ]
        })

        d = self.marathon_acme.sync()
        assert_that(d, succeeded(MatchesListwise([  # Per domain
            is_marathon_lb_sigusr_response,
            is_marathon_lb_sigusr_response
        ])))

        assert_that(self.cert_store.as_dict(), succeeded(MatchesDict({
            'example.com': Not(Is(None)),
            'example2.com': Not(Is(None))
        })))

        assert_that(self.fake_marathon_lb.check_signalled_usr1(), Equals(True))

    def test_sync_apps_common_domains(self):
        """
        When a sync is run and there are multiple apps, possibly with multiple
        ports, then certificates are only fetched for unique domains.
        """
        self.fake_marathon.add_app({
            'id': '/my-app_1',
            'labels': {
                'HAPROXY_GROUP': 'external',
                'MARATHON_ACME_0_DOMAIN': 'example.com',
                'MARATHON_ACME_1_DOMAIN': 'example.com'
            },
            'portDefinitions': [
                {'port': 9000, 'protocol': 'tcp', 'labels': {}},
                {'port': 9001, 'protocol': 'tcp', 'labels': {}}
            ]
        })
        self.fake_marathon.add_app({
            'id': '/my-app_2',
            'labels': {
                'HAPROXY_GROUP': 'external',
                'MARATHON_ACME_0_DOMAIN': 'example.com',
            },
            'portDefinitions': [
                {'port': 8000, 'protocol': 'tcp', 'labels': {}},
            ]
        })

        d = self.marathon_acme.sync()
        assert_that(d, succeeded(MatchesListwise([  # Per domain
            is_marathon_lb_sigusr_response
        ])))

        assert_that(self.cert_store.as_dict(), succeeded(MatchesDict({
            'example.com': Not(Is(None))
        })))

        assert_that(self.fake_marathon_lb.check_signalled_usr1(), Equals(True))

    def test_sync_app_multiple_domains(self):
        """
        When a sync is run and there is an app with a domain label containing
        multiple domains, then only the first domain is considered.
        """
        self.fake_marathon.add_app({
            'id': '/my-app_1',
            'labels': {
                'HAPROXY_GROUP': 'external',
                'MARATHON_ACME_0_DOMAIN': 'example.com,example2.com'
            },
            'portDefinitions': [
                {'port': 9000, 'protocol': 'tcp', 'labels': {}}
            ]
        })

        d = self.marathon_acme.sync()
        assert_that(d, succeeded(MatchesListwise([  # Per domain
            is_marathon_lb_sigusr_response
        ])))

        assert_that(self.cert_store.as_dict(), succeeded(MatchesDict({
            'example.com': Not(Is(None))
        })))

        assert_that(self.fake_marathon_lb.check_signalled_usr1(), Equals(True))

    def test_sync_no_apps(self):
        """
        When a sync is run and Marathon has no apps for us then no certificates
        should be fetched and marathon-lb should not be notified.
        """
        d = self.marathon_acme.sync()
        assert_that(d, succeeded(Equals([])))

        # Nothing stored, nothing notified
        assert_that(self.cert_store.as_dict(), succeeded(Equals({})))
        assert_that(self.fake_marathon_lb.check_signalled_usr1(),
                    Equals(False))

    def test_sync_app_no_domains(self):
        """
        When a sync is run and Marathon has an app but that app has no
        marathon-acme domains, then no certificates should be fetched and
        marathon-lb should not be notified.
        """
        self.fake_marathon.add_app({
            'id': '/my-app_1',
            'labels': {
                'HAPROXY_0_VHOST': 'example.com'
            },
            'portDefinitions': [
                {'port': 9000, 'protocol': 'tcp', 'labels': {}}
            ]
        })

        d = self.marathon_acme.sync()
        assert_that(d, succeeded(Equals([])))

        # Nothing stored, nothing notified
        assert_that(self.cert_store.as_dict(), succeeded(Equals({})))
        assert_that(self.fake_marathon_lb.check_signalled_usr1(),
                    Equals(False))

    def test_sync_app_group_mismatch(self):
        """
        When a sync is run and Marathon has an app but that app has a different
        group to the one marathon-acme is configured with, then no certificates
        should be fetched and marathon-lb should not be notified.
        """
        self.fake_marathon.add_app({
            'id': '/my-app_1',
            'labels': {
                'HAPROXY_GROUP': 'internal',
                'HAPROXY_0_VHOST': 'example.com',
                'MARATHON_ACME_0_DOMAIN': 'example.com',
            },
            'portDefinitions': [
                {'port': 9000, 'protocol': 'tcp', 'labels': {}}
            ]
        })

        d = self.marathon_acme.sync()
        assert_that(d, succeeded(Equals([])))

        # Nothing stored, nothing notified
        assert_that(self.cert_store.as_dict(), succeeded(Equals({})))
        assert_that(self.fake_marathon_lb.check_signalled_usr1(),
                    Equals(False))

    def test_sync_app_port_group_mismatch(self):
        """
        When a sync is run and Marathon has an app and that app has a matching
        group but mismatching port group, then no certificates should be
        fetched and marathon-lb should not be notified.
        """
        self.fake_marathon.add_app({
            'id': '/my-app_1',
            'labels': {
                'HAPROXY_GROUP': 'external',
                'HAPROXY_0_GROUP': 'internal',
                'HAPROXY_0_VHOST': 'example.com',
                'MARATHON_ACME_0_DOMAIN': 'example.com',
            },
            'portDefinitions': [
                {'port': 9000, 'protocol': 'tcp', 'labels': {}}
            ]
        })

        d = self.marathon_acme.sync()
        assert_that(d, succeeded(Equals([])))

        # Nothing stored, nothing notified
        assert_that(self.cert_store.as_dict(), succeeded(Equals({})))
        assert_that(self.fake_marathon_lb.check_signalled_usr1(),
                    Equals(False))

    def test_sync_app_existing_cert(self):
        """
        When a sync is run and Marathon has an app with a domain label but we
        already have a certificate for that app then a new certificate should
        not be fetched.
        """
        self.fake_marathon.add_app({
            'id': '/my-app_1',
            'labels': {
                'HAPROXY_GROUP': 'external',
                'MARATHON_ACME_0_DOMAIN': 'example.com'
            },
            'portDefinitions': [
                {'port': 9000, 'protocol': 'tcp', 'labels': {}}
            ]
        })
        self.cert_store.store('example.com', 'certcontent')

        d = self.marathon_acme.sync()
        assert_that(d, succeeded(Equals([])))

        # Existing cert unchanged, marathon-lb not notified
        assert_that(self.cert_store.as_dict(), succeeded(
            Equals({'example.com': 'certcontent'})))
        assert_that(self.fake_marathon_lb.check_signalled_usr1(),
                    Equals(False))

    def test_listen_event(self):
        """
        When Marathon events are listened for, and an action (adding an app) in
        Marathon triggers an ``api_post_event``, a sync should be run.
        """
        self.marathon_acme.listen_events()

        # Add an app to trigger an event
        self.fake_marathon.add_app({
            'id': '/my-app_1',
            'labels': {
                'HAPROXY_GROUP': 'external',
                'MARATHON_ACME_0_DOMAIN': 'example.com'
            },
            'portDefinitions': [
                {'port': 9000, 'protocol': 'tcp', 'labels': {}}
            ]
        })

        # Flush the client to make sure the event is received
        self.marathon_inner_client.flush()

        assert_that(self.cert_store.as_dict(), succeeded(MatchesDict({
            'example.com': Not(Is(None))
        })))
        assert_that(self.fake_marathon_lb.check_signalled_usr1(), Equals(True))
