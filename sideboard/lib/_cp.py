from __future__ import unicode_literals
import json
from threading import Event
from functools import wraps
from collections import defaultdict

from six.moves.urllib_parse import quote

import jinja2
import cherrypy

try:
    from sideboard.lib._redissession import RedisSession
    cherrypy.lib.sessions.RedisSession = RedisSession
except ImportError:
    # cherrys not installed, so redis sessions not supported
    pass

import sideboard.lib
from sideboard.lib import log, config, serializer

auth_registry = {}
_startup_registry = defaultdict(list)
_shutdown_registry = defaultdict(list)


def _on_startup(func, priority):
    _startup_registry[priority].append(func)
    return func


def _on_shutdown(func, priority):
    _shutdown_registry[priority].append(func)
    return func


def on_startup(func=None, priority=50):
    """
    Register a function to be called when Sideboard starts.  Startup functions
    have a priority, and the functions are invoked in priority order, where
    low-priority-numbered functions are invoked before higher numbers.

    Startup functions may be registered in one of three ways:

    1) A function can be passed directly, e.g.
        on_startup(callback_function)
        on_startup(callback_function, priority=25)

    2) This function can be used as a decorator, e.g.
        @on_startup
        def callback_function():
            ...

    3) This function can be used as a decorator with a priority value, e.g.
        @on_startup(priority=25)
        def callback_function():
            ...

    If instead of running a function when Sideboard starts, you need to run a
    function immediately after Sideboard loads your plugin, you may optionally
    declare an on_load() function in your plugin's top-level __init__.py
    module. If it exists, Sideboard will call on_load() immediately after
    loading the plugin, before attempting to load any subsequent plugins.

    """
    if func:
        return _on_startup(func, priority)
    else:
        return lambda func: _on_startup(func, priority)


def on_shutdown(func=None, priority=50):
    """
    Register a function to be called when Sideboard exits.  See the on_startup
    function above for how this is used.
    """
    if func:
        return _on_shutdown(func, priority)
    else:
        return lambda func: _on_shutdown(func, priority)


def _run_startup():
    for priority, functions in sorted(_startup_registry.items()):
        for func in functions:
            func()


def _run_shutdown():
    for priority, functions in sorted(_shutdown_registry.items()):
        for func in functions:
            try:
                func()
            except Exception:
                log.warning('Ignored exception during shutdown', exc_info=True)

stopped = Event()
on_startup(stopped.clear, priority=0)
on_shutdown(stopped.set, priority=0)

cherrypy.engine.subscribe('start', _run_startup, priority=98)
cherrypy.engine.subscribe('stop', _run_shutdown, priority=98)


def mainloop():
    """
    This function exists for Sideboard plugins which do not run CherryPy.  It
    runs all of the functions registered with sideboard.lib.on_startup and then
    waits for shutdown, at which point it runs all functions registered with
    sideboard.lib.on_shutdown.
    """
    _run_startup()
    try:
        while not stopped.is_set():
            try:
                stopped.wait(config['thread_wait_interval'])
            except KeyboardInterrupt:
                break
    finally:
        _run_shutdown()


def ajax(method):
    """
    Decorator for CherryPy page handler methods which sets the Content-Type
    to application/json and serializes your function's return value to json.
    """
    @wraps(method)
    def to_json(self, *args, **kwargs):
        cherrypy.response.headers['Content-Type'] = 'application/json'
        return json.dumps(method(self, *args, **kwargs), cls=sideboard.lib.serializer)
    return to_json


def restricted(x):
    """
    Decorator for CherryPy page handler methods.  This can either be called
    to provide an authenticator ident or called directly as a decorator, e.g.

        @restricted
        def some_page(self): ...

    is equivalent to

        @restricted(sideboard.lib.config['default_authenticator'])
        def some_page(self): ...
    """
    def make_decorator(ident):
        def decorator(func):
            @cherrypy.expose
            @wraps(func)
            def with_checking(*args, **kwargs):
                if not auth_registry[ident]['check']():
                    raise cherrypy.HTTPRedirect(auth_registry[ident]['login_path'])
                else:
                    return func(*args, **kwargs)
            return with_checking
        return decorator

    if hasattr(x, '__call__'):
        return make_decorator(config['default_authenticator'])(x)
    else:
        return make_decorator(x)


def renders_template(method):
    """
    Decorator for CherryPy page handler methods implementing default behaviors:
    - if your page handler returns a string, return that un-modified
    - if your page handler returns a non-jsonrpc dictionary, render a template
        with that dictionary; the function my_page will render my_page.html
    """
    @cherrypy.expose
    @wraps(method)
    def renderer(self, *args, **kwargs):
        output = method(self, *args, **kwargs)
        if isinstance(output, dict) and output.get('jsonrpc') != '2.0':
            return self.env.get_template(method.__name__ + '.html').render(**output)
        else:
            return output
    return renderer


# Lifted from Jinja2 docs. See http://jinja.pocoo.org/docs/api/#autoescaping
def _guess_autoescape(template_name):
    if template_name is None or '.' not in template_name:
        return False
    ext = template_name.rsplit('.', 1)[1]
    return ext in ('html', 'htm', 'xml')


class render_with_templates(object):
    """
    Class decorator for CherryPy application objects which causes all of your page
    handler methods which return dictionaries to render Jinja templates found in this
    directory using those dictionaries.  So if you have a page handler called my_page
    which returns a dictionary, the template my_page.html in the template_dir
    directory will be rendered with that dictionary.  An "env" attribute gets added
    to the class which is a Jinja environment.

    For convenience, if the optional "restricted" parameter is passed, this class is
    also passed through the @all_restricted class decorator.
    """
    def __init__(self, template_dir, restricted=False):
        self.template_dir, self.restricted = template_dir, restricted

    def __call__(self, klass):
        klass.env = jinja2.Environment(autoescape=_guess_autoescape, loader=jinja2.FileSystemLoader(self.template_dir))
        klass.env.filters['jsonify'] = lambda x: klass.env.filters['safe'](json.dumps(x, cls=serializer))

        if self.restricted:
            all_restricted(self.restricted)(klass)

        for name, func in list(klass.__dict__.items()):
            if hasattr(func, '__call__'):
                setattr(klass, name, renders_template(func))

        return klass


class all_restricted(object):
    """Invokes the @restricted decorator on all methods of a class."""
    def __init__(self, ident):
        self.ident = ident
        assert ident in auth_registry, '{!r} is not a recognized authenticator'.format(ident)

    def __call__(self, klass):
        for name, func in list(klass.__dict__.items()):
            if hasattr(func, '__call__'):
                setattr(klass, name, restricted(self.ident)(func))
        return klass


def register_authenticator(ident, login_path, checker):
    """
    Register a new authenticator, which consists of three things:
    - A string ident, used to identify the authenticator in @restricted calls.
    - The path to the login page we should redirect to when not authenticated.
    - A function callable with no parameters which returns a truthy value if the
      user is logged in and a falsey value if they are not.
    """
    assert ident not in auth_registry, '{} is already a registered authenticator'.format(ident)
    auth_registry[ident] = {
        'check': checker,
        'login_path': login_path
    }

register_authenticator('default', '/login', lambda: 'username' in cherrypy.session)
