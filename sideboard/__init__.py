from __future__ import unicode_literals
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

_discover_plugins()
_configure_logging()
