from __future__ import unicode_literals

import cherrypy

import sideboard.server

if __name__ == '__main__':
    cherrypy.engine.start()
    cherrypy.engine.block()
