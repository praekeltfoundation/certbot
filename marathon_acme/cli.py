import argparse
import ipaddress
import sys

from twisted.internet.endpoints import quoteStringArgument
from twisted.internet.task import react
from twisted.logger import (
    FilteringLogObserver, globalLogPublisher, Logger, LogLevel,
    LogLevelFilterPredicate, textFileLogObserver)
from twisted.python.compat import unicode
from twisted.python.filepath import FilePath
from twisted.python.url import URL
from txacme.store import DirectoryStore

from marathon_acme.acme_util import (
    create_txacme_client_creator, generate_wildcard_pem_bytes, maybe_key)
from marathon_acme.clients import MarathonClient, MarathonLbClient
from marathon_acme.service import MarathonAcme


log = Logger()

parser = argparse.ArgumentParser(
    description='Automatically manage ACME certificates for Marathon apps')
parser.add_argument('-a', '--acme',
                    help='The address for the ACME Directory Resource '
                         '(default: %(default)s)',
                    default=(
                        'https://acme-v01.api.letsencrypt.org/directory'))
parser.add_argument('-e', '--email',
                    help='An email address to register with the ACME service '
                         '(optional)')
parser.add_argument('-m', '--marathon', metavar='MARATHON[,MARATHON,...]',
                    help='The addresses for the Marathon HTTP API (default: '
                         '%(default)s)',
                    default='http://marathon.mesos:8080')
parser.add_argument('-l', '--lb', metavar='LB[,LB,...]',
                    help='The addresses for the marathon-lb HTTP API '
                         '(default: %(default)s)',
                    default='http://marathon-lb.marathon.mesos:9090')
parser.add_argument('-g', '--group',
                    help='The marathon-lb group to issue certificates for '
                         '(default: %(default)s)',
                    default='external')
parser.add_argument('--listen',
                    help='The address for the port to listen on (default: '
                         '%(default)s)',
                    default=':8000')
parser.add_argument('--log-level',
                    help='The minimum severity level to log messages at '
                         '(default: %(default)s)',
                    choices=['debug', 'info', 'warn', 'error', 'critical'],
                    default='info'),
parser.add_argument('storage_dir', metavar='storage-dir',
                    help='Path to directory for storing certificates')


def main(reactor, raw_args=sys.argv[1:]):
    """
    A tool to automatically request, renew and distribute Let's Encrypt
    certificates for apps running on Marathon and served by marathon-lb.
    """
    args = parser.parse_args(raw_args)

    # Set up logging
    init_logging(args.log_level)

    # Set up marathon-acme
    marathon_addrs = args.marathon.split(',')
    mlb_addrs = args.lb.split(',')

    marathon_acme = create_marathon_acme(
        args.storage_dir, args.acme, args.email,
        marathon_addrs, mlb_addrs, args.group,
        reactor)

    # Run the thing
    endpoint_description = parse_listen_addr(args.listen)

    log.info('Running marathon-acme with: storage-dir="{storage_dir}", '
             'acme="{acme}", email="{email}", marathon={marathon_addrs}, '
             'lb={mlb_addrs}, group="{group}", '
             'endpoint_description="{endpoint_desc}", ',
             storage_dir=args.storage_dir, acme=args.acme, email=args.email,
             marathon_addrs=marathon_addrs, mlb_addrs=mlb_addrs,
             group=args.group, endpoint_desc=endpoint_description)

    return marathon_acme.run(endpoint_description)


def _to_unicode(string):
    if isinstance(string, unicode):
        return string
    elif isinstance(string, bytes):
        return unicode(string, 'utf-8')


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


def create_marathon_acme(storage_dir, acme_directory, acme_email,
                         marathon_addrs, mlb_addrs, group,
                         reactor):
    """
    Create a marathon-acme instance.

    :param storage_dir:
        Path to the storage directory for certificates and the client key.
    :param acme_directory: Address for the ACME directory to use.
    :param acme_email:
        Email address to use when registering with the ACME service.
    :param marathon_addr:
        Address for the Marathon instance to find app domains that require
        certificates.
    :param mlb_addrs:
        List of addresses for marathon-lb instances to reload when a new
        certificate is issued.
    :param group:
        The marathon-lb group (``HAPROXY_GROUP``) to consider when finding
        app domains.
    :param reactor: The reactor to use.
    """
    storage_path, certs_path = init_storage_dir(storage_dir)
    acme_url = URL.fromText(_to_unicode(acme_directory))
    key = maybe_key(storage_path)

    return MarathonAcme(
        MarathonClient(marathon_addrs, reactor=reactor),
        group,
        DirectoryStore(certs_path),
        MarathonLbClient(mlb_addrs, reactor=reactor),
        create_txacme_client_creator(reactor, acme_url, key),
        reactor,
        acme_email)


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


def _main():
    react(main)


if __name__ == '__main__':
    _main()
