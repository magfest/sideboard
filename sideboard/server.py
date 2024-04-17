from __future__ import unicode_literals
import cherrypy

from sideboard.lib import config

cherrypy_config = {}
for setting, value in config['cherrypy'].items():
    if isinstance(value, str):
        if value.isdigit():
            value = int(value)
        elif value.lower() in ['true', 'false']:
            value = value.lower() == 'true'
    cherrypy_config[setting] = value
cherrypy.config.update(cherrypy_config)
