from __future__ import unicode_literals

import cherrypy

import sideboard.server

if __name__ == '__main__':
    # Start the server engine (Option 1 *and* 2)
    cherrypy.engine.start()
    cherrypy.engine.block()
