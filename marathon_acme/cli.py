import argparse
import sys

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


def main(raw_args=sys.argv[1:]):
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

    # Set up marathon-acme
    marathon_client = MarathonClient(args.marathon)
    group = args.group
    store_path = FilePath(args.storage_dir)
    cert_store = DirectoryStore(store_path)
    mlb_client = MarathonLbClient(args.lb)

    from twisted.internet import reactor
    clock = reactor

    def client_creator():
        acme_url = URL.fromText(args.acme)
        key = maybe_key(store_path)
        return txacme_Client.from_url(clock, acme_url, key)

    marathon_acme = MarathonAcme(
        marathon_client,
        group,
        cert_store,
        mlb_client,
        client_creator,
        clock)

    # Set up logging
    log_level_filter = LogLevelFilterPredicate(
        LogLevel.levelWithName(args.log_level))
    log_observer = FilteringLogObserver(
        textFileLogObserver(sys.stdout), [log_level_filter])
    globalLogPublisher.addObserver(log_observer)

    # Run the thing
    host, port = args.listen.split(':', 1)  # TODO: better validation
    marathon_acme.run(host, int(port))
    reactor.run()


if __name__ == '__main__':
    main()
