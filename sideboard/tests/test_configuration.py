from __future__ import unicode_literals
import os

import pytest
from mock import Mock

from sideboard.lib import config
from sideboard.config import get_config_files, get_config_overrides, \
    get_config_root, get_module_and_root_dirs, parse_config, uniquify


def test_uniquify():
    pytest.raises(AssertionError, uniquify, None)
    assert [] == uniquify([])
    assert ['a', 'b', 'c'] == uniquify(['a', 'b', 'c'])
    assert ['a', 'b', 'c', 'd', 'e'] == uniquify(['a', 'b', 'a', 'c', 'a', 'd', 'a', 'e'])
    assert ['a'] == uniquify(['a', 'a', 'a', 'a', 'a', 'a', 'a', 'a'])


@pytest.mark.skipif(
    'SIDEBOARD_CONFIG_OVERRIDES' not in os.environ,
    reason='SIDEBOARD_CONFIG_OVERRIDES not set')
def test_test_defaults_ini():
    """
    Verify that the tests were launched using `test-defaults.ini`.

    All of the other sideboard tests will succeed whether `test-defaults.ini`
    or `development-defaults.ini` is used. This test is actually a functional
    test of sorts; it verifies the test suite itself was launched with
    `SIDEBOARD_CONFIG_OVERRIDES="test-defaults.ini"`.

    The test is skipped rather than failing if the tests were launched without
    setting `SIDEBOARD_CONFIG_OVERRIDES`.
    """
    from sideboard.lib import config
    # is_test_running is ONLY set in test-defaults.ini
    assert config.get('is_test_running')


class SideboardConfigurationTest(object):
    sideboard_root = os.path.abspath(os.path.join(__file__, '..', '..', '..'))
    dev_test_plugin_path = os.path.join(sideboard_root, 'plugins', 'configuration-test',
                                        'configuration_test', '__init__.py')
    production_test_plugin_path = os.path.join('/', 'opt', 'sideboard', 'plugins', 'configuration-test',
                                               'env', 'lib', 'python{py_version}', 'site-packages',
                                               'configuration_test-{plugin_ver}-{py_version}.egg',
                                               'configuration_test', '__init__.py')

    def test_parse_config_adding_root_and_module_root_for_dev(self):
        test_config = parse_config(self.dev_test_plugin_path)
        expected_module_root = os.path.dirname(self.dev_test_plugin_path)
        expected_root = os.path.dirname(expected_module_root)
        assert test_config.get('module_root') == expected_module_root
        assert test_config.get('root') == expected_root

    def test_parse_config_adding_root_and_module_root_for_production(self):
        for path_values in (dict(py_version='2.7', plugin_ver='1.0'),):
            test_path = self.production_test_plugin_path.format(**path_values)
            test_config = parse_config(test_path)
            expected_module_root = os.path.dirname(test_path)
            expected_root = os.path.join('/', 'opt', 'sideboard', 'plugins', 'configuration-test')
            assert test_config.get('module_root') == expected_module_root
            assert test_config.get('root') == expected_root


class TestSideboardGetConfigFiles(object):
    @pytest.fixture
    def config_overrides_unset(self, monkeypatch):
        monkeypatch.delenv('SIDEBOARD_CONFIG_OVERRIDES', raising=False)

    @pytest.fixture
    def config_overrides_set(self, monkeypatch):
        monkeypatch.setenv('SIDEBOARD_CONFIG_OVERRIDES', 'test-defaults.ini')

    @pytest.fixture
    def plugin_dirs(self):
        module_path = '/fake/sideboard/plugins/test-plugin/test_plugin'
        root_path = os.path.join(config['plugins_dir'], 'test-plugin')
        return (module_path, root_path)

    @pytest.fixture
    def sideboard_dirs(self):
        module_path = '/fake/sideboard/sideboard'
        root_path = '/fake/sideboard'
        return (module_path, root_path)

    def test_get_module_and_root_dirs_plugin(self, plugin_dirs):
        assert plugin_dirs == get_module_and_root_dirs(
            os.path.join(plugin_dirs[0], 'config.py'), is_plugin=True)

    def test_get_module_and_root_dirs_sideboard(self, sideboard_dirs):
        assert sideboard_dirs == get_module_and_root_dirs(
            os.path.join(sideboard_dirs[0], 'config.py'), is_plugin=False)

    def test_get_config_files_plugin(self, plugin_dirs, config_overrides_unset):

        expected = [
            '/etc/sideboard/plugins.d/test-plugin.cfg',
            os.path.join(plugin_dirs[1], 'development-defaults.ini'),
            os.path.join(plugin_dirs[1], 'development.ini')]
        assert expected == get_config_files(
            os.path.join(plugin_dirs[0], 'config.py'), is_plugin=True)

    def test_get_config_files_sideboard(self, sideboard_dirs, config_overrides_unset):

        expected = [
            '/etc/sideboard/sideboard-core.cfg',
            '/etc/sideboard/sideboard-server.cfg',
            os.path.join(sideboard_dirs[1], 'development-defaults.ini'),
            os.path.join(sideboard_dirs[1], 'development.ini')]
        assert expected == get_config_files(
            os.path.join(sideboard_dirs[0], 'config.py'), is_plugin=False)

    def test_get_config_files_plugin_with_overrides(self, plugin_dirs, config_overrides_set):

        expected = [
            '/etc/sideboard/plugins.d/test-plugin.cfg',
            os.path.join(plugin_dirs[1], 'test-defaults.ini'),
            os.path.join(plugin_dirs[1], 'test.ini')]
        assert expected == get_config_files(
            os.path.join(plugin_dirs[0], 'config.py'), is_plugin=True)

    def test_get_config_files_sideboard_with_overrides(self, sideboard_dirs, config_overrides_set):

        expected = [
            '/etc/sideboard/sideboard-core.cfg',
            '/etc/sideboard/sideboard-server.cfg',
            os.path.join(sideboard_dirs[1], 'test-defaults.ini'),
            os.path.join(sideboard_dirs[1], 'test.ini')]
        assert expected == get_config_files(
            os.path.join(sideboard_dirs[0], 'config.py'), is_plugin=False)


class TestSideboardGetConfigOverrides(object):
    @pytest.fixture(params=[
        (None, ['development-defaults.ini', 'development.ini']),
        ('test-defaults.ini', ['test-defaults.ini', 'test.ini']),
        ('test.ini;development.ini;test.ini', ['test.ini', 'development.ini']),
        ('test-defaults.ini;test-defaults.ini', ['test-defaults.ini', 'test.ini']),
        (' /absolute/path.ini ', ['/absolute/path.ini']),
        ('/absolute/path.cfg', ['/absolute/path.cfg']),
        (' relative/path.ini ', ['relative/path.ini']),
        ('relative/path.cfg', ['relative/path.cfg']),
        ('/absolute/path.cfg;relative/path.ini', ['/absolute/path.cfg', 'relative/path.ini']),
        ('relative/path.cfg;/absolute/path.ini', ['relative/path.cfg', '/absolute/path.ini']),
        ('  /absolute/path.cfg  ; relative/path.ini ', ['/absolute/path.cfg', 'relative/path.ini']),
        (' /absolute/path-defaults.ini ', ['/absolute/path-defaults.ini', '/absolute/path.ini']),
        ('/absolute/path-defaults.cfg', ['/absolute/path-defaults.cfg', '/absolute/path.cfg']),
        (' relative/path-defaults.ini ', ['relative/path-defaults.ini', 'relative/path.ini']),
        ('relative/path-defaults.cfg', ['relative/path-defaults.cfg', 'relative/path.cfg']),
        ('/absolute/path-defaults.cfg;relative/path-defaults.ini', [
            '/absolute/path-defaults.cfg',
            '/absolute/path.cfg',
            'relative/path-defaults.ini',
            'relative/path.ini'
        ])
    ])
    def config_overrides(self, request, monkeypatch):
        if request.param[0] is None:
            monkeypatch.delenv('SIDEBOARD_CONFIG_OVERRIDES', raising=False)
        else:
            monkeypatch.setenv('SIDEBOARD_CONFIG_OVERRIDES', request.param[0])
        return request.param[1]

    def test_get_config_overrides(self, config_overrides):
        assert get_config_overrides() == config_overrides


class TestSideboardGetConfigRoot(object):
    @pytest.fixture
    def dir_missing(self, monkeypatch):
        monkeypatch.setattr(os.path, 'isdir', Mock(return_value=False))

    @pytest.fixture
    def dir_exists(self, monkeypatch):
        monkeypatch.setattr(os.path, 'isdir', Mock(return_value=True))

    @pytest.fixture
    def dir_readable(self, monkeypatch):
        monkeypatch.setattr(os, 'access', Mock(return_value=True))

    @pytest.fixture
    def dir_unreadable(self, monkeypatch):
        monkeypatch.setattr(os, 'access', Mock(return_value=False))

    @pytest.fixture
    def custom_root(self, monkeypatch):
        monkeypatch.setitem(os.environ, 'SIDEBOARD_CONFIG_ROOT', '/custom/location')

    def test_valid_etc_sideboard(self, dir_exists, dir_readable):
        assert get_config_root() == '/etc/sideboard'

    def test_no_etc_sideboard(self, dir_missing):
        assert get_config_root() == '/etc/sideboard'

    def test_etc_sideboard_unreadable(self, dir_exists, dir_unreadable):
        pytest.raises(AssertionError, get_config_root)

    def test_overridden_missing(self, custom_root, dir_missing):
        pytest.raises(AssertionError, get_config_root)

    def test_overridden_unreadable(self, custom_root, dir_exists, dir_unreadable):
        pytest.raises(AssertionError, get_config_root)

    def test_overridden_valid(self, custom_root, dir_exists, dir_readable):
        assert get_config_root() == '/custom/location'
