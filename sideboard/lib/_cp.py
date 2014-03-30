from __future__ import unicode_literals
import json
from urllib import quote
from threading import Event
from functools import wraps
from collections import defaultdict

import jinja2
import cherrypy

import sideboard.lib
from sideboard.lib import log


_startup_registry = defaultdict(list)
_shutdown_registry = defaultdict(list)


def on_startup(func, priority=50):
    _startup_registry[priority].append(func)
    return func


def on_shutdown(func, priority=50):
    _shutdown_registry[priority].append(func)
    return func


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
                log.warn('Ignored exception during shutdown', exc_info=True)


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
                stopped.wait(0.1)
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


def renders_template(method, restricted=False):
    """
    Decorator for CherryPy page handler methods implementing default behaviors:
    - if your @render_with_templates class decorator used the "restricted"
        argument, this redirects to /login if the user has not authenticated
    - if your page handler returns a string, return that un-modified
    - if your page handler returns a non-jsonrpc dictionary, render a template
        with that dictionary; the function my_page will render my_page.html
    """
    @cherrypy.expose
    @wraps(method)
    def renderer(self, *args, **kwargs):
        if restricted and 'username' not in cherrypy.session:
            raise cherrypy.HTTPRedirect('/login?return_to=' + quote(cherrypy.request.app.script_name))
        
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
    Class decorator for CherryPy application objects with two optional arguments:
    - template_dir: if present, this will cause all of your page handler methods
        which return dictionaries to render Jinja templates found in this
        directory using those dictionaries.  So if you have a page handler called
        my_page which returns a dictionary, the template my_page.html in the
        template_dir directory will be rendered with that dictionary.
    - restricted: boolean which if True (this is False by default) will cause all
        page handlers in this class to redirect to /login if the client has not
        logged in already
    """
    def __init__(self, template_dir=None, restricted=False):
        self.template_dir, self.restricted = template_dir, restricted

    def __call__(self, klass):
        if self.template_dir:
            klass.env = jinja2.Environment(
                autoescape=_guess_autoescape,
                loader=jinja2.FileSystemLoader(self.template_dir),
                block_start_string='$(%',
                block_end_string='%)$',
                variable_start_string='$((',
                variable_end_string='))$',
            )
            klass.env.filters['jsonify'] = klass.env.filters['safe']
        for name, func in list(klass.__dict__.items()):
            if hasattr(func, '__call__'):
                setattr(klass, name, renders_template(func, self.restricted))
        return klass
