from __future__ import unicode_literals
import os

from sideboard.config import parse_config


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
