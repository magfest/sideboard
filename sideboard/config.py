from __future__ import unicode_literals
import os

from os import unlink
from copy import deepcopy
from tempfile import NamedTemporaryFile

import configobj
from validate import Validator


class ConfigurationError(RuntimeError):
    pass

def os_path_split_asunder(path, debug=False):
    """
    http://stackoverflow.com/a/4580931/171094
    """
    parts = []
    while True:
        newpath, tail = os.path.split(path)
        if newpath == path:
            assert not tail
            if path: parts.append(path)
            break
        parts.append(tail)
        path = newpath
    parts.reverse()
    return parts


def is_subdirectory(potential_subdirectory, expected_parent_directory):
    """
    Is the first argument a sub-directory of the second argument?

    :param potential_subdirectory:
    :param expected_parent_directory:
    :return: True if the potential_subdirectory is a child of the expected parent directory

    >>> is_subdirectory('/var/test2', '/var/test')
    False
    >>> is_subdirectory('/var/test', '/var/test2')
    False
    >>> is_subdirectory('var/test2', 'var/test')
    False
    >>> is_subdirectory('var/test', 'var/test2')
    False
    >>> is_subdirectory('/var/test/sub', '/var/test')
    True
    >>> is_subdirectory('/var/test', '/var/test/sub')
    False
    >>> is_subdirectory('var/test/sub', 'var/test')
    True
    >>> is_subdirectory('var/test', 'var/test')
    True
    >>> is_subdirectory('var/test', 'var/test/fake_sub/..')
    True
    >>> is_subdirectory('var/test/sub/sub2/sub3/../..', 'var/test')
    True
    >>> is_subdirectory('var/test/sub', 'var/test/fake_sub/..')
    True
    >>> is_subdirectory('var/test', 'var/test/sub')
    False
    """

    def _get_normalized_parts(path):
        return os_path_split_asunder(os.path.realpath(os.path.abspath(os.path.normpath(path))))

    # make absolute and handle symbolic links, split into components
    sub_parts = _get_normalized_parts(potential_subdirectory)
    parent_parts = _get_normalized_parts(expected_parent_directory)

    if len(parent_parts) > len(sub_parts):
        # a parent directory never has more path segments than its child
        return False

    # we expect the zip to end with the short path, which we know to be the parent
    return all(part1==part2 for part1, part2 in zip(sub_parts, parent_parts))


def get_dirnames(pyname):
    module_dir = os.path.dirname(os.path.abspath(pyname))

    # this can blow up if we decide that production plugins are somewhere different
    expected_prod_plugin_dir = ('/', 'opt', 'sideboard', 'plugins')
    if is_subdirectory(pyname, os.path.join(*expected_prod_plugin_dir)):
        # we're in production, so the root, is really the directory in plugins that holds our
        # virtualenv
        root_dir = os.path.join(*os_path_split_asunder(pyname)[:len(expected_prod_plugin_dir) + 1])
    else:
        root_dir = os.path.realpath(os.path.join(module_dir, '..'))

    return module_dir, root_dir


def get_config_files(requesting_file_path, plugin):
    """
    get a list of the config files that should be parsed, merged and returned by parse_config

    :param requesting_file_path: the path of the file requesting a parsed config file
    :param plugin: if True (default) return the expected production-config directory. This is based
        on the folder name of the requesting module, although in the future this could be the
        based on the plugin name, no matter where you request a config from.
    :return: list of config file paths that should be parsed, this list is ordered from lowest
        to highest priority
    :type: list
    """

    module_dir, root_dir = get_dirnames(requesting_file_path)
    module_name = os.path.basename(module_dir)

    # this first two are expected to be per-plugin (or sideboard itself)
    default_file_paths = ('development-defaults.ini', 'development.ini')

    if plugin:
        # TODO: this should ideally be the plugin name, even if it's overridden
        plugin_config_name = '%s.cfg' % module_name.replace('_', '-')
        extra_configs = [os.path.join('/etc', 'sideboard', 'plugins.d', plugin_config_name)]
    else:
        if module_name != 'sideboard':
            raise RuntimeError('Unexpected module name {!r} requesting "non-plugin" '
                               'configuration files'.format(module_name))

        extra_configs = [
            os.path.join('/etc', 'sideboard', 'sideboard-core.cfg'),
            os.path.join('/etc', 'sideboard', 'sideboard-server.cfg'),
        ]

        old_production_path = os.path.join('/etc', 'sideboard', 'sideboard.cfg')
        if os.path.exists(old_production_path):
            raise RuntimeError("Old-style production path {}, exists. Configuration you've set "
                               "should be migrated to one of the following new-style "
                               "configuration files:\n{}".format(old_production_path,
                                                                 '\n'.join(extra_configs)))

    return ([os.path.join(root_dir, default_path) for default_path in default_file_paths] +
            extra_configs)


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
    module_dir, root_dir = get_dirnames(requesting_file_path)

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
            from sideboard.lib import register_rpc_services
            register_rpc_services(config['rpc_services'])
        
        if 'default_url' in config:
            priority = config.get('default_url_priority', 0)
            if priority >= sideboard_config['default_url_priority']:
                sideboard_config['default_url'] = config['default_url']

    return config

config = parse_config(__file__, plugin=False)
