from __future__ import unicode_literals
import os

from rpctools.jsonrpc import ServerProxy

from sideboard.lib import log, config, threadlocal


class _ServiceDispatcher(object):
    def __init__(self, services, name):
        self.services, self.name = services, name

    def __getattr__(self, method):
        assert self.name in self.services, '{} is not registered as a service'.format(self.name)
        func = getattr(self.services[self.name], method, None)
        assert func and hasattr(func, '__call__') and not method.startswith('_'), 'no such method {}.{}'.format(self.name, method)
        return func


class _Services(object):
    """
    This class is used by plugins to register services, and to call services
    registered by other plugins.  You call services by attribute lookup, e.g.
    
    >>> from sideboard.lib import services
    >>> services.foo.bar()
    'Hello World!'
    
    You may get a service which has not yet been registered; you'll only get
    an exception when calling a method on the service if it doesn't exist yet;
    this is to facilitate getting a namespace before the relevant plugin has
    been imported by Sideboard:
    
    >>> foo, baz = services.foo, services.baz
    >>> foo.bar()
    'Hello World!'
    >>> baz.baf()
    AssertionError: baz is not registered as a service
    
    Services may be local or jsonrpc, but they're called in the same way.
    """
    def __init__(self):
        self._services = {}

    def register(self, module, name):
        """
        Register an object with methods (usually a module) to be exposed under
        the given name.  An exception is raised if you use a name already used
        by another service.
        """
        assert name not in self._services, '{} has already been registered'.format(name)
        self._services[name] = module

    def get_services(self):
        """
        Returns the dictionary we use to store our registered services.  This
        is NOT a copy, so it is NOT safe to modify this dictionary without
        copying; this is intentional because it means that once you call this
        method, the dictionary which is returned will contain all known services,
        even ones registered after you called this method.
        """
        return self._services

    def __getattr__(self, name):
        return _ServiceDispatcher(self._services, name)

services = _Services()


def _register_rpc_services(rpc_services):
    for name, url in rpc_services.items():
        for setting in ['client_key', 'client_cert', 'ca']:
            if config[setting]:
                assert os.path.exists(config[setting]), '{} config option set to path not found on the filesystem: {}'.format(setting, config[setting])

        service = ServerProxy(url, key_file=config['client_key'], cert_file=config['client_cert'],
                              ca_certs=config['ca'], validate_cert_hostname=bool(config['ca']))
        services.register(getattr(service, name), name)

_register_rpc_services(config['rpc_services'])


class _SideboardCoreServices(object):
    """
    Location of rpc methods we want Sideboard itself to expose in the "sideboard"
    namespace.  Currently this only contains "poll" but we may add more
    methods, especially ones which allow you to list plugins, get version
    numbers, etc.
    """
    def poll(self):
        """empty method which exists only to help keep WebSockets alive"""
        log.debug('sideboard.poll by user {}', threadlocal.get('username'))

services.register(_SideboardCoreServices(), 'sideboard')
