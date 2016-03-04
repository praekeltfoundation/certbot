"""Certbot - A robot for managing letsencrypt certs

.. moduleauthor:: Colin Alston <colin@praekelt.com>

"""

from certbot import service


def makeService(config):
    # Create CertbotService
    return service.CertbotService(config)
