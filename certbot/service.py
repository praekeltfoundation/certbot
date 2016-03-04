
from twisted.application import service
from twisted.internet import task, reactor, defer
from twisted.python import log


class CertbotService(service.Service):
    def __init__(self, config):
        self.config = config 

    def startService(self):
        pass

    def stopService(self):
        pass
