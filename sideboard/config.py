from __future__ import unicode_literals
import os
import re

from os import unlink
from copy import deepcopy
from tempfile import NamedTemporaryFile

import configobj
from validate import Validator


_defaults_re = re.compile(r'(.+)-defaults(\.\w+)$')


def uniquify(x):
    """
    Returns an ordered copy of `x` with duplicate items removed.

    >>> uniquify(['a', 'b', 'a', 'c', 'a', 'd', 'a', 'e'])
    ['a', 'b', 'c', 'd', 'e']

    """
    seen = set()
    return [i for i in x if i not in seen and not seen.add(i)]


class ConfigurationError(RuntimeError):
    pass


def get_config_overrides():
    """
    Returns a list of config file paths used to override the default config.

    The SIDEBOARD_CONFIG_OVERRIDES environment variable may be set to a
    semicolon separated list of absolute and/or relative paths. If the
    SIDEBOARD_CONFIG_OVERRIDES is set, this function returns a list of its
    contents, split on semicolons::

        # SIDEBOARD_CONFIG_OVERRIDES='/absolute/config.ini;relative/config.ini'
        return ['/absolute/config.ini', 'relative/config.ini']


    If any of the paths listed in SIDEBOARD_CONFIG_OVERRIDES ends with the
    suffix "<FILENAME>-defaults.<EXT>" then a similarly named path
    "<FILENAME>.<EXT>" will also be included::

        # SIDEBOARD_CONFIG_OVERRIDES='test-defaults.ini'
        return ['test-defaults.ini', 'test.ini']


    If the SIDEBOARD_CONFIG_OVERRIDES environment variable is NOT set, this
    function returns a list with two relative paths::

        return ['development-defaults.ini', 'development.ini']

    """
    config_overrides = os.environ.get(
        'SIDEBOARD_CONFIG_OVERRIDES',
        'development-defaults.ini')

    config_paths = []
    for config_path in uniquify([s.strip() for s in config_overrides.split(';')]):
        config_paths.append(config_path)
        m = _defaults_re.match(config_path)
        if m:
            config_paths.append(m.group(1) + m.group(2))

    return config_paths


def get_config_root():
    """
    Returns the config root for the system, defaults to '/etc/sideboard'.

    If the SIDEBOARD_CONFIG_ROOT environment variable is set, its contents
    will be returned instead.
    """
    default_root = '/etc/sideboard'
    config_root = os.environ.get('SIDEBOARD_CONFIG_ROOT', default_root)
    if config_root != default_root and not os.path.isdir(config_root):
        raise AssertionError('cannot find {!r} directory'.format(config_root))
    elif os.path.isdir(config_root) and not os.access(config_root, os.R_OK):
        raise AssertionError('{!r} directory is not readable'.format(config_root))
    return config_root


def get_module_and_root_dirs(requesting_file_path, is_plugin):
    """
    Returns the "module_root" and "root" directories for the given file path.

    Sideboard and its plugins often want to find other files.  Sometimes they
    need files which ship as part of the module itself, and for those they need
    to know the module directory.  Other times they might need files which are
    bundled with their Git repo or which shipped with their RPM, and for those
    they need to know their "root" directory.  This "root" directory in
    development is just the root of the Git repo and in production is the
    package under the configured "plugins_dir" directory.

    These two directories are also automatically inserted into plugin config
    files as "root" and "module_root" and are available for interpolation. For
    example, a plugin could have a line in their config file like::

        template_dir = "%(module_root)s/templates"


    and that would be interpolated to the correct absolute path.

    Parameters:
        requesting_file_path (str): The __file__ of the module requesting the
            "root" and "module_root" directories.
        is_plugin (bool): Indicates whether a plugin is making the request or
            Sideboard itself is making the request.
    """
    module_dir = os.path.dirname(os.path.abspath(requesting_file_path))
    if is_plugin:
        from sideboard.lib import config
        plugin_name = os.path.basename(module_dir)
        root_dir = os.path.join(config['plugins_dir'], plugin_name)
    else:
        root_dir = os.path.realpath(os.path.join(module_dir, '..'))
    return module_dir, root_dir


def get_config_files(requesting_file_path, is_plugin):
    """
    Returns a list of absolute paths to config files for the given file path.

    When the returned config files are parsed by ConfigObj each subsequent
    file will override values in earlier files.

    If `is_plugin` is `True` the first of the returned files is:

    * /etc/sideboard/plugins.d/<PLUGIN_NAME>.cfg, which is the config file we
      expect in production


    If `is_plugin` is `False` the first of the returned files is:

    * /etc/sideboard/sideboard-core.cfg, which is the sideboard core config
      file we expect in production

    * /etc/sideboard/sideboard-server.cfg, which is the sideboard server config
      file we expect in production


    The rest of the files returned are as follows, though we wouldn't expect
    these to exist on a production install (these are controlled by
    SIDEBOARD_CONFIG_OVERRIDES):

    * <PROJECT_DIR>/development-defaults.ini, which can be checked into source
      control and include whatever we want to be present in a development
      environment.

    * <PROJECT_DIR>/development.ini, which shouldn't be checked into source
      control, allowing a developer to include local settings not shared with
      others.


    When developing on a machine with an installed production config file, we
    might want to ignore the "real" config file and limit ourselves to only the
    development files.  This behavior is turned on by setting the environment
    variable SIDEBOARD_MODULE_TESTING to any value.  (This environment variable
    is also used elsewhere to turn off automatically loading all plugins in
    order to facilitate testing modules which rely on Sideboard but which are
    not themselves Sideboard plugins.)

    Parameters:
        requesting_file_path (str): The Python __file__ of the module
            requesting its config files.
        is_plugin (bool): Indicates whether a plugin is making the request or
            Sideboard itself is making the request, since this affects which
            config files we return.
    """
    config_root = get_config_root()
    module_dir, root_dir = get_module_and_root_dirs(requesting_file_path, is_plugin)
    module_name = os.path.basename(module_dir)

    if 'SIDEBOARD_MODULE_TESTING' in os.environ:
        base_configs = []
    elif is_plugin:
        base_configs = [os.path.join(config_root, 'plugins.d', '{}.cfg'.format(module_name.replace('_', '-')))]
    else:
        assert module_name == 'sideboard', 'Unexpected module name {!r} requesting "non-plugin" configuration files'.format(module_name)
        base_configs = [
            os.path.join(config_root, 'sideboard-core.cfg'),
            os.path.join(config_root, 'sideboard-server.cfg')]

    override_configs = [os.path.join(root_dir, config_path) for config_path in get_config_overrides()]

    return base_configs + override_configs


def parse_config(requesting_file_path, is_plugin=True):
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
    :param is_plugin: if True (default) add plugin-relevant information to the returning config. Also,
        treat it as if it's a plugin
    :type is_plugin: bool
    :return: the resulting configuration object
    :rtype: ConfigObj
    """
    module_dir, root_dir = get_module_and_root_dirs(requesting_file_path, is_plugin)

    specfile = os.path.join(module_dir, 'configspec.ini')
    spec = configobj.ConfigObj(specfile, interpolation=False, list_values=False, encoding='utf-8', _inspec=True)

    # to allow more/better interpolations
    root_conf = ['root = "{}"\n'.format(root_dir), 'module_root = "{}"\n'.format(module_dir)]
    temp_config = configobj.ConfigObj(root_conf, interpolation=False, encoding='utf-8')

    for config_path in get_config_files(requesting_file_path, is_plugin):
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

    if is_plugin:
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

config = parse_config(__file__, is_plugin=False)
