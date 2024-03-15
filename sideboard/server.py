from __future__ import unicode_literals
import os
import sys

import six
import cherrypy

from sideboard.lib import config, threadlocal


def reset_threadlocal():
    threadlocal.reset(**{field: cherrypy.session.get(field) for field in config['ws.session_fields']})

cherrypy.tools.reset_threadlocal = cherrypy.Tool('before_handler', reset_threadlocal, priority=51)

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
