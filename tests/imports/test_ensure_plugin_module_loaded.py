from __future__ import unicode_literals
import os
import sys

import pytest

from sideboard.internal.imports import SideboardImportError, _discover_plugins, ensure_plugin_module_loaded
from sideboard.tests import config_patcher

__here__ = os.path.dirname(os.path.abspath(__file__))
__plugin_container__ = os.path.abspath(os.path.join(__here__, '..', 'plugins'))


def test_discover_plugins(config_patcher):
    config_patcher(os.path.join(__plugin_container__, 'not_installed'), 'plugins_dir')
    with pytest.raises(SideboardImportError) as exc:
        _discover_plugins()

def test_plugin_module_loaded(monkeypatch):
    monkeypatch.setattr(sys, 'modules', {'foo': '<module>'})
    ensure_plugin_module_loaded('foo')

def test_plugin_module_not_loaded(monkeypatch):
    monkeypatch.setattr(sys, 'modules', {})
    with pytest.raises(SideboardImportError):
        ensure_plugin_module_loaded('foo')
