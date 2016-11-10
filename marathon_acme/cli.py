import argparse
import sys

from twisted.internet.task import react
from twisted.logger import (
    FilteringLogObserver, globalLogPublisher, LogLevel,
    LogLevelFilterPredicate, textFileLogObserver)
from twisted.python.filepath import FilePath
from twisted.python.url import URL
from txacme.client import Client as txacme_Client
from txacme.store import DirectoryStore

from marathon_acme.acme_util import maybe_key
from marathon_acme.clients import MarathonClient, MarathonLbClient
from marathon_acme.service import MarathonAcme


def main(reactor, raw_args=sys.argv[1:]):
    """
    A tool to automatically request, renew and distribute Let's Encrypt
    certificates for apps running on Marathon and served by marathon-lb.
    """
    parser = argparse.ArgumentParser(
        description='Automatically manage ACME certificates for Marathon apps')
    parser.add_argument('-a', '--acme',
                        help='The address for the ACME Directory Resource '
                             '(default: %(default)s)',
                        default=(
                            'https://acme-v01.api.letsencrypt.org/directory'))
    parser.add_argument('-m', '--marathon',
                        help='The address for the Marathon HTTP API (default: '
                             '%(default)s)',
                        default='http://marathon.mesos:8080')
    parser.add_argument('-l', '--lb', nargs='+',
                        help='The address for the marathon-lb HTTP API '
                             '(default: %(default)s)',
                        default='http://marathon-lb.marathon.mesos:9090')
    parser.add_argument('-g', '--group',
                        help='The marathon-lb group to issue certificates for '
                             '(default: %(default)s)',
                        default='external')
    parser.add_argument('--listen',
                        help='The address for the port to listen on (default: '
                             '%(default)s)',
                        default='0.0.0.0:8000')
    parser.add_argument('--log-level',
                        help='The minimum severity level to log messages at '
                             '(default: %(default)s)',
                        choices=['debug', 'info', 'warn', 'error', 'critical'],
                        default='info'),
    parser.add_argument('storage_dir', metavar='storage-dir',
                        help='Path to directory for storing certificates')

    args = parser.parse_args(raw_args)

    # Set up logging
    init_logging(args.log_level)

    # Set up marathon-acme
    marathon_acme = create_marathon_acme(
        args.storage_dir, args.acme,
        args.marathon, args.lb, args.group,
        reactor)

    # Run the thing
    host, port = args.listen.split(':', 1)  # TODO: better validation
    return marathon_acme.run(host, int(port))


def create_marathon_acme(storage_dir, acme_directory,
                         marathon_addr, mlb_addrs, group,
                         reactor):
    """
    Create a marathon-acme instance.

    :param storage_dir:
        Path to the storage directory for certificates and the client key.
    :param acme_directory: Address for the ACME directory to use.
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
    store_path = FilePath(storage_dir)

    def client_creator():
        acme_url = URL.fromText(acme_directory)
        key = maybe_key(store_path)
        return txacme_Client.from_url(reactor, acme_url, key)

    return MarathonAcme(
        MarathonClient(marathon_addr, reactor=reactor),
        group,
        DirectoryStore(store_path),
        MarathonLbClient(mlb_addrs, reactor=reactor),
        client_creator,
        reactor)


def init_logging(log_level):
    """
    Initialise the logging by adding an observer to the global log publisher.

    :param str log_level: The minimum log level to log messages for.
    """
    log_level_filter = LogLevelFilterPredicate(
        LogLevel.levelWithName(log_level))
    log_observer = FilteringLogObserver(
        textFileLogObserver(sys.stdout), [log_level_filter])
    globalLogPublisher.addObserver(log_observer)


def _main():
    react(main)


if __name__ == '__main__':
    _main()
