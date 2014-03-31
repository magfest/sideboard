from __future__ import unicode_literals, print_function
import os
import pkg_resources
import sys
import glob

from itertools import chain

import paver.virtual as virtual
from paver.easy import *  # paver docs pretty consistently want you to do this
from paver.path import path  # primarily here to support the rmtree method of a path object

__here__ = path(os.path.abspath(os.path.dirname(__file__)))

PLUGINS_DIR = __here__ / path('plugins')
SIDEBOARD_DIR = __here__ / path('sideboard')


def bootstrap_plugin_venv(plugin_path, plugin_name, venv_name='env'):
    """
    make a virtualenv with the specified name at the specified location

    :param plugin_path: the absolute path to the plugin folder
    :type plugin_path: unicode
    :param plugin_name: the name of the plugin
    :type plugin_name: unicode
    :param plugin_name: the name of the venv folder (default: env)
    :type plugin_name: unicode
    """

    assert os.path.exists(plugin_path), "{} doesn't exist".format(plugin_path)
    intended_venv = path(plugin_path) / path(venv_name)

    bootstrap_venv(intended_venv, plugin_name)


def bootstrap_venv(intended_venv, bootstrap_name=None):
    # bootstrap wants options available in options.virtualenv which is a Bunch
    if os.path.exists(intended_venv):
        intended_venv.rmtree()

    venv = getattr(options, 'virtualenv', Bunch())

    with open(path(os.path.dirname(intended_venv)) / path('requirements.txt')) as reqs:
        # we expect this to be reversed in setup.py
        venv.packages_to_install = [line.strip() for line in reqs.readlines()[::-1] if line.strip()]

    venv.dest_dir = intended_venv
    if bootstrap_name:
        venv.script_name = '{}-bootstrap.py'.format(bootstrap_name)

    options.virtualenv = venv
    virtual.bootstrap()
    if sys.executable:
        # if we can figure out the python associated with this paver, execute the bootstrap script
        # and we can expect the virtual env will then exist
        sh('{python_path} "{script_name}"'.format(python_path=sys.executable,
                                                  script_name=venv.script_name))

        # we're going to assume that worked, so run setup.py develop
        develop_plugin(intended_venv)


@task
@cmdopts([('plugin=', 'p',
           'name (not necessarily repo name) of the plugin to make a virtualenv for')])
def make_plugin_venv(options):
    """
    make a virtualenv named 'env' for the specified plugin
    """
    # TODO: disassociate plugin name with folder name
    bootstrap_plugin_venv(PLUGINS_DIR / options.make_plugin_venv.plugin,
                          options.make_plugin_venv.plugin)


@task
def make_plugin_venvs():
    """
    make a virtualenv named 'env' for plugin found in the plugins folder
    """

    for plugin_dir in collect_plugin_dirs():

        bootstrap_plugin_venv(plugin_dir, os.path.split(plugin_dir)[-1])


def guess_plugin_module_name(containing_folder):
    """
    given a containing folder, guess what the plugin name should be

    :param containing_folder: the folder that possibly contains a plugin
    :type containing_folder: unicode
    :return:
    """
    # TODO: this only works as long as insist that the plugin dir be the module name
    return os.path.split(containing_folder)[-1].replace('-', '_')


def collect_plugin_dirs(module=False):
    """
    :param module: if True, return the module within a plugin directory, else (default) just return
        the plugin directory
    :return: the plugin folders in a form that can be iterated over
    :rtype: collections.Iterator
    """
    for potential_folder in glob.glob(PLUGINS_DIR / path('*')):
        if all(os.path.exists(os.path.join(potential_folder, req_file))
               for req_file in ('setup.py', 'requirements.txt')):
            if module:
                yield os.path.join(potential_folder, guess_plugin_module_name(potential_folder))
            else:
                yield potential_folder


@task
def make_sideboard_venv():
    """
    make a virtualenv for the sideboard project
    """

    bootstrap_venv(__here__ / path('env'), 'sideboard')
    develop_sideboard()


def develop_plugin(virtual_env):
    # TODO: this is very hard-coded and should be done better
    sh('cd {module_dir};{python_path} setup.py develop'.format(
        python_path=os.path.join(virtual_env, 'bin', 'python'),
        module_dir=os.path.dirname(virtual_env)))

def develop_sideboard():
    # TODO: this is very hard-coded and should be done better
    sh('{python_path} setup.py develop'.format(python_path=os.path.join('env', 'bin', 'python')))


@task
@needs(['make_plugin_venvs', 'make_sideboard_venv'])
def make_all_venvs():
    """
    make all the plugin virtual environments and the overall sideboard env
    """


@task
def pull_plugins():
    """
    invoke git pull from each plug-in directory, your global git either needs to allow this to \
happen auth-free, or you need to enter your credentials each time
    """
    for plugin_dir in collect_plugin_dirs():
        sh('cd "{}";git pull'.format(plugin_dir))


@task
def assert_all_files_import_unicode_literals():
    """
    error if a python file is found in sideboard or plugins that does not import unicode_literals
    """
    all_files_found = []
    cmd = ("find '%s' -name '*.py' ! -size 0 "
           "-exec grep -RL 'from __future__ import.*unicode_literals.*$' {} \;")
    for test_dir in chain(['sideboard'], collect_plugin_dirs(module=True)):
        output = sh(cmd % test_dir, capture=True)
        if output:
            all_files_found.append(output)

    if all_files_found:
        print('the following files did not include "from __future__ import unicode_literals":')
        print(''.join(all_files_found))
        raise BuildFailure("there were files that didn't include "
                           '"from __future__ import unicode_literals"')

@task
def assert_all_projects_correctly_define_a_version():
    """
    error if there are plugins where we can't find a version defined
    """
    all_files_with_bad_versions = []
    # FIXME: should we try to execfile? that's what setup.py is going to do anyway
    cmd = (r'grep -xP "__version__\s*=\s*[\'\"][0-9]+\.[0-9]+(\.[0-9]+)?[\'\+]" {0}/_version.py')
    for test_dir in chain(['sideboard'], collect_plugin_dirs(module=True)):
        try:
            sh(cmd.format(test_dir))
        except BuildFailure:
            all_files_with_bad_versions.append(test_dir)


    if all_files_with_bad_versions:
        print('the following directories do not include a _version.py file with __version__ '
              'specified:')
        print('\n'.join(all_files_with_bad_versions))
        print('Your plugin should be in agreement with this stack overflow post:')
        print('http://stackoverflow.com/questions/458550/'
              'standard-way-to-embed-version-into-python-package/7071358#7071358')

        raise BuildFailure("there were projects that didn't include correctly specify __version__")

@task
@needs(['assert_all_files_import_unicode_literals',
        'assert_all_projects_correctly_define_a_version'])
def run_all_assertions():
    """
    run all the assertion tasks that sideboard supports
    """

@task
@cmdopts([
    ('name=', 'n', 'name of the plugin to create'),
    ('drop', 'd', 'delete existing plugin if present'),
    ('no_webapp', 'w', 'do not expose webpages in the plugin'),
    ('no_sqlalchemy', 'a', 'do not use SQLAlchemy in the plugin'),
    ('no_service', 'r', 'do not expose a service in the plugin'),
    ('cli', 'c', 'make this a cli application; implies -w/-r')
])
def create_plugin(options):
    """create a plugin skeleton to start a new project"""

    # this is actually needed thanks to the skeleton using jinja2 (and six, although that's changeable)
    try:
       pkg_resources.get_distribution("sideboard")
    except pkg_resources.DistributionNotFound:
       raise BuildFailure("This command must be run from within a configured virtual environment.")

    plugin_name = options.create_plugin.name

    if getattr(options.create_plugin, 'drop', False) and (PLUGINS_DIR / path(plugin_name.replace('_', '-'))).exists():
        # rmtree fails if the dir doesn't exist apparently
        (PLUGINS_DIR / path(plugin_name.replace('_', '-'))).rmtree()
    
    kwargs = {}
    for opt in ['webapp', 'sqlalchemy', 'service']:
        kwargs[opt] = not getattr(options.create_plugin, 'no_' + opt, False)
    kwargs['cli'] = getattr(options.create_plugin, 'cli', False)
    if kwargs['cli']:
        kwargs['webapp'] = False
        kwargs['service'] = False
    
    from data.paver import skeleton
    skeleton.create_plugin(PLUGINS_DIR, plugin_name, **kwargs)
    print('{} successfully created'.format(options.create_plugin.name))

@task
def clean():
    """
    clean all pyc and __pycache__ files
    """
    sh("find . -name '*.pyc' | xargs rm -f")
    sh("find . -name __pycache__ | xargs rm -fr")
