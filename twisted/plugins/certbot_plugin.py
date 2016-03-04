from zope.interface import implements
 
from twisted.python import usage
from twisted.plugin import IPlugin
from twisted.application.service import IServiceMaker
 
import certbot
 
class Options(usage.Options):
    optParameters = [
        ["config", "c", "certbot.yml", "Config file"],
    ]
 
class CertbotServiceMaker(object):
    implements(IServiceMaker, IPlugin)
    tapname = "certbot"
    description = "A robot for managing letsencrypt certs"
    options = Options
 
    def makeService(self, options):
        config = yaml.load(open(options['config']))
        return certbot.makeService(config)
 
serviceMaker = CertbotServiceMaker()
