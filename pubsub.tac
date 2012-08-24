from twisted.application import internet, service
from twisted.web.server import Site
from pubsub import *

factory = Site(Dispatcher())
port = 8080
application = Application("My Web Service")
TCPServer(port, factory).setServiceParent(application)

