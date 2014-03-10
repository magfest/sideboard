from __future__ import unicode_literals

import functools
import unittest

import mock


class HandleExceptionTest(unittest.TestCase):

    def setUp(self):
        self.log = mock.Mock()

    @property
    def handle_exception(self):
        from sideboard.internal.imports import handle_exception
        return functools.partial(handle_exception, log=self.log)

    @property
    def SideboardImportError(self):
        from sideboard.internal.imports import SideboardImportError
        return SideboardImportError

    def test_import_error_of_same_module_raised_in_nonplugin_module(self):
        # Sideboard decides what modules it should try to import from looking
        # at the file system, so if we tried to import a module and it's not
        # there, that's a problem.
        e = ImportError('No module named bar')
        self.handle_exception(e, 'foo_plugin', 'bar')
        self.log.warning.assert_called_with('ImportError caught while importing bar')

    def test_import_error_of_same_module_raised_in_nonplugin_module_with_dotted_name(self):
        e = ImportError('No module named foo.bar.baz')
        self.handle_exception(e, 'foo_plugin', 'foo.bar.baz')
        self.log.warning.assert_called_with('ImportError caught while importing foo.bar.baz')

    def test_import_error_of_different_module_raised_in_nonplugin_module(self):
        e = ImportError('No module named monkey')
        self.handle_exception(e, 'foo_plugin', 'foo')
        self.log.debug.assert_called_with('ImportError caught while importing foo')

    def test_import_error_of_different_module_raised_in_nonplugin_module_with_dotted_name(self):
        e = ImportError('No module named monkey.butler')
        self.handle_exception(e, 'foo_plugin', 'foo.bar.baz')
        self.log.debug.assert_called_with('ImportError caught while importing foo.bar.baz')

    def test_syntax_error_in_nonplugin_module(self):
        e = SyntaxError('EOL while scanning string literal')
        self.handle_exception(e, 'foo_plugin', 'foo')
        self.log.debug.assert_called_with('SyntaxError caught while importing foo')

    def test_exception_in_nonplugin_module(self):
        e = Exception()
        self.handle_exception(e, 'foo_plugin', 'foo')
        self.log.debug.assert_called_with('Exception caught while importing foo')

    def test_import_error_of_same_module_raised_in_plugin_module(self):
        e = ImportError('No module named foo_plugin')
        with self.assertRaises(self.SideboardImportError) as cm:
            self.handle_exception(e, 'foo_plugin', 'foo_plugin')
        self.assertEqual(str(cm.exception), 'ImportError caught while importing foo_plugin')

    def test_import_error_of_same_module_raised_in_plugin_module_with_dotted_name(self):
        e = ImportError('No module named foo_plugin.foo.bar')
        with self.assertRaises(self.SideboardImportError) as cm:
            self.handle_exception(e, 'foo_plugin', 'foo_plugin.foo.bar')
        self.assertEqual(str(cm.exception), 'ImportError caught while importing foo_plugin.foo.bar')

    def test_import_error_of_different_module_raised_in_plugin_module(self):
        e = ImportError('No module named aaa')
        with self.assertRaises(self.SideboardImportError) as cm:
            self.handle_exception(e, 'foo_plugin', 'foo_plugin')
        self.assertEqual(str(cm.exception), 'ImportError caught while importing foo_plugin')

    def test_import_error_of_different_module_raised_in_plugin_module_with_dotted_name(self):
        e = ImportError('No module named aaa.bbb.ccc')
        with self.assertRaises(self.SideboardImportError) as cm:
            self.handle_exception(e, 'foo_plugin', 'foo_plugin.bar.baz')
        self.assertEqual(str(cm.exception), 'ImportError caught while importing foo_plugin.bar.baz')

    def test_syntax_error_in_plugin_module(self):
        e = SyntaxError('EOL while scanning string literal')
        with self.assertRaises(self.SideboardImportError) as cm:
            self.handle_exception(e, 'foo_plugin', 'foo_plugin')
        self.assertEqual(str(cm.exception), 'SyntaxError caught while importing foo_plugin')

    def test_exception_in_plugin_module(self):
        e = Exception()
        with self.assertRaises(self.SideboardImportError) as cm:
            self.handle_exception(e, 'foo_plugin', 'foo_plugin')
        self.assertEqual(str(cm.exception), 'Exception caught while importing foo_plugin')
