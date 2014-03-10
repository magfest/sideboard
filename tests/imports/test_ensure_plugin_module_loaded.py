from __future__ import unicode_literals

import os
import unittest

import mock

__here__ = os.path.dirname(os.path.abspath(__file__))
__plugin_container__ = os.path.abspath(os.path.join(__here__, '..', 'plugins'))


class EnsurePluginModuleLoaded(unittest.TestCase):
    maxDiff = None
    @property
    def SideboardImportError(self):
        from sideboard.internal.imports import SideboardImportError
        return SideboardImportError

    def test(self):
        from sideboard.internal.imports import _discover_plugins
        plugin_dir = os.path.join(__plugin_container__, 'not_installed')
        with self.assertRaises(self.SideboardImportError) as cm:
            _discover_plugins(plugin_dir)
        self.assertEqual(str(cm.exception), 'plugin module foo not loaded; '
                                'did you forget to run `setup.py develop`?')

    def test_plugin_module_loaded(self):
        from sideboard.internal.imports import ensure_plugin_module_loaded
        mock_sys = mock.Mock()
        mock_sys.modules = {'foo': '<module>'}
        try:
            ensure_plugin_module_loaded('foo', sys=mock_sys)
        except self.SideboardImportError:
            self.fail('Loaded module should not cause SideboardImportError')

    def test_plugin_submodule_loaded(self):
        # I don't know that this is possible, but might as well test for it.
        from sideboard.internal.imports import ensure_plugin_module_loaded
        mock_sys = mock.Mock()
        mock_sys.modules = {'foo.bar': '<module1>', 'foo.baz': '<module2>'}
        with self.assertRaises(self.SideboardImportError):
            ensure_plugin_module_loaded('foo', sys=mock_sys)

    def test_plugin_module_not_loaded(self):
        from sideboard.internal.imports import ensure_plugin_module_loaded
        mock_sys = mock.Mock()
        mock_sys.modules = {}
        with self.assertRaises(self.SideboardImportError):
            ensure_plugin_module_loaded('foo', sys=mock_sys)
