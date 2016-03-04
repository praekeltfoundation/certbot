
from twisted.trial import unittest
from twisted.internet import defer

from certbot.service import CertbotService

class Test(unittest.TestCase):
    def test_lame(self):
        cls = CertbotService({})
