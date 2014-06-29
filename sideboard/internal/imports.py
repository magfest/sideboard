from __future__ import unicode_literals
import sys
import importlib
from glob import glob
from os.path import join, isdir, basename

from sideboard.config import config

plugins = {}

def _discover_plugins():
    for plugin_path in glob(join(config['plugins_dir'], '*')):
        if isdir(plugin_path) and not basename(plugin_path).startswith('_'):
            sys.path.append(plugin_path)
            plugin_name = basename(plugin_path).replace('-', '_')
            plugins[plugin_name] = importlib.import_module(plugin_name)
