from twisted.internet.defer import gatherResults
from twisted.logger import Logger, LogLevel
from twisted.python.failure import Failure
from txacme.challenges import HTTP01Responder
from txacme.client import ServerError as txacme_ServerError
from txacme.service import AcmeIssuingService

from marathon_acme.server import MarathonAcmeServer
from marathon_acme.acme_util import MlbCertificateStore


def parse_domain_label(domain_label):
    """ Parse the list of comma-separated domains from the app label. """
    domains = []
    for domain_string in domain_label.split(','):
        domain = domain_string.strip()
        if domain:
            domains.append(domain)
    return domains


class MarathonAcme(object):
    log = Logger()

    def __init__(self, marathon_client, group, cert_store, mlb_client,
                 txacme_client_creator, reactor, email=None):
        """
        Create the marathon-acme service.

        :param marathon_client: The Marathon API client.
        :param group: The name of the marathon-lb group.
        :param cert_store: The ``ICertificateStore`` instance to use.
        :param mlb_clinet: The marathon-lb API client.
        :param txacme_client_creator: Callable to create the txacme client.
        :param reactor: The reactor to use.
        :param email: The ACME registration email.
        """
        self.marathon_client = marathon_client
        self.group = group
        self.reactor = reactor

        responder = HTTP01Responder()
        self.server = MarathonAcmeServer(responder.resource)

        mlb_cert_store = MlbCertificateStore(cert_store, mlb_client)
        self.txacme_service = AcmeIssuingService(
            mlb_cert_store, txacme_client_creator, reactor, [responder], email)

        self._server_listening = None

    def run(self, endpoint_description):
        self.log.info('Starting marathon-acme...')

        # Start the server
        d = self.server.listen(self.reactor, endpoint_description)

        def on_server_listening(listening_port):
            self._server_listening = listening_port

            # Start the txacme service and wait for the initial check
            self.txacme_service.startService()
            return self.txacme_service.when_certs_valid()
        d.addCallback(on_server_listening)

        # Then listen for events...
        d.addCallback(lambda _: self.listen_events())

        # If anything goes wrong or listening for events returns, stop
        d.addBoth(self._stop)

        return d

    def _stop(self, result):
        if isinstance(result, Failure):
            self.log.failure('Unhandle error during operation', result)
        self.log.warn('Stopping marathon-acme...')

        # If the server failed to start we have nothing to cancel yet
        if self._server_listening is not None:
            return gatherResults([
                self._server_listening.stopListening(),
                self.txacme_service.stopService()
            ], consumeErrors=True)

    def listen_events(self, reconnects=0):
        """
        Start listening for events from Marathon, running a sync when we first
        successfully subscribe and triggering a sync on API request events.
        """
        self.log.info('Listening for events from Marathon...')
        self._attached = False

        def on_finished(result, reconnects):
            # If the callback fires then the HTTP request to the event stream
            # went fine, but the persistent connection for the SSE stream was
            # dropped. Just reconnect for now- if we can't actually connect
            # then the errback will fire rather.
            self.log.warn('Connection lost listening for events, '
                          'reconnecting... ({reconnects} so far)',
                          reconnects=reconnects)
            reconnects += 1
            return self.listen_events(reconnects)

        def log_failure(failure):
            self.log.failure('Failed to listen for events', failure)
            return failure

        return self.marathon_client.get_events({
            'event_stream_attached': self._sync_on_event_stream_attached,
            'api_post_event': self._sync_on_api_post_event
        }).addCallbacks(on_finished, log_failure, callbackArgs=[reconnects])

    def _sync_on_event_stream_attached(self, event):
        if self._attached:
            self.log.debug(
                'event_stream_attached event received (timestamp: '
                '"{timestamp}", remoteAddress: "{remoteAddress}"), but '
                'already attached', timestamp=event['timestamp'],
                remoteAddress=event['remoteAddress'])
            return

        self._attached = True
        self.log.info(
            'event_stream_attached event received (timestamp: "{timestamp}", '
            'remoteAddress: "{remoteAddress}"), running initial sync...',
            timestamp=event['timestamp'], remoteAddress=event['remoteAddress'])
        return self.sync()

    def _sync_on_api_post_event(self, event):
        self.log.info(
            'api_post_event event received (timestamp: "{timestamp}", uri: '
            '"{uri}"), triggering a sync...', timestamp=event['timestamp'],
            uri=event['uri'])
        return self.sync()

    def sync(self):
        """
        Fetch the list of apps from Marathon, find the domains that require
        certificates, and issue certificates for any domains that don't already
        have a certificate.
        """
        self.log.info('Starting a sync...')

        def log_success(result):
            self.log.info('Sync completed successfully')
            return result

        def log_failure(failure):
            self.log.failure('Sync failed', failure, LogLevel.error)
            return failure

        return (self.marathon_client.get_apps()
                .addCallback(self._apps_acme_domains)
                .addCallback(self._filter_new_domains)
                .addCallback(self._issue_certs)
                .addCallbacks(log_success, log_failure))

    def _apps_acme_domains(self, apps):
        domains = []
        for app in apps:
            domains.extend(self._app_acme_domains(app))

        self.log.debug('Found {len_domains} domains for apps: {domains}',
                       len_domains=len(domains), domains=domains)

        return domains

    def _app_acme_domains(self, app):
        app_domains = []
        labels = app['labels']
        app_group = labels.get('HAPROXY_GROUP')

        # Prefer the 'portDefinitions' field added in Marathon 1.0.0 but fall
        # back to the deprecated 'ports' array if that's not present.
        if 'portDefinitions' in app:
            ports = app['portDefinitions']
        else:
            ports = app['ports']

        # Iterate through the ports, checking for corresponding labels
        for port_index, _ in enumerate(ports):
            # Get the port group label, defaulting to the app group label
            port_group = labels.get(
                'HAPROXY_%d_GROUP' % (port_index,), app_group)

            if port_group == self.group:
                domain_label = labels.get(
                    'MARATHON_ACME_%d_DOMAIN' % (port_index,), '')
                port_domains = parse_domain_label(domain_label)

                if port_domains:
                    # TODO: Support SANs- for now just use the first domain
                    if len(port_domains) > 1:
                        self.log.warn(
                            'Multiple domains found for port {port} of app '
                            '{app}, only the first will be used',
                            port=port_index, app=app['id'])

                    app_domains.append(port_domains[0])

        self.log.debug(
            'Found {len_domains} domains for app {app}: {domains}',
            len_domains=len(app_domains), app=app['id'], domains=app_domains)

        return app_domains

    def _filter_new_domains(self, marathon_domains):
        def filter_domains(stored_domains):
            return set(marathon_domains) - set(stored_domains.keys())

        d = self.txacme_service.cert_store.as_dict()
        d.addCallback(filter_domains)
        return d

    def _issue_certs(self, domains):
        if domains:
            self.log.info(
                'Issuing certificates for {len_domains} domains: {domains}',
                len_domains=len(domains), domains=domains)
        else:
            self.log.debug('No new domains to issue certificates for')
        return gatherResults([self._issue_cert(domain) for domain in domains])

    def _issue_cert(self, domain):
        """
        Issue a certificate for the given domain.
        """
        def errback(failure):
            # Don't fail on some of the errors we could get from the ACME
            # server, rather just log an error so that we can continue with
            # other domains.
            failure.trap(txacme_ServerError)
            acme_error = failure.value.message

            if acme_error.code in ['rateLimited', 'serverInternal',
                                   'connection', 'unknownHost']:
                # TODO: Fire off an error to Sentry or something?
                self.log.error(
                    'Error ({code}) issuing certificate for "{domain}": '
                    '{detail}', code=acme_error.code, domain=domain,
                    detail=acme_error.detail)
            else:
                # There are more error codes but if they happen then something
                # serious has gone wrong-- carry on error-ing.
                return failure

        d = self.txacme_service.issue_cert(domain)
        return d.addErrback(errback)
