import argparse
import ipaddress
import os
import sys

from twisted.internet.endpoints import quoteStringArgument
from twisted.internet.task import react
from twisted.logger import (
    FilteringLogObserver, LogLevel, LogLevelFilterPredicate, Logger,
    globalLogPublisher, textFileLogObserver)
from twisted.python.compat import unicode
from twisted.python.filepath import FilePath
from twisted.python.url import URL

from txacme.store import DirectoryStore
from txacme.urls import LETSENCRYPT_DIRECTORY

from marathon_acme import __version__
from marathon_acme.acme_util import (
    create_txacme_client_creator, generate_wildcard_pem_bytes, maybe_key,
    maybe_key_vault)
from marathon_acme.clients import MarathonClient, MarathonLbClient, VaultClient
from marathon_acme.service import MarathonAcme
from marathon_acme.vault_store import VaultKvCertificateStore


log = Logger()


def main(reactor, argv=sys.argv[1:], env=os.environ,
         acme_url=LETSENCRYPT_DIRECTORY.asText()):
    """
    A tool to automatically request, renew and distribute Let's Encrypt
    certificates for apps running on Marathon and served by marathon-lb.
    """
    parser = argparse.ArgumentParser(
        description='Automatically manage ACME certificates for Marathon apps')
    parser.add_argument('-a', '--acme',
                        help='The address for the ACME Directory Resource '
                             '(default: %(default)s)',
                        default=acme_url)
    parser.add_argument('-e', '--email',
                        help='An email address to register with the ACME '
                             'service (optional)')
    parser.add_argument('-m', '--marathon', metavar='MARATHON[,MARATHON,...]',
                        help='The addresses for the Marathon HTTP API '
                             '(default: %(default)s)',
                        default='http://marathon.mesos:8080')
    parser.add_argument('-l', '--lb', metavar='LB[,LB,...]',
                        help='The addresses for the marathon-lb HTTP API '
                             '(default: %(default)s)',
                        default='http://marathon-lb.marathon.mesos:9090')
    parser.add_argument('-g', '--group',
                        help='The marathon-lb group to issue certificates for '
                             '(default: %(default)s)',
                        default='external')
    parser.add_argument('--allow-multiple-certs',
                        help=('Allow multiple certificates for a single app '
                              'port. This allows multiple domains for an app, '
                              'but is not recommended.'),
                        action='store_true')
    parser.add_argument('--listen',
                        help='The address for the port to listen on (default: '
                             '%(default)s)',
                        default=':8000')
    parser.add_argument('--marathon-timeout',
                        help=('Amount of time in seconds to wait for HTTP '
                              'response headers to be received for all '
                              'requests to Marathon. Set to 0 to disable. '
                              '(default: %(default)s)'),
                        type=float,
                        default=10)
    parser.add_argument('--sse-timeout',
                        help=('Amount of time in seconds to wait for some '
                              'event data to be received from Marathon. Set '
                              'to 0 to disable. (default: %(default)s)'),
                        type=float,
                        default=60)
    parser.add_argument('--log-level',
                        help='The minimum severity level to log messages at '
                             '(default: %(default)s)',
                        choices=['debug', 'info', 'warn', 'error', 'critical'],
                        default='info'),
    parser.add_argument('--vault',
                        help=('Enable storage of certificates in Vault. This '
                              'can be further configured with VAULT_-style '
                              'environment variables.'),
                        action='store_true')
    parser.add_argument('storage_path', metavar='storage-path',
                        help=('Path for storing certificates. If --vault is '
                              'used then this is the mount path for the '
                              'key/value engine in Vault. If not, this is the '
                              'path to a directory.'))
    parser.add_argument('--version', action='version', version=__version__)

    args = parser.parse_args(argv)

    # Set up logging
    init_logging(args.log_level)

    # Set up marathon-acme
    marathon_addrs = args.marathon.split(',')
    mlb_addrs = args.lb.split(',')

    sse_timeout = args.sse_timeout if args.sse_timeout > 0 else None

    acme_url = URL.fromText(_to_unicode(args.acme))

    endpoint_description = parse_listen_addr(args.listen)

    log_args = [
        ('storage-path', args.storage_path),
        ('vault', args.vault),
        ('acme', acme_url),
        ('email', args.email),
        ('allow-multiple-certs', args.allow_multiple_certs),
        ('marathon', marathon_addrs),
        ('sse-timeout', sse_timeout),
        ('lb', mlb_addrs),
        ('group', args.group),
        ('endpoint-description', endpoint_description),
    ]
    log_args = ['{}={!r}'.format(k, v) for k, v in log_args]
    log.info('Starting marathon-acme {} with: {}'.format(
        __version__, ', '.join(log_args)))

    if args.vault:
        key_d, cert_store = init_vault_storage(
            reactor, env, args.storage_path)
    else:
        key_d, cert_store = init_file_storage(args.storage_path)

    # Once we have the client key, create the txacme client creator
    key_d.addCallback(create_txacme_client_creator, reactor, acme_url)

    # Once we have the client creator, create the service
    key_d.addCallback(
        create_marathon_acme, cert_store, args.email,
        args.allow_multiple_certs, marathon_addrs, args.marathon_timeout,
        sse_timeout, mlb_addrs, args.group, reactor)

    # Finally, run the thing
    return key_d.addCallback(lambda ma: ma.run(endpoint_description))


def _to_unicode(string):
    if isinstance(string, unicode):
        return string
    return unicode(string, sys.getfilesystemencoding())


def parse_listen_addr(listen_addr):
    """
    Parse an address of the form [ipaddress]:port into a tcp or tcp6 Twisted
    endpoint description string for use with
    ``twisted.internet.endpoints.serverFromString``.
    """
    if ':' not in listen_addr:
        raise ValueError(
            "'%s' does not have the correct form for a listen address: "
            '[ipaddress]:port' % (listen_addr,))
    host, port = listen_addr.rsplit(':', 1)

    # Validate the host
    if host == '':
        protocol = 'tcp'
        interface = None
    else:
        if host.startswith('[') and host.endswith(']'):  # IPv6 wrapped in []
            host = host[1:-1]
        ip_address = ipaddress.ip_address(_to_unicode(host))
        protocol = 'tcp6' if ip_address.version == 6 else 'tcp'
        interface = str(ip_address)

    # Validate the port
    if not port.isdigit() or int(port) < 1 or int(port) > 65535:
        raise ValueError(
            "'%s' does not appear to be a valid port number" % (port,))

    args = [protocol, port]
    kwargs = {'interface': interface} if interface is not None else {}

    return _create_tx_endpoints_string(args, kwargs)


def _create_tx_endpoints_string(args, kwargs):
    _kwargs = (
        ['='.join((k, quoteStringArgument(v))) for k, v in kwargs.items()])
    return ':'.join(args + _kwargs)


def create_marathon_acme(
    client_creator, cert_store, acme_email, allow_multiple_certs,
    marathon_addrs, marathon_timeout, sse_timeout, mlb_addrs, group,
        reactor):
    """
    Create a marathon-acme instance.

    :param client_creator:
        The txacme client creator function.
    :param cert_store:
        The txacme certificate store instance.
    :param acme_email:
        Email address to use when registering with the ACME service.
    :param allow_multiple_certs:
        Whether to allow multiple certificates per app port.
    :param marathon_addr:
        Address for the Marathon instance to find app domains that require
        certificates.
    :param marathon_timeout:
        Amount of time in seconds to wait for response headers to be received
        from Marathon.
    :param sse_timeout:
        Amount of time in seconds to wait for some event data to be received
        from Marathon.
    :param mlb_addrs:
        List of addresses for marathon-lb instances to reload when a new
        certificate is issued.
    :param group:
        The marathon-lb group (``HAPROXY_GROUP``) to consider when finding
        app domains.
    :param reactor: The reactor to use.
    """
    marathon_client = MarathonClient(marathon_addrs, timeout=marathon_timeout,
                                     sse_kwargs={'timeout': sse_timeout},
                                     reactor=reactor)
    marathon_lb_client = MarathonLbClient(mlb_addrs, reactor=reactor)

    return MarathonAcme(
        marathon_client,
        group,
        cert_store,
        marathon_lb_client,
        client_creator,
        reactor,
        acme_email,
        allow_multiple_certs
    )


def init_storage_dir(storage_dir):
    """
    Initialise the storage directory with the certificates directory and a
    default wildcard self-signed certificate for HAProxy.

    :return: the storage path and certs path
    """
    storage_path = FilePath(storage_dir)

    # Create the default wildcard certificate if it doesn't already exist
    default_cert_path = storage_path.child('default.pem')
    if not default_cert_path.exists():
        default_cert_path.setContent(generate_wildcard_pem_bytes())

    # Create a directory for unmanaged certs. We don't touch this again, but it
    # needs to be there and it makes sense to create it at the same time as
    # everything else.
    unmanaged_certs_path = storage_path.child('unmanaged-certs')
    if not unmanaged_certs_path.exists():
        unmanaged_certs_path.createDirectory()

    # Store certificates in a directory inside the storage directory, so
    # HAProxy will read just the certificates there.
    certs_path = storage_path.child('certs')
    if not certs_path.exists():
        certs_path.createDirectory()

    return storage_path, certs_path


def init_logging(log_level):
    """
    Initialise the logging by adding an observer to the global log publisher.

    :param str log_level: The minimum log level to log messages for.
    """
    log_level_filter = LogLevelFilterPredicate(
        LogLevel.levelWithName(log_level))
    log_level_filter.setLogLevelForNamespace(
        'twisted.web.client._HTTP11ClientFactory', LogLevel.warn)
    log_observer = FilteringLogObserver(
        textFileLogObserver(sys.stdout), [log_level_filter])
    globalLogPublisher.addObserver(log_observer)


def init_vault_storage(reactor, env, mount_path):
    vault_client = VaultClient.from_env(reactor=reactor, env=env)
    cert_store = VaultKvCertificateStore(vault_client, mount_path)
    key_d = maybe_key_vault(vault_client, mount_path)
    return key_d, cert_store


def init_file_storage(storage_dir):
    storage_path, certs_path = init_storage_dir(storage_dir)
    cert_store = DirectoryStore(certs_path)
    key_d = maybe_key(storage_path)
    return key_d, cert_store


def _main():  # pragma: no cover
    react(main)


if __name__ == '__main__':  # pragma: no cover
    _main()
