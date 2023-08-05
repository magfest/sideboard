from __future__ import unicode_literals
import os
import sys

import six
import cherrypy
from cherrypy.lib import cpstats

import sideboard
from sideboard.internal import connection_checker
from sideboard.jsonrpc import _make_jsonrpc_handler
from sideboard.websockets import WebSocketDispatcher, WebSocketRoot, WebSocketAuthError
from sideboard.lib import log, listify, config, render_with_templates, services, threadlocal
from sideboard.lib._cp import auth_registry

default_auth_checker = auth_registry[config['default_authenticator']]['check']


def reset_threadlocal():
    threadlocal.reset(**{field: cherrypy.session.get(field) for field in config['ws.session_fields']})

cherrypy.tools.reset_threadlocal = cherrypy.Tool('before_handler', reset_threadlocal, priority=51)


def jsonrpc_reset(body):
    reset_threadlocal()
    threadlocal.set('client', body.get('websocket_client'))


def jsonrpc_auth(body):
    jsonrpc_reset(body)
    if not default_auth_checker():
        raise cherrypy.HTTPError(401, 'not logged in')


@render_with_templates(config['template_dir'])
class Root(object):
    def default(self, *args, **kwargs):
        raise cherrypy.HTTPRedirect(config['default_url'])

    def logout(self, return_to='/'):
        cherrypy.session.pop('username', None)
        raise cherrypy.HTTPRedirect('login?return_to=%s' % return_to)

    def login(self, username='', password='', message='', return_to=''):
        if not config['debug']:
            return 'Login page only available in debug mode.'

        if username:
            if config['debug'] and password == config['debug_password']:
                cherrypy.session['username'] = username
                raise cherrypy.HTTPRedirect(return_to or config['default_url'])
            else:
                message = 'Invalid credentials'

        return {
            'message': message,
            'username': username,
            'return_to': return_to
        }

    def list_plugins(self):
        from sideboard.internal.imports import plugins
        plugin_info = {}
        for plugin, module in plugins.items():
            plugin_info[plugin] = {
                'name': ' '.join(plugin.split('_')).title(),
                'version': getattr(module, '__version__', None),
                'paths': []
            }
        for path, app in cherrypy.tree.apps.items():
            # exclude what Sideboard itself mounts and grafted mount points
            if path and hasattr(app, 'root'):
                plugin = app.root.__module__.split('.')[0]
                plugin_info[plugin]['paths'].append(path)
        return {
            'plugins': plugin_info,
            'version': getattr(sideboard, '__version__', None)
        }

    def connections(self):
        return {'connections': connection_checker.check_all()}

    ws = WebSocketRoot()
    wsrpc = WebSocketRoot()

    json = _make_jsonrpc_handler(services.get_services(), precall=jsonrpc_auth)
    jsonrpc = _make_jsonrpc_handler(services.get_services(), precall=jsonrpc_reset)


class SideboardWebSocket(WebSocketDispatcher):
    """
    This web socket handler will be used by browsers connecting to Sideboard web
    sites.  Therefore, the authentication mechanism is the default approach
    of checking the session for a username and rejecting unauthenticated users.
    """
    services = services.get_services()

    @classmethod
    def check_authentication(cls):
        host, origin = cherrypy.request.headers['host'], cherrypy.request.headers['origin']
        if ('//' + host.split(':')[0]) not in origin:
            log.error('Javascript websocket connections must follow same-origin policy; origin %s does not match host %s', origin, host)
            raise WebSocketAuthError('Origin and Host headers do not match')

        if config['ws.auth_required'] and not cherrypy.session.get(config['ws.auth_field']):
            log.warning('websocket connections to this address must have a valid session')
            raise WebSocketAuthError('You are not logged in')

        return WebSocketDispatcher.check_authentication()


app_config = {
    '/static': {
        'tools.staticdir.on': True,
        'tools.staticdir.dir': os.path.join(config['module_root'], 'static')
    },
    '/ws': {
        'tools.websockets.on': True,
        'tools.websockets.handler_cls': SideboardWebSocket
    }
}
if config['debug']:
    app_config['/docs'] = {
        'tools.staticdir.on': True,
        'tools.staticdir.dir': os.path.join(config['module_root'], 'docs', 'html'),
        'tools.staticdir.index': 'index.html'
    }
cherrypy_config = {}
for setting, value in config['cherrypy'].items():
    if isinstance(value, six.string_types):
        if value.isdigit():
            value = int(value)
        elif value.lower() in ['true', 'false']:
            value = value.lower() == 'true'
        elif six.PY2:
            value = value.encode('utf-8')
    cherrypy_config[setting] = value
cherrypy.config.update(cherrypy_config)


# on Python 2, we need bytestrings for CherryPy config, see https://bitbucket.org/cherrypy/cherrypy/issue/1184
def recursive_coerce(d):
    if isinstance(d, dict):
        for k, v in d.items():
            if sys.version_info[:2] == (2, 7) and isinstance(k, unicode):
                del d[k]
                d[k.encode('utf-8')] = recursive_coerce(v)
    return d


def mount(root, script_name='', config=None):
    assert script_name not in cherrypy.tree.apps, '{} has already been mounted, probably by another plugin'.format(script_name)
    return orig_mount(root, script_name, recursive_coerce(config))

orig_mount = cherrypy.tree.mount
cherrypy.tree.mount = mount
root = Root()
if config['cherrypy']['tools.cpstats.on']:
    root.stats = cpstats.StatsPage()
cherrypy.tree.mount(root, '', app_config)

if config['cherrypy']['profiling.on']:
    # If profiling is turned on then expose the web UI, otherwise ignore it.
    from sideboard.lib import Profiler
    cherrypy.tree.mount(Profiler(config['cherrypy']['profiling.path']), '/profiler')

sys.modules.pop('six.moves.winreg', None)  # kludgy workaround for CherryPy's autoreloader erroring on winreg for versions which have this
