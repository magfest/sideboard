from __future__ import unicode_literals
import importlib

_plugins_imported = False

# monkeypatch import_module to use our venv context manager
_orig_import_module = importlib.import_module
def _new_import_module(name, package=None):
    if not _plugins_imported:
        return _orig_import_module(name, package)
    else:
        with use_plugin_virtualenv():
            return _orig_import_module(name, package)
importlib.import_module = _new_import_module

import six
import cherrypy

from sideboard._version import __version__
try:
    import sideboard.server
except:
    from sideboard.lib import log
    log.warning('Error importing server', exc_info=True)

# check for arguments which are required for daemon/server but are not required for core
from sideboard.lib import on_startup, config, ConfigurationError

@on_startup
def _check_sometimes_required_options():
    missing = []
    for optname in ['ldap.url', 'ldap.basedn']:
        val = config[optname]
        if not val or isinstance(val, (list, tuple)) and not filter(bool, val):
            missing.append(optname)

    if missing:
        message = 'missing configuration options: {}'.format(missing)
        log.error(message)
        raise ConfigurationError(message)

from sideboard.internal.logging import _configure_logging
from sideboard.internal.imports import _discover_plugins, use_plugin_virtualenv

_discover_plugins()
_configure_logging()

# notably, this is after we discover all the plugins. It's possible that a modified
# approach can be written that can handle the discovery and all follow-on imports
_original_import = __import__
def _new_import(*args, **kwargs):
    with use_plugin_virtualenv():
        return _original_import(*args, **kwargs)
six.moves.builtins.__import__ = _new_import
_plugins_imported = True
