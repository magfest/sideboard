from __future__ import unicode_literals
import os
import importlib

import six
import cherrypy

from sideboard._version import __version__
try:
    import sideboard.server
except:
    from sideboard.lib import log
    log.warning('Error importing server', exc_info=True)

from sideboard.internal.imports import _discover_plugins
from sideboard.internal.logging import _configure_logging
import sideboard.run_mainloop

if 'SIDEBOARD_MODULE_TESTING' not in os.environ:
    _discover_plugins()
    _configure_logging()
