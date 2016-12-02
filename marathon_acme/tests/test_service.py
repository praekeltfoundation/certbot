from datetime import datetime

from acme import challenges
from acme.jose import JWKRSA
from acme.messages import Error as acme_Error
from testtools.assertions import assert_that
from testtools.matchers import (
    AfterPreprocessing, Equals, HasLength, Is, IsInstance, MatchesAll,
    MatchesDict, MatchesListwise, MatchesPredicate, MatchesStructure, Not)
from testtools.twistedsupport import failed, succeeded
from twisted.internet.defer import succeed
from twisted.internet.task import Clock
from txacme.client import ServerError as txacme_ServerError
from txacme.testing import FakeClient, MemoryStore
from txacme.util import generate_private_key

from marathon_acme.clients import MarathonClient, MarathonLbClient
from marathon_acme.service import MarathonAcme, parse_domain_label
from marathon_acme.tests.fake_marathon import (
    FakeMarathon, FakeMarathonAPI, FakeMarathonLb)
from marathon_acme.tests.helpers import failing_client


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


class FailableTxacmeClient(FakeClient):
    """
    A fake txacme client that raises an error during the CSR issuance phase if
    the 'error' attribute has been set. Used to very *very* roughly simulate
    an error while issuing a certificate.
    """

    def __init__(self, *args, **kwargs):
        super(FailableTxacmeClient, self).__init__(*args, **kwargs)
        # Patch on support for HTTP challenge types
        self._challenge_types.append(challenges.HTTP01)
        self.issuance_error = None

    def request_issuance(self, csr):
        if self.issuance_error is not None:
            # Server error takes an ACME error and a treq response...but we
            # don't have a response
            raise self.issuance_error
        return super(FailableTxacmeClient, self).request_issuance(csr)


class TestMarathonAcme(object):

    def setup_method(self):
        self.fake_marathon = FakeMarathon()
        self.fake_marathon_api = FakeMarathonAPI(self.fake_marathon)
        marathon_client = MarathonClient(
            ['http://localhost:8080'], client=self.fake_marathon_api.client)

        self.cert_store = MemoryStore()

        self.fake_marathon_lb = FakeMarathonLb()
        mlb_client = MarathonLbClient(
            ['http://localhost:9090'], client=self.fake_marathon_lb.client)

        key = JWKRSA(key=generate_private_key(u'rsa'))
        clock = Clock()
        clock.rightNow = (
            datetime.now() - datetime(1970, 1, 1)).total_seconds()
        self.txacme_client = FailableTxacmeClient(key, clock)

        self.marathon_acme = MarathonAcme(
            marathon_client,
            'external',
            self.cert_store,
            mlb_client,
            lambda: succeed(self.txacme_client),
            clock
        )

    def test_listen_events_attach_initial_sync(self):
        """
        When we listen for events from Marathon, and we receive a subscribe
        event from ourselves subscribing, an initial sync should be performed
        and certificates issued for any new domains.
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

        self.marathon_acme.listen_events()

        # Observe that the certificate was stored and marathon-lb notified
        assert_that(self.cert_store.as_dict(), succeeded(MatchesDict({
            'example.com': Not(Is(None))
        })))
        assert_that(self.fake_marathon_lb.check_signalled_usr1(), Equals(True))

    def test_listen_events_attach_only_first(self):
        """
        When we're listening for events and receive multiple
        ``event_stream_attached`` events, only the first received event should
        trigger the initial sync.
        """
        self.marathon_acme.listen_events()

        # First attach event is from ourselves attaching...
        assert_that(
            self.fake_marathon_api.check_called_get_apps(), Equals(True))

        # Some other client attaches
        other_client = MarathonClient(
            ['http://localhost:8080'], client=self.fake_marathon_api.client)
        other_client_events = []
        other_client.get_events(
            {'event_stream_attached': other_client_events.append})

        # Make very sure that two clients are attached and event sent
        assert_that(other_client_events, HasLength(1))
        assert_that(self.fake_marathon_api.event_requests, HasLength(2))

        # No second sync from marathon-acme
        assert_that(
            self.fake_marathon_api.check_called_get_apps(), Equals(False))

    def test_listen_events_api_request_triggers_sync(self):
        """
        When we listen for events from Marathon, and something happens that
        triggers an API request event, a sync should be performed and
        certificates issued for any new domains.
        """
        self.marathon_acme.listen_events()

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

        # Observe that the certificate was stored and marathon-lb notified
        assert_that(self.cert_store.as_dict(), succeeded(MatchesDict({
            'example.com': Not(Is(None))
        })))
        assert_that(self.fake_marathon_lb.check_signalled_usr1(), Equals(True))

        # Try one more app
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

        assert_that(self.cert_store.as_dict(), succeeded(MatchesDict({
            'example.com': Not(Is(None)),
            'example2.com': Not(Is(None)),
        })))
        assert_that(self.fake_marathon_lb.check_signalled_usr1(), Equals(True))

    def test_listen_events_reconnects(self):
        """
        When we listen for events, and we connect successfully but the
        persistent connection drops, we should reconnect to the event stream
        and be able to receive new events.
        """
        self.marathon_acme.listen_events()

        # Trigger a lost connection
        requests = self.fake_marathon_api.event_requests
        assert_that(requests, HasLength(1))
        request = requests[0]

        request.loseConnection()
        self.fake_marathon_api.client.flush()

        # Check a new request has been made
        requests = self.fake_marathon_api.event_requests
        assert_that(requests, HasLength(1))
        new_request = requests[0]

        # Make sure this is, in fact, another request
        assert_that(new_request, Not(Is(request)))

        # Check that apps will sync
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
        assert_that(self.cert_store.as_dict(), succeeded(MatchesDict({
            'example.com': Not(Is(None))
        })))
        assert_that(self.fake_marathon_lb.check_signalled_usr1(), Equals(True))

    def test_listen_events_syncs_each_reconnect(self):
        """
        When we're listening for events and receive multiple
        ``event_stream_attached`` events, each reconnect should trigger another
        sync as we re-attach.
        """
        self.marathon_acme.listen_events()

        # Check the initial sync happens
        assert_that(
            self.fake_marathon_api.check_called_get_apps(), Equals(True))

        # Trigger a lost connection
        requests = self.fake_marathon_api.event_requests
        assert_that(requests, HasLength(1))
        request = requests[0]

        request.loseConnection()
        self.fake_marathon_api.client.flush()

        # We reconnect and another sync should occur as we re-attach
        assert_that(
            self.fake_marathon_api.check_called_get_apps(), Equals(True))

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

    def test_sync_app_no_port_definitions(self):
        """
        When a sync is run and this Marathon doesn't return the
        'portDefinitions' field with the app definitions, the 'ports' field
        should be used instead and a regular sync is completed.
        """
        # Store an app in Marathon with a marathon-acme domain
        self.fake_marathon.add_app({
            'id': '/my-app_1',
            'labels': {
                'HAPROXY_GROUP': 'external',
                'MARATHON_ACME_0_DOMAIN': 'example.com'
            },
            'ports': [10007]  # Some random service port
        })

        d = self.marathon_acme.sync()
        assert_that(d, succeeded(MatchesListwise([  # Per domain
            is_marathon_lb_sigusr_response
        ])))

        assert_that(self.cert_store.as_dict(), succeeded(MatchesDict({
            'example.com': Not(Is(None))
        })))

        assert_that(self.fake_marathon_lb.check_signalled_usr1(), Equals(True))

    def test_sync_app_port_definitions_preferred(self):
        """
        When a sync is run and this Marathon returns both the
        'portDefinitions' field and 'ports' field with the app definitions,
        the 'portsDefinition' field should be used and 'ports' ignored.
        """
        # Store an app in Marathon with a marathon-acme domain
        self.fake_marathon.add_app({
            'id': '/my-app_1',
            'labels': {
                'HAPROXY_GROUP': 'external',
                'MARATHON_ACME_0_DOMAIN': 'example.com'
            },
            'portDefinitions': [
                {'port': 9000, 'protocol': 'tcp', 'labels': {}},
                {'port': 9001, 'protocol': 'tcp', 'labels': {}}
            ],
            # There should never be a different number of elements in
            # 'portDefinitions' and 'ports' but 'ports' is deprecated and we
            # want to make sure it is ignored if 'portDefinitions' is present
            'ports': []
        })

        d = self.marathon_acme.sync()
        assert_that(d, succeeded(MatchesListwise([  # Per domain
            is_marathon_lb_sigusr_response
        ])))

        assert_that(self.cert_store.as_dict(), succeeded(MatchesDict({
            'example.com': Not(Is(None))
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

        # Nothing stored, nothing notified, but Marathon checked
        assert_that(
            self.fake_marathon_api.check_called_get_apps(), Equals(True))
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

        # Nothing stored, nothing notified, but Marathon checked
        assert_that(
            self.fake_marathon_api.check_called_get_apps(), Equals(True))
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

        # Nothing stored, nothing notified, but Marathon checked
        assert_that(
            self.fake_marathon_api.check_called_get_apps(), Equals(True))
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

        # Nothing stored, nothing notified, but Marathon checked
        assert_that(
            self.fake_marathon_api.check_called_get_apps(), Equals(True))
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

        # Existing cert unchanged, marathon-lb not notified, but Marathon
        # checked
        assert_that(
            self.fake_marathon_api.check_called_get_apps(), Equals(True))
        assert_that(self.cert_store.as_dict(), succeeded(
            Equals({'example.com': 'certcontent'})))
        assert_that(self.fake_marathon_lb.check_signalled_usr1(),
                    Equals(False))

    def test_sync_failure(self):
        """
        When a sync is run and something fails, the failure is propagated to
        the sync's deferred.
        """
        self.marathon_acme.marathon_client = MarathonClient(
            'http://localhost:8080', client=failing_client)

        d = self.marathon_acme.sync()
        assert_that(d, failed(MatchesStructure(
            value=IsInstance(RuntimeError))))

    def test_sync_acme_server_failure_acceptable(self):
        """
        When a sync is run and we try to issue a certificate for a domain but
        the ACME server returns an error, if that error is of an acceptable
        type then it should be ignored.
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
        acme_error = acme_Error(typ='urn:acme:error:rateLimited', detail='bar')
        # Server error takes an ACME error and a treq response...but we don't
        # have a response
        self.txacme_client.issuance_error = txacme_ServerError(
            acme_error, None)

        d = self.marathon_acme.sync()

        assert_that(d, succeeded(Equals([None])))
        # Nothing stored, nothing notified
        assert_that(self.cert_store.as_dict(), succeeded(Equals({})))
        assert_that(self.fake_marathon_lb.check_signalled_usr1(),
                    Equals(False))

    def test_sync_acme_server_failure_unacceptable(self):
        """
        When a sync is run and we try to issue a certificate for a domain but
        the ACME server returns an error, if that error is of an unacceptable
        type then a failure should be returned.
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
        acme_error = acme_Error(typ='urn:acme:error:badCSR', detail='bar')
        # Server error takes an ACME error and a treq response...but we don't
        # have a response
        self.txacme_client.issuance_error = txacme_ServerError(
            acme_error, None)

        d = self.marathon_acme.sync()

        # Oh god
        assert_that(d, failed(MatchesStructure(
            value=MatchesStructure(subFailure=MatchesStructure(
                value=MatchesAll(IsInstance(txacme_ServerError),
                    MatchesStructure(message=MatchesAll(
                        IsInstance(acme_Error),
                        MatchesStructure(
                            typ=Equals('urn:acme:error:badCSR'),
                            detail=Equals('bar')
                        )
                    ))
                )
            ))
        )))
        # Nothing stored, nothing notified
        assert_that(self.cert_store.as_dict(), succeeded(Equals({})))
        assert_that(self.fake_marathon_lb.check_signalled_usr1(),
                    Equals(False))

    def test_sync_other_issue_failure(self):
        """
        When a sync is run and we try to issue a certificate for a domain but
        some non-ACME server error occurs, the sync should fail.
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
        self.txacme_client.issuance_error = RuntimeError('Something bad')

        d = self.marathon_acme.sync()

        assert_that(d, failed(MatchesStructure(
            value=MatchesStructure(subFailure=MatchesStructure(
                value=MatchesAll(
                    IsInstance(RuntimeError),
                    MatchesPredicate(str, 'Something bad')
                )
            ))
        )))
        # Nothing stored, nothing notified
        assert_that(self.cert_store.as_dict(), succeeded(Equals({})))
        assert_that(self.fake_marathon_lb.check_signalled_usr1(),
                    Equals(False))
