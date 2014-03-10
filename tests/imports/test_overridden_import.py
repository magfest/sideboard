from unittest import TestCase

import threading

import mock
from mock import patch

import sideboard
from sideboard.internal.imports import _yield_frames

class OverriddenImportTest(TestCase):
    maxDiff = None

    def test_that_yield_frames_goes_most_recent_call_first(self):

        def a():
            def b():
                def c():
                    # TODO: this is better done as an assertion that the c,b,a list is a subsequence of the co_names
                    self.assertEqual(['c', 'b', 'a'],
                                     # item 0 is _yield_frames itself
                                     # item 1 is the generator expression that creates the list
                                     list(frame.f_code.co_name for frame in _yield_frames())[2:5])
                c()
            b()
        a()

    def test_that_yield_module_names_goes_most_recent_call_first(self):

        from .overridden_import_modules_for_asserts.a import a_func
        # assert module_names[2] == 'tests.imports.overridden_import_modules_for_asserts.c'
        # assert module_names[3] == 'tests.imports.overridden_import_modules_for_asserts.b'
        # assert module_names[4] == 'tests.imports.overridden_import_modules_for_asserts.a'
        a_func()

    # TODO: test exception cases from yield module name from callstack

    def test_is_plugin_name(self):
        with patch.dict('sideboard.internal.imports._path_cache', {'foo': ['bar'], 'foo2': ['bar']}, clear=True), \
             patch.dict('sideboard.internal.imports._module_cache', {'foo': ['bar'], 'foo3': ['bar']},  clear=True):

            assert sideboard.internal.imports._is_plugin_name('foo')
            assert not sideboard.internal.imports._is_plugin_name('foo2')
            assert not sideboard.internal.imports._is_plugin_name('foo3')
            assert not sideboard.internal.imports._is_plugin_name('foo4')

    def test_venv_plugin_name(self):

        foo_site_packages = '/opt/sideboard/plugins/test-plugin-foo/env/lib/python2.7/site-packages'
        foo2_site_packages = '/opt/sideboard/plugins/test-plugin-foo2/env/lib/python2.7/site-packages'

        fake_paths = {
            'foo': [foo_site_packages + '/test-plugin-foo', foo_site_packages],
            'foo2': [foo2_site_packages + '/test-plugin-foo2', foo2_site_packages],
        }

        def _get_plugin_name(file_path):
            return sideboard.internal.imports._venv_plugin_name(file_path)

        with patch.dict('sideboard.internal.imports._path_cache', fake_paths, clear=True):
            assert _get_plugin_name(foo_site_packages + '/bar.pyc') == 'foo'
            assert _get_plugin_name(foo_site_packages + '/blah/baz.pyc') == 'foo'
            assert _get_plugin_name(foo_site_packages + 'test-plugin-foo/baz.pyc') == 'foo'
            assert _get_plugin_name(foo2_site_packages + '/bar.pyc') == 'foo2'
            assert _get_plugin_name(foo2_site_packages + '/blah/baz.pyc') == 'foo2'
            assert _get_plugin_name(foo2_site_packages + 'test-plugin-foo/baz.pyc') == 'foo2'

    def test_venv_plugin_name_with_trailing_slash(self):

        foo_site_packages = '/opt/sideboard/plugins/test-plugin-foo/env/lib/python2.7/site-packages/'
        foo2_site_packages = '/opt/sideboard/plugins/test-plugin-foo2/env/lib/python2.7/site-packages/'

        fake_paths = {
            'foo': [foo_site_packages + 'test-plugin-foo', foo_site_packages],
            'foo2': [foo2_site_packages + 'test-plugin-foo2', foo2_site_packages],
        }

        def _get_plugin_name(file_path):
            return sideboard.internal.imports._venv_plugin_name(file_path)

        with patch.dict('sideboard.internal.imports._path_cache', fake_paths, clear=True):
            assert _get_plugin_name(foo_site_packages + 'bar.pyc') == 'foo'
            assert _get_plugin_name(foo_site_packages + 'blah/baz.pyc') == 'foo'
            assert _get_plugin_name(foo_site_packages + 'test-plugin-foo/baz.pyc') == 'foo'
            assert _get_plugin_name(foo2_site_packages + 'bar.pyc') == 'foo2'
            assert _get_plugin_name(foo2_site_packages + 'blah/baz.pyc') == 'foo2'
            assert _get_plugin_name(foo2_site_packages + 'test-plugin-foo/baz.pyc') == 'foo2'

    @patch('sideboard.internal.imports._is_plugin_name')
    @patch('sideboard.internal.imports._yield_module_names_and_filenames_from_callstack')
    def test_simplest_case_for_import_origination(self, mock_module_and_file_names, mock_is_plugin_name):
        mock_module_and_file_names.return_value = [('foo.bar.baz.bax', 'foo/bar/baz/bax.py')]
        mock_is_plugin_name.return_value = True
        self.assertEqual(sideboard.internal.imports._get_sideboard_plugin_where_import_originated(), 'foo')

    @patch('sideboard.internal.imports._is_plugin_name')
    @patch('sideboard.internal.imports._yield_module_names_and_filenames_from_callstack')
    def test_empty_callstack_case_for_import_origination(self, mock_module_and_file_names, mock_is_plugin_name):
        mock_module_and_file_names.return_value = []
        mock_is_plugin_name.return_value = True
        self.assertIsNone(sideboard.internal.imports._get_sideboard_plugin_where_import_originated())

    @patch('sideboard.internal.imports._is_plugin_name')
    @patch('sideboard.internal.imports._yield_module_names_and_filenames_from_callstack')
    def test_not_from_a_plugin_case_for_import_origination(self, mock_module_and_file_names, mock_is_plugin_name):
        mock_module_and_file_names.return_value = [
            ('foo.bar.baz.bax', 'foo/bar/baz/bax/__init__.py'),
            ('foo.bar.baz.bax.buz', 'foo2/bar/baz/bax/buz/__init__.py'),
            ('foo.bar.baz.bax.buz.bux', 'foo/bar/baz/bax/buz/buz/__init__.py')
        ]
        mock_is_plugin_name.return_value = False
        self.assertIsNone(sideboard.internal.imports._get_sideboard_plugin_where_import_originated())

    @patch('sideboard.internal.imports._venv_plugin_name')
    @patch('sideboard.internal.imports._is_plugin_name')
    @patch('sideboard.internal.imports._yield_module_names_and_filenames_from_callstack')
    def test_virtualenv_import_returning_a_plugin(self, mock_module_and_file_names, mock_is_plugin_name, mock_venv_name):
        mock_module_and_file_names.return_value = [
            ('bax', '/opt/sideboard/plugins/foo-plugin/env/lib/python2.7/site-packages/bax.pyc'),
        ]
        mock_venv_name.return_value = 'foo'
        mock_is_plugin_name.side_effect = lambda name: name == 'foo'
        self.assertEqual(sideboard.internal.imports._get_sideboard_plugin_where_import_originated(), 'foo')

    @patch('sideboard.internal.imports._get_sideboard_plugin_where_import_originated')
    @patch('sideboard.internal.imports.use_plugin_virtualenv')
    def test_that_not_finding_plugin_just_defers_to_original_import(self, mock_use_plugin, mock_get_plugin):
        assert not mock_use_plugin.called
        mock_get_plugin.return_value = None
        assert not mock_get_plugin.called
        mock_import = mock.Mock()
        test_import = sideboard.internal.imports._import_overrider(mock_import, mock.MagicMock(spec=threading.RLock()))

        import_args = ['something', 'something_else']
        import_kwargs = dict(some_third_thing="foo")
        test_import(*import_args, **import_kwargs)
        assert mock_get_plugin.called
        assert not mock_use_plugin.called
        mock_import.assert_called_once_with(*import_args, **import_kwargs)

    @patch('sideboard.internal.imports._get_sideboard_plugin_where_import_originated')
    @patch('sideboard.internal.imports.use_plugin_virtualenv')
    def test_that_finding_a_plugin_activates_use_plugin_virtualenv(self, mock_use_plugin, mock_get_plugin):
        assert not mock_use_plugin.called
        mock_get_plugin.return_value = 'some_plugin_name'
        assert not mock_get_plugin.called
        mock_import = mock.Mock()
        test_import = sideboard.internal.imports._import_overrider(mock_import, mock.MagicMock(spec=threading.RLock()))

        import_args = ['something', 'something_else']
        import_kwargs = dict(some_third_thing="foo")
        test_import(*import_args, **import_kwargs)
        assert mock_get_plugin.called
        mock_use_plugin.assert_called_once_with('some_plugin_name')
        # we still call import
        mock_import.assert_called_once_with(*import_args, **import_kwargs)