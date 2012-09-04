import os
from twisted.application import internet, service
from twisted.web import server
from twisted.web.server import Site

import sys
sys.path.append("/usr/local/bin")

from pubsub import Dispatcher

def getWebService(port):
    """
    Return a service suitable for creating an application object.

    This service is a simple web server that serves files on port 8080 from
    underneath the current working directory.
    """
    # create a resource to serve static files
    Server = server.Site(Dispatcher())
    return internet.TCPServer(port, Server)



# this is the core part of any tac file, the creation of the root-level
# application object
application = service.Application("Demo application")

# attach the service to its parent application
port = 8080
service = getWebService(port)
service.setServiceParent(application)


#factory = Site(Dispatcher())
#port = 8080
#application = Application("My Web Service")
#TCPServer(port, factory).setServiceParent(application)

