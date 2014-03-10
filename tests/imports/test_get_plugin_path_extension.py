from __future__ import unicode_literals

import os
import unittest

__here__ = os.path.dirname(os.path.abspath(__file__))
__plugin_container__ = os.path.abspath(os.path.join(__here__, '..', 'plugins'))


class GetPluginPathExtensionTest(unittest.TestCase):
    maxDiff = None

    def test(self):
        from sideboard.internal.imports import get_plugin_path_extension
        plugin_path = os.path.join(__plugin_container__, 'simple', 'one')
        site_packages = os.path.join('env', 'lib', 'python2.7', 'site-packages')
        expected = [
            plugin_path,
            os.path.join(plugin_path, site_packages),
            os.path.join(plugin_path, site_packages, 'pip-1.3.1-py2.7.egg'),
            os.path.join(plugin_path, site_packages, 'distribute-0.6.34-py2.7.egg'),
        ]
        self.assertItemsEqual(
            get_plugin_path_extension(plugin_path),
            expected
        )
