from __future__ import unicode_literals
import os

from os import unlink
from copy import deepcopy
from tempfile import NamedTemporaryFile

import configobj
from validate import Validator


class ConfigurationError(RuntimeError):
    pass


def get_config_root():
    """
    Returns the configuration root for the system, which defaults to '/etc/sideboard'.
    If the SIDEBOARD_CONFIG_ROOT environment variable is set, its contents will be returned instead.
    """
    config_root = os.environ.get('SIDEBOARD_CONFIG_ROOT', '/etc/sideboard')
    assert os.path.isdir(config_root) and os.access(config_root, os.R_OK), '{!r} directory is not readable'.format(config_root)
    return config_root


def get_dirnames(pyname, plugin):
    """
    Sideboard and its plugins often want to find other files.  Sometimes they
    need files which ship as part of the module itself, and for those they need
    to know the module directory.  Other times they might need files which are
    bundled with their Git repo or which shipped with their RPM, and for those
    they need to know their "root" directory.  This "root" directory in
    development is just the root of the Git repo and in production is the
    package under the configured "plugins_dir" directory.

    These two directories are also automatically inserted into plugin config
    files as "root" and "module_root" and are available for interpolation.  For
    example, a plugin could have a line in their config file like
        template_dir = "%(module_root)s/templates"
    and that would be interpolated to the correct absolute path.

    This function takes two parameters:
    pyname: the __file__ of the module needing to know these directories
    plugin: boolean indicating whether this is a plugin or Sideboard itself
    """
    module_dir = os.path.dirname(os.path.abspath(pyname))
    if plugin:
        from sideboard.lib import config
        plugin_name = os.path.basename(module_dir)
        root_dir = os.path.join(config['plugins_dir'], plugin_name.replace('_', '-'))
    else:
        root_dir = os.path.realpath(os.path.join(module_dir, '..'))
    return module_dir, root_dir


def get_config_files(requesting_file_path, plugin):
    """
    Returns a list of absolute paths to config files to be parsed by ConfigObj,
    which allows subsequent files to override values in earlier files.  We parse
    the following files in this order:
    -> development-defaults.ini, which can be checked into source control and
        include whatever we want to be present in a development environment
    -> development.ini, which shouldn't be checked into source control, allowing
        a developer to include local settings not shared with others
    -> /etc/sideboard/plugins.d/<PLUGIN_NAME>.cfg, which is the config file we
        expect in production; the others shouldn't exist on a real install

    When developing on a machine with an installed production config file, we
    might want to ignore the "real" config file and limit ourselves to only the
    development files.  This behavior is turned on by setting the environment
    variable SIDEBOARD_MODULE_TESTING to any value.  (This environment variable
    is also used elsewhere to turn off automatically loading all plugins in
    order to facilitate testing modules which rely on Sideboard but which are
    not themselves Sideboard plugins.)

    This function takes the following parameters:
    requesting_file_path: the Python __file__ of the module which is parsing its
                          config; used to locate development config files
    plugin: boolean indicating whether config is being parsed for a plugin or
            for Sideboard itself, since this affects which filenames we return
    """
    config_root = get_config_root()
    module_dir, root_dir = get_dirnames(requesting_file_path, plugin)
    module_name = os.path.basename(module_dir)
    default_file_paths = ('development-defaults.ini', 'development.ini')

    if 'SIDEBOARD_MODULE_TESTING' in os.environ:
        extra_configs = []
    elif plugin:
        extra_configs = [os.path.join(config_root, 'plugins.d', '{}.cfg'.format(module_name.replace('_', '-')))]
    else:
        assert module_name == 'sideboard', 'Unexpected module name {!r} requesting "non-plugin" configuration files'.format(module_name)
        extra_configs = [
            os.path.join(config_root, 'sideboard-core.cfg'),
            os.path.join(config_root, 'sideboard-server.cfg'),
        ]

    return [os.path.join(root_dir, default_path) for default_path in default_file_paths] + extra_configs


def parse_config(requesting_file_path, plugin=True):
    """
    parse the configuration files for a given sideboard module (or the sideboard server itself). It's
    expected that this function is called from one of the files in the top-level of your module
    (typically the __init__.py file)

    :param requesting_file_path: the path of the file requesting a parsed config file. An example
        value is:
        ~/sideboard/plugins/plugin_nickname/plugin_module_name/__init__.py
        the containing directory (here, 'plugin_module_name') is assumed to be the module name of
        the plugin that is requesting a parsed config.
    :type requesting_file_path: binary or unicode string
    :param plugin: if True (default) add plugin-relevant information to the returning config. Also,
        treat it as if it's a plugin
    :type plugin: bool
    :return: the resulting configuration object
    :rtype: ConfigObj
    """
    module_dir, root_dir = get_dirnames(requesting_file_path, plugin)

    specfile = os.path.join(module_dir, 'configspec.ini')
    spec = configobj.ConfigObj(specfile, interpolation=False, list_values=False, encoding='utf-8', _inspec=True)

    # to allow more/better interpolations
    root_conf = ['root = "{}"\n'.format(root_dir), 'module_root = "{}"\n'.format(module_dir)]
    temp_config = configobj.ConfigObj(root_conf, interpolation=False, encoding='utf-8')

    for config_path in get_config_files(requesting_file_path, plugin):
        # this gracefully handles nonexistent files
        temp_config.merge(configobj.ConfigObj(config_path, encoding='utf-8', interpolation=False))

    # combining the merge files to one file helps configspecs with interpolation
    with NamedTemporaryFile(delete=False) as config_outfile:
        temp_config.write(config_outfile)
        temp_name = config_outfile.name

    config = configobj.ConfigObj(temp_name, encoding='utf-8', configspec=spec)

    validation = config.validate(Validator(), preserve_errors=True)
    unlink(temp_name)

    if validation is not True:
        raise ConfigurationError('configuration validation error(s) (): {!r}'.format(
            configobj.flatten_errors(config, validation))
        )

    if plugin:
        sideboard_config = globals()['config']
        config['plugins'] = deepcopy(sideboard_config['plugins'])
        if 'rpc_services' in config:
            from sideboard.lib._services import _register_rpc_services
            _register_rpc_services(config['rpc_services'])

        if 'default_url' in config:
            priority = config.get('default_url_priority', 0)
            if priority >= sideboard_config['default_url_priority']:
                sideboard_config['default_url'] = config['default_url']

    return config

config = parse_config(__file__, plugin=False)
