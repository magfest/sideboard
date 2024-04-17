from __future__ import unicode_literals
import os
import importlib

import cherrypy

from sideboard._version import __version__
import sideboard.server

from sideboard.internal.imports import _discover_plugins

if 'SIDEBOARD_MODULE_TESTING' not in os.environ:
    _discover_plugins()
