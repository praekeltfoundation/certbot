import argparse
import sys


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
    parser.add_argument('--log-level',
                        help='The minimum severity level to log messages at '
                             '(default: %(default)s)',
                        choices=['debug', 'info', 'warn', 'error', 'critical'],
                        default='info'),
    parser.add_argument('storage-dir',
                        help='Path to directory for storing certificates')

    args = parser.parse_args(raw_args)  # noqa


if __name__ == '__main__':
    main()
