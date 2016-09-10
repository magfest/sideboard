from __future__ import unicode_literals
import sys
import importlib
from glob import glob
from os.path import join, isdir, basename

from sideboard.config import config

plugins = {}


def _discover_plugins():
    ordered = list(reversed(config['priority_plugins']))
    plugin_dirs = [d for d in glob(join(config['plugins_dir'], '*')) if isdir(d) and not basename(d).startswith('_')]

    # glob() results are not ordered, so we sort here to ensure non-prioritized plugins load in the same order
    # regardless of OS-dependent arbitrary ordering
    plugin_dirs = sorted(plugin_dirs, key=lambda d: basename(d))

    for plugin_path in sorted(plugin_dirs, reverse=True, key=lambda d: (ordered.index(basename(d)) if basename(d) in ordered else -1)):
        sys.path.append(plugin_path)
        plugin_name = basename(plugin_path).replace('-', '_')
        plugins[plugin_name] = importlib.import_module(plugin_name)
