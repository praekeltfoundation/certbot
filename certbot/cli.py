import click
import sys


@click.command()
@click.option('--email',
              help='Email address for Let\'s Encrypt certificate registration '
                   'and recovery contact',
              required=True)
@click.option('--server',
              help='The address for the ACME Directory Resource',
              default='https://acme-v01.api.letsencrypt.org/directory',
              show_default=True)
@click.option('--storage-dir',
              help='Path to directory for storing certificates')
@click.option('--marathon', default='http://marathon.service.consul:8080',
              help='The address for the Marathon HTTP API',
              show_default=True)
@click.option('--listen',
              help='The address of the interface to bind to to receive '
                   'Marathon\'s event stream',
              default='0.0.0.0',
              show_default=True)
@click.option('--port', default='7000', type=int, show_default=True,
              help='The port to bind to to receive Marathon\'s event stream')
@click.option('--advertise', default='http://certbot.service.consul',
              help='The address to advertise to Marathon when registering for '
                   'the event stream',
              show_default=True)
@click.option('--consul', default='http://consul.service.consul:8500',
              help='The address for the Consul HTTP API',
              show_default=True)
@click.option('--consul-prefix', default='certbot',
              help='Prefix for all paths to certificates in Consul\'s '
                   'key/value store',
              show_default=True)
@click.option('--poll',
              help='Periodically sync Marathon\'s state with Consul\'s every '
                   '_n_ seconds [default: disabled]',
              type=int)
@click.option('--logfile',
              help='Where to log output to [default: stdout]',
              type=click.File('a'),
              default=sys.stdout)
@click.option('--debug',
              help='Log debug output',
              is_flag=True)
def main(email, server, storage_dir,         # Certificates
         marathon, listen, port, advertise,  # Marathon
         consul, consul_prefix, poll,        # Consul
         logfile, debug):                    # Logging
    """
    A tool to automatically request, renew and distribute Let's Encrypt
    certificates for apps running on Seed Stack.
    """
