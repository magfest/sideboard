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

from sideboard.internal.imports import _discover_plugins
from sideboard.internal.logging import _configure_logging

_discover_plugins()
_configure_logging()
