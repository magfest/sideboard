from __future__ import unicode_literals
import os

import pytest
from mock import Mock

from sideboard.config import parse_config, get_config_root


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


class TestSideboardConfigRoot(object):
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
