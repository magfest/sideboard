from __future__ import unicode_literals
from sideboard.debugging import debugger_helpers_all_init

import cherrypy

if __name__ == '__main__':
    # import pydevd
    # print("running debug server2...", flush=True)
    # pydevd.settrace('10.0.0.29', port=5000, stdoutToServer=True, stderrToServer=True)

    debugger_helpers_all_init()

    cherrypy.engine.start()
    cherrypy.engine.block()
