from __future__ import unicode_literals
from sideboard.debugging import debugger_helpers_all_init

import cherrypy

if __name__ == '__main__':
    debugger_helpers_all_init()

    cherrypy.engine.start()
    cherrypy.engine.block()
