from __future__ import unicode_literals
import os
import ssl

from rpctools.jsonrpc import ServerProxy

from sideboard.lib import log, config, threadlocal, WebSocket


class _ServiceDispatcher(object):
    def __init__(self, services, name):
        self.services, self.name = services, name

    def __getattr__(self, method):
        from sideboard.lib import is_listy
        assert self.name in self.services, '{} is not registered as a service'.format(self.name)
        service = self.services[self.name]
        assert not is_listy(getattr(service, '__all__', None)) or method in service.__all__, 'unable to call non-whitelisted method {}.{}'.format(self.name, method)
        func = service.make_caller('{}.{}'.format(self.name, method)) if isinstance(service, WebSocket) else getattr(service, method, None)
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

    def _register_websocket(self, url=None, connect_immediately=True, **ws_kwargs):
        if url not in self._websockets:
            self._websockets[url] = WebSocket(url, connect_immediately=connect_immediately, **ws_kwargs)
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


def _rpc_opts(host, service_config=None):
    """
    Sideboard uses client certs for backend service authentication.  There's a
    global set of config options which determine the SSL settings we pass to our
    RPC libraries, but sometimes different services require client certs issued
    by different CAs.  In those cases, we define a config subsection of the main
    [rpc_services] section to override those settings.

    This function takes a hostname and for each config option, it returns either
    the hostname-specific config option if it exists, or the global config option
    if it doesn't.  Specifically, this returns a dict of option names/values.

    If the service_config parameter is passed, it uses that as the config section
    from which to draw the hostname-specific options.  Otherwise it searches
    the [rpc_services] config section for Sideboard and for all Sideboard plugins
    which have a "config" object defined in order to find options for that host.
    """
    from sideboard.internal.imports import plugins
    section = service_config
    if service_config is not None:  # check explicitly for None because service_config might be {}
        section = service_config
    else:
        rpc_sections = {host: section for host, section in config['rpc_services'].items() if isinstance(section, dict)}
        for plugin in plugins.values():
            plugin_config = getattr(plugin, 'config', None)
            if isinstance(plugin_config, dict):
                rpc_sections.update({host: section for host, section in plugin_config.get('rpc_services', {}).items() if isinstance(section, dict)})
        section = rpc_sections.get(host, {})

    opts = {}
    for setting in ['client_key', 'client_cert', 'ca', 'ssl_version']:
        path = section.get(setting, config[setting])
        if path and setting != 'ssl_version':
            assert os.path.exists(path), '{} config option set to path not found on the filesystem: {}'.format(setting, path)

        opts[setting] = path
    return opts


def _ssl_opts(rpc_opts):
    """
    Given a dict of config options returned by _rpc_opts, return a dict of
    options which can be passed to the ssl module.
    """
    ssl_opts = {
        'ca_certs': rpc_opts['ca'],
        'keyfile': rpc_opts['client_key'],
        'certfile': rpc_opts['client_cert'],
        'cert_reqs': ssl.CERT_REQUIRED if rpc_opts['ca'] else None,
        'ssl_version': getattr(ssl, rpc_opts['ssl_version'])
    }
    return {k: v for k, v in ssl_opts.items() if v}


def _ws_url(host, rpc_opts):
    """
    Given a hostname and set of config options returned by _rpc_opts, return the
    standard URL websocket endpoint for a Sideboard remote service.
    """
    return '{protocol}://{host}/ws'.format(host=host, protocol='wss' if rpc_opts['ca'] else 'ws')


def _register_rpc_services(rpc_services):
    """
    Sideboard has a config file, and it provides a parse_config method for its
    plugins to parse their own config files.  In both cases, we check for the
    presence of an [rpc_services] config section, which we use to register any
    services defined there with our sideboard.lib.services API.  Note that this
    means a server can provide information about a remote service in either the
    main Sideboard config file OR the config file of any plugin.

    This function takes the [rpc_services] config section from either Sideboard
    itself or one of its plugins and registers all remote services found there.
    """
    for service_name, host in rpc_services.items():
        if not isinstance(host, dict):
            rpc_opts = _rpc_opts(host, rpc_services.get(host, {}))
            ssl_opts = _ssl_opts(rpc_opts)

            jsonrpc_url = '{protocol}://{host}/jsonrpc'.format(host=host, protocol='https' if rpc_opts['ca'] else 'http')
            jproxy = ServerProxy(jsonrpc_url, ssl_opts=ssl_opts, validate_cert_hostname=bool(rpc_opts['ca']))
            jservice = getattr(jproxy, service_name)
            if rpc_services.get(host, {}).get('jsonrpc_only'):
                service = jservice
            else:
                service = services._register_websocket(_ws_url(host, rpc_opts), ssl_opts=ssl_opts, connect_immediately=False)

            services.register(service, service_name, _jsonrpc=jservice, _override=True)

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
        log.debug('sideboard.poll by user %s', threadlocal.get('username'))

services.register(_SideboardCoreServices(), 'sideboard')
