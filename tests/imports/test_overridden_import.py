from __future__ import unicode_literals
import threading

import mock
from mock import patch

import sideboard
from sideboard.internal import imports

def test_that_yield_frames_goes_most_recent_call_first():
    def a():
        def b():
            def c():
                # TODO: this is better done as an assertion that the c,b,a list is a subsequence of the co_names
                assert ['c', 'b', 'a'] == list(frame.f_code.co_name for frame in imports._yield_frames())[2:5]
                # item 0 is _yield_frames itself
                # item 1 is the generator expression that creates the list
            c()
        b()
    a()

def test_that_yield_module_names_goes_most_recent_call_first():
    from .overridden_import_modules_for_asserts.a import a_func
    # assert module_names[2] == 'tests.imports.overridden_import_modules_for_asserts.c'
    # assert module_names[3] == 'tests.imports.overridden_import_modules_for_asserts.b'
    # assert module_names[4] == 'tests.imports.overridden_import_modules_for_asserts.a'
    a_func()

# TODO: test exception cases from yield module name from callstack

def test_is_plugin_name():
    with patch.dict('sideboard.internal.imports._path_cache', {'foo': ['bar'], 'foo2': ['bar']}, clear=True), \
         patch.dict('sideboard.internal.imports._module_cache', {'foo': ['bar'], 'foo3': ['bar']},  clear=True):

        assert sideboard.internal.imports._is_plugin_name('foo')
        assert not sideboard.internal.imports._is_plugin_name('foo2')
        assert not sideboard.internal.imports._is_plugin_name('foo3')
        assert not sideboard.internal.imports._is_plugin_name('foo4')

def test_venv_plugin_name():
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

def test_venv_plugin_name_with_trailing_slash():

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
def test_simplest_case_for_import_origination(mock_module_and_file_names, mock_is_plugin_name):
    mock_module_and_file_names.return_value = [('foo.bar.baz.bax', 'foo/bar/baz/bax.py')]
    mock_is_plugin_name.return_value = True
    assert sideboard.internal.imports.get_current_plugin() == 'foo'

@patch('sideboard.internal.imports._is_plugin_name')
@patch('sideboard.internal.imports._yield_module_names_and_filenames_from_callstack')
def test_empty_callstack_case_for_import_origination(mock_module_and_file_names, mock_is_plugin_name):
    mock_module_and_file_names.return_value = []
    mock_is_plugin_name.return_value = True
    assert sideboard.internal.imports.get_current_plugin() is None

@patch('sideboard.internal.imports._is_plugin_name')
@patch('sideboard.internal.imports._yield_module_names_and_filenames_from_callstack')
def test_not_from_a_plugin_case_for_import_origination(mock_module_and_file_names, mock_is_plugin_name):
    mock_module_and_file_names.return_value = [
        ('foo.bar.baz.bax', 'foo/bar/baz/bax/__init__.py'),
        ('foo.bar.baz.bax.buz', 'foo2/bar/baz/bax/buz/__init__.py'),
        ('foo.bar.baz.bax.buz.bux', 'foo/bar/baz/bax/buz/buz/__init__.py')
    ]
    mock_is_plugin_name.return_value = False
    assert sideboard.internal.imports.get_current_plugin() is None

@patch('sideboard.internal.imports._venv_plugin_name')
@patch('sideboard.internal.imports._is_plugin_name')
@patch('sideboard.internal.imports._yield_module_names_and_filenames_from_callstack')
def test_virtualenv_import_returning_a_plugin(mock_module_and_file_names, mock_is_plugin_name, mock_venv_name):
    mock_module_and_file_names.return_value = [
        ('bax', '/opt/sideboard/plugins/foo-plugin/env/lib/python2.7/site-packages/bax.pyc'),
    ]
    mock_venv_name.return_value = 'foo'
    mock_is_plugin_name.side_effect = lambda name: name == 'foo'
    assert sideboard.internal.imports.get_current_plugin(), 'foo'
