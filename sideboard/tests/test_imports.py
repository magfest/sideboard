from __future__ import unicode_literals
import os
import shutil
import tempfile
from os.path import join

import pytest

from sideboard.config import config
from sideboard.internal.imports import _discover_plugin_dirs


class TestDiscoverPluginDirs:

    def test_discover_plugin_dirs(self, monkeypatch):
        plugins_dir = tempfile.mkdtemp()
        try:
            monkeypatch.setitem(config, 'plugins_dir', plugins_dir)
            plugin_names = ['_u', 'a-1', 'z-2', 'b_3', 'y_4', 'c-6', 'x_7']
            plugin_dirs = {name: join(plugins_dir, name) for name in plugin_names}
            for plugin_name, plugin_dir in plugin_dirs.items():
                os.makedirs(plugin_dir)
            actual = _discover_plugin_dirs()
            expected = [(name.replace('-', '_'), plugin_dirs[name]) for name in sorted(plugin_names) if name != '_u']
            assert actual == expected
        finally:
            shutil.rmtree(plugins_dir, ignore_errors=True)
