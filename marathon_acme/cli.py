import click
import sys


@click.command()
@click.option('--acme',
              help='The address for the ACME Directory Resource',
              default='https://acme-v01.api.letsencrypt.org/directory',
              show_default=True)
@click.option('--email',
              help=("Email address for Let's Encrypt certificate registration "
                    "and recovery contact"),
              required=True)
@click.option('--storage-dir',
              help='Path to directory for storing certificates')
@click.option('--marathon', default='http://marathon.mesos:8080',
              help='The address for the Marathon HTTP API',
              show_default=True)
@click.option('--poll',
              help=("Periodically check Marathon's state every _n_ seconds "
                    "[default: disabled]"),
              type=int)
@click.option('--logfile',
              help='Where to log output to [default: stdout]',
              type=click.File('a'),
              default=sys.stdout)
@click.option('--debug',
              help='Log debug output',
              is_flag=True)
def main(acme, email, storage_dir,  # ACME/certificates
         marathon, poll,            # Marathon
         logfile, debug):           # Logging
    """
    A tool to automatically request, renew and distribute Let's Encrypt
    certificates for apps running on Seed Stack.
    """
