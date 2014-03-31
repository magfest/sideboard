from __future__ import unicode_literals
import os

from rpctools.jsonrpc import ServerProxy

from sideboard.lib import log, config, threadlocal, WebSocket


class _ServiceDispatcher(object):
    def __init__(self, services, name):
        self.services, self.name = services, name

    def __getattr__(self, method):
        assert self.name in self.services, '{} is not registered as a service'.format(self.name)
        service = self.services[self.name]
        func = service.make_caller(method) if isinstance(service, WebSocket) else getattr(service, method, None)
        assert func and hasattr(func, '__call__') and not method.startswith('_'), 'no such method {}.{}'.format(self.name, method)
        return func


class _JsonrpcServices(object):
    def __init__(self, services):
        self.services = services

    def __getattr__(self, name):
        return _ServiceDispatcher(self.services, name)


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
    
    Services may be local or websocket, but they're called in the same way.
    If you know that service is remote, and you want to use Jsonrpc, you can
    use the .jsonrpc attribute of this class, e.g.
    
    >>> services.jsonrpc.foo.bar()
    'Hello World!'
    >>> foo = services.jsonrpc.foo
    >>> foo.bar()
    'Hello World!'
    """
    def __init__(self):
        self._services, self._jsonrpc, self._websockets = {}, {}, {}
        self.jsonrpc = _JsonrpcServices(self._jsonrpc)

    def register(self, service, name=None, _jsonrpc=None, _override=False):
        """
        Register an object with methods (usually a module) to be exposed under
        the given name.  An exception is raised if you use a name already used
        by another service.

        This method takes the following parameters:
        - service: the object being registered; this is typically a module but
                   can be anything with functions (e.g. a class instance)
        - name: the name of the service being registered; if omitted, this will
                default to the __name__ of the service object
        - _jsonrpc: this should probably never be called by plugins; Sideboard
                    uses this to register both WebSoket and Jsonrpc RPC clients
        """
        name = name or service.__name__
        if not _jsonrpc:
            assert name not in self._services, '{} has already been registered'.format(name)
        self._services[name] = service
        if _jsonrpc:
            self._jsonrpc[name] = _jsonrpc

    def get_services(self):
        """
        Returns the dictionary we use to store our registered services.  This
        is NOT a copy, so it is NOT safe to modify this dictionary without
        copying; this is intentional because it means that once you call this
        method, the dictionary which is returned will contain all known services,
        even ones registered after you called this method.
        """
        return self._services

    def _register_websocket(self, url=None, **ws_kwargs):
        if url not in self._websockets:
            self._websockets[url] = WebSocket(url, **ws_kwargs)
        return self._websockets[url]

    def get_websocket(self, service_name=None):
        """
        Return the websocket connection to the machine that the specified service
        is running on, or a websocket connection to localhost if the service is
        unknown or not provided.
        """
        for name, service in self._services.items():
            if name == service_name and isinstance(service, WebSocket):
                return service
        else:
            return self._register_websocket()

    def __getattr__(self, name):
        return _ServiceDispatcher(self._services, name)

services = _Services()


def _register_rpc_services(rpc_services):
    for service_name, host in rpc_services.items():
        if not isinstance(host, dict):
            opts = {}
            for setting in ['client_key', 'client_cert', 'ca']:
                path = rpc_services.get(host, {}).get(setting, config[setting])
                if path:
                    assert os.path.exists(path), '{} config option set to path not found on the filesystem: {}'.format(setting, path)

                _check(setting, path)
                opts[setting] = path

                jsonrpc_url = '{protocol}://{host}/jsonrpc'.format(host=host, protocol='https' if opts['ca'] else 'http')
                jproxy = ServerProxy(url, key_file=opts['client_key'], cert_file=opts['client_cert'],
                                          ca_certs=opts['ca'], validate_cert_hostname=bool(opts['ca']))
                jservice = getattr(jproxy, service_name)
                if rpc_services.get(host, {}).get('jsonrpc_only'):
                    service = jservice
                else:
                    ws_url = '{protocol}://{host}/wsprc'.format(host=host, protocol='wss' if opts['ca'] else 'ws')
                    ssl_opts = {'key_file': opts['client_key'], 'cert_file': opts['client_cert'], 'ca_certs': opts['ca']}
                    service = services._register_websocket(ws_url, ssl_opts={k: v for k, v in ssl_opts if v})

            services.register(service, name, _jsonrpc=jservice, _override=True)

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
