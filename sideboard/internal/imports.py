from __future__ import unicode_literals
import sys
import importlib
from collections import OrderedDict
from glob import glob
from itertools import chain
from os.path import join, isdir, basename

from sideboard.config import config


plugins = OrderedDict()
plugin_dirs = OrderedDict()


def _discover_plugin_dirs():
    unsorted_dirs = {basename(d).replace('-', '_'): d
            for d in glob(join(config['plugins_dir'], '*'))
            if isdir(d) and not basename(d).startswith('_')}

    priority_plugins = config['priority_plugins']
    nonpriority_plugins = sorted(set(unsorted_dirs.keys()).difference(priority_plugins))
    sorted_plugins = chain(priority_plugins, nonpriority_plugins)

    return [(name, unsorted_dirs[name]) for name in sorted_plugins]


def _discover_plugins():
    for name, path in _discover_plugin_dirs():
        sys.path.append(path)
        plugin_dirs[name] = path

    for name, path in plugin_dirs.items():
        plugins[name] = importlib.import_module(name)
        if callable(getattr(plugins[name], 'on_load', None)):
            plugins[name].on_load()
