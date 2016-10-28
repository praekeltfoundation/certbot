from twisted.internet.defer import gatherResults

from marathon_acme.server import HealthServer
from marathon_acme.acme_util import create_txacme_service


def parse_domain_label(domain_label):
    """ Parse the list of comma-separated domains from the app label. """
    domains = []
    for domain_string in domain_label.split(','):
        domain = domain_string.strip()
        if domain:
            domains.append(domain)
    return domains


class MarathonAcme(object):

    def __init__(self, marathon_client, group, cert_store, mlb_client,
                 txacme_client_creator, clock):
        """
        Create the marathon-acme service.

        :param marathon_client: The Marathon API client.
        :param group: The name of the marathon-lb group.
        :param cert_store: The ``ICertificateStore`` instance to use.
        :param mlb_clinet: The marathon-lb API client.
        :param txacme_client_creator: Callable to create the txacme client.
        :param clock: The ``IReactorTime`` provider.
        """
        self.marathon_client = marathon_client
        self.group = group

        self.server = HealthServer()

        root_resource = self.server.app.resource()
        self.txacme_service = create_txacme_service(
            cert_store, mlb_client, txacme_client_creator, clock,
            root_resource)

    def listen_events(self):
        """
        Listen for events from Marathon and run syncs when appropriate.
        """
        return self.marathon_client.get_events({
            'api_post_event': self._sync_on_event
        })

    def _sync_on_event(self, event):
        print('received event:', event)
        return self.sync()

    def sync(self):
        """
        Fetch the list of apps from Marathon, find the domains that require
        certificates, and issue certificates for any domains that don't already
        have a certificate.
        """
        return (self.marathon_client.get_apps()
                .addCallback(self._apps_acme_domains)
                .addCallback(self._filter_new_domains)
                .addCallback(self._issue_certs))

    def _apps_acme_domains(self, apps):
        domains = []
        for app in apps:
            domains.extend(self._app_acme_domains(app))

        return domains

    def _app_acme_domains(self, app):
        app_domains = []
        labels = app['labels']
        app_group = labels.get('HAPROXY_GROUP')

        # Iterate through the ports, checking for corresponding labels
        for port_index, _ in enumerate(app['portDefinitions']):
            # Get the port group label, defaulting to the app group label
            port_group = labels.get(
                'HAPROXY_%d_GROUP' % (port_index,), app_group)

            if port_group == self.group:
                domain_label = labels.get(
                    'MARATHON_ACME_%d_DOMAIN' % (port_index,), '')
                port_domains = parse_domain_label(domain_label)

                if port_domains:
                    # TODO: Support SANs- for now just use the first domain
                    app_domains.append(port_domains[0])

        return app_domains

    def _filter_new_domains(self, marathon_domains):
        def filter_domains(stored_domains):
            return set(marathon_domains) - set(stored_domains.keys())

        d = self.txacme_service.cert_store.as_dict()
        d.addCallback(filter_domains)
        return d

    def _issue_certs(self, domains):
        return gatherResults(
            [self.txacme_service.issue_cert(domain) for domain in domains])
