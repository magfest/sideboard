from __future__ import unicode_literals
import os
import sys

import cherrypy

from sideboard.lib import config, threadlocal


def reset_threadlocal():
    threadlocal.reset(username=cherrypy.session.get("username"))

cherrypy.tools.reset_threadlocal = cherrypy.Tool('before_handler', reset_threadlocal, priority=51)

cherrypy_config = {}
for setting, value in config['cherrypy'].items():
    if isinstance(value, str):
        if value.isdigit():
            value = int(value)
        elif value.lower() in ['true', 'false']:
            value = value.lower() == 'true'
    cherrypy_config[setting] = value
cherrypy.config.update(cherrypy_config)
