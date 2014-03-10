from __future__ import unicode_literals

import os
import unittest

from sideboard.internal.imports import get_modules

__here__ = os.path.dirname(os.path.abspath(__file__))
__plugin_container__ = os.path.abspath(os.path.join(__here__, '..', 'plugins'))
site_packages = os.path.join('env', 'lib', 'python2.7', 'site-packages')


def path(plugin_container, plugin):
    return os.path.join(__plugin_container__, plugin_container,
                        plugin, site_packages)


def rewrite_egglink(plugin_container, plugin):
    """
    Hack to replace the egg-link file created by setup.py develop.
    This simulates `setup.py develop`ing for testing purposes.
    See also SIDEBOARD-79
    """
    site_packages_path = path(plugin_container, plugin)
    egglink_filename = os.path.join(site_packages_path, plugin + '.egg-link')
    with open(egglink_filename, 'w') as f:
        f.write(egglink_path(plugin_container, plugin) + '\n.')


def egglink_path(plugin_container, plugin):
    return os.path.join(__plugin_container__, plugin_container, plugin)


distribute_modules = [
    'easy_install',
    '_markerlib',
    '_markerlib.markers',
    'pkg_resources',
    'setuptools',
    'setuptools.archive_util',
    'setuptools.command',
    'setuptools.command.alias',
    'setuptools.command.bdist_egg',
    'setuptools.command.bdist_rpm',
    'setuptools.command.bdist_wininst',
    'setuptools.command.build_ext',
    'setuptools.command.build_py',
    'setuptools.command.develop',
    'setuptools.command.easy_install',
    'setuptools.command.egg_info',
    'setuptools.command.install_egg_info',
    'setuptools.command.install_lib',
    'setuptools.command.install',
    'setuptools.command.install_scripts',
    'setuptools.command.register',
    'setuptools.command.rotate',
    'setuptools.command.saveopts',
    'setuptools.command.sdist',
    'setuptools.command.setopt',
    'setuptools.command.test',
    'setuptools.command.upload_docs',
    'setuptools.command.upload',
    'setuptools.depends',
    'setuptools.dist',
    'setuptools.extension',
    'setuptools.package_index',
    'setuptools.sandbox',
    'setuptools.tests',
    'setuptools.tests.doctest',
    'setuptools.tests.py26compat',
    'setuptools.tests.server',
    'setuptools.tests.test_bdist_egg',
    'setuptools.tests.test_build_ext',
    'setuptools.tests.test_develop',
    'setuptools.tests.test_dist_info',
    'setuptools.tests.test_easy_install',
    'setuptools.tests.test_markerlib',
    'setuptools.tests.test_packageindex',
    'setuptools.tests.test_resources',
    'setuptools.tests.test_sandbox',
    'setuptools.tests.test_sdist',
    'setuptools.tests.test_test',
    'setuptools.tests.test_upload_docs',
    'site',
]

pip_modules = [
    'pip',
    'pip.backwardcompat',
    'pip.backwardcompat.socket_create_connection',
    'pip.backwardcompat.ssl_match_hostname',
    'pip.basecommand',
    'pip.baseparser',
    'pip.cmdoptions',
    'pip.commands',
    'pip.commands.bundle',
    'pip.commands.completion',
    'pip.commands.freeze',
    'pip.commands.help',
    'pip.commands.install',
    'pip.commands.list',
    'pip.commands.search',
    'pip.commands.show',
    'pip.commands.uninstall',
    'pip.commands.unzip',
    'pip.commands.zip',
    'pip.download',
    'pip.exceptions',
    'pip.index',
    'pip.locations',
    'pip.log',
    'pip.__main__',
    'pip.req',
    'pip.runner',
    'pip.status_codes',
    'pip.util',
    'pip.vcs',
    'pip.vcs.bazaar',
    'pip.vcs.git',
    'pip.vcs.mercurial',
    'pip.vcs.subversion',
]

paver_modules = [
    'paver',
    'paver.bzr',
    'paver.command',
    'paver.defaults',
    'paver.deps',
    'paver.deps.path2',
    'paver.deps.path3',
    'paver.deps.six',
    'paver.doctools',
    'paver.easy',
    'paver.git',
    'paver.misctasks',
    'paver.options',
    'paver.path25',
    'paver.path',
    'paver.release',
    'paver.runtime',
    'paver.setuputils',
    'paver.ssh',
    'paver.svn',
    'paver.tasks',
    'paver.version',
    'paver.virtual',
]

rdf_modules = [
    'rdflib',
    'rdflib.exceptions',
    'rdflib.collection',
    'rdflib.compare',
    'rdflib.events',
    'rdflib.serializer',
    'rdflib.graph',
    'rdflib.store',
    'rdflib.term',
    'rdflib.query',
    'rdflib.util',
    'rdflib.parser',
    'rdflib.plugin',
    'rdflib.namespace',
    'rdflib.plugins.sleepycat',
    'rdflib.plugins',
    'rdflib.plugins.memory',
    'rdflib.plugins.serializers.nt',
    'rdflib.plugins.serializers.turtle',
    'rdflib.plugins.serializers.rdfxml',
    'rdflib.plugins.serializers',
    'rdflib.plugins.serializers.n3',
    'rdflib.plugins.serializers.xmlwriter',
    'rdflib.plugins.serializers.trix',
    'rdflib.plugins.parsers.nt',
    'rdflib.plugins.parsers.rdfxml',
    'rdflib.plugins.parsers.notation3',
    'rdflib.plugins.parsers',
    'rdflib.plugins.parsers.ntriples',
    'rdflib.plugins.parsers.trix',
    'rdflib.plugins.parsers.rdfa.literal',
    'rdflib.plugins.parsers.rdfa.embeddedrdf',
    'rdflib.plugins.parsers.rdfa.state',
    'rdflib.plugins.parsers.rdfa',
    'rdflib.plugins.parsers.rdfa.parse',
    'rdflib.plugins.parsers.rdfa.options',
    'rdflib.plugins.parsers.rdfa.transform',
    'rdflib.plugins.parsers.rdfa.transform.headabout',
]


class GetModulesTest(unittest.TestCase):
    maxDiff = None

    def test_simple_one(self):
        self.assertItemsEqual(
            get_modules(path('simple', 'one')),
            distribute_modules + pip_modules
        )

    def test_simple_two(self):
        self.assertItemsEqual(
            get_modules(path('simple', 'two')),
            pip_modules + ['setuptools']
        )

    def test_nested_tree(self):
        rewrite_egglink('nested', 'tree')
        self.assertItemsEqual(
            get_modules(path('nested', 'tree')),
            [
                'tree',
                'tree.leaf1',
                'tree.branch1',
                'tree.branch1.leaf2',
                'tree.branch2',
                'tree.branch2.branch3',
                'tree.branch2.branch3.leaf3',
            ] + pip_modules + distribute_modules
        )

    def test_manypackages_multi(self):
        rewrite_egglink('manypackages', 'multi')
        self.assertItemsEqual(
            get_modules(path('manypackages', 'multi')),
            pip_modules + distribute_modules + [
                'configobj',
                'mock',
                'validate',
            ] + paver_modules
        )

    def test_different_versions_rdflib3_0_0(self):
        rewrite_egglink('different_versions', 'rdflib3_0_0')
        self.assertItemsEqual(
            get_modules(path('different_versions', 'rdflib3_0_0')),
            pip_modules + distribute_modules + rdf_modules +
            ['rdflib3_0_0', 'rdflib.t']
        )

    def test_different_versions_rdflib3_1_0(self):
        rewrite_egglink('different_versions', 'rdflib3_1_0')
        self.assertItemsEqual(
            get_modules(path('different_versions', 'rdflib3_1_0')),
            pip_modules + distribute_modules + rdf_modules +
            ['rdflib3_1_0']
        )

    # TODO need source egg other than pip and distribute
