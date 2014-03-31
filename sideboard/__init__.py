from __future__ import unicode_literals

from sideboard._version import __version__

# must be done before setting up log levels in order to blow away CherryPy
import cherrypy
import threading

from sideboard.internal.logging import _configure_logging
_configure_logging()

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


from sideboard.internal.imports import _discover_plugins, _import_overrider

from sideboard.lib import log
import __builtin__

_discover_plugins()
original_import = __import__

# notably, this is after we discover all the plugins. It's possible that a modified function
# can be written that can handle the discovery and all follow-on imports
# we're intentionally not passing in a reference to an earlier initialized lock because we never
# expect it to be acquired anywhere else except here
__builtin__.__import__ = _import_overrider(original_import, threading.RLock())
