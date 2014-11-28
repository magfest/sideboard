from __future__ import unicode_literals
from debugger import debugger_helpers_all_init

import cherrypy

import sideboard.server

if __name__ == '__main__':
    debugger_helpers_all_init()

    cherrypy.engine.start()
    cherrypy.engine.block()
