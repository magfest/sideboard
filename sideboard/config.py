from __future__ import unicode_literals
import pathlib
import json
import yaml
import os

from os import unlink
from copy import deepcopy
from tempfile import NamedTemporaryFile

import configobj
from validate import Validator


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

    Args:
        requesting_file_path (str): The __file__ of the module requesting the
            "root" and "module_root" directories.
        is_plugin (bool): Indicates whether a plugin is making the request or
            Sideboard itself is making the request.

    Returns:
        tuple(Path, Path, str): The "module_root" and "root" directories, and plugin name for the
            given module.
    """
    module_dir = pathlib.Path(requesting_file_path).parents[0]
    if is_plugin:
        from sideboard.lib import config
        plugin_name = module_dir.name
        root_dir = pathlib.Path(config['plugins_dir']) / plugin_name
        if '_' in plugin_name and not root_dir.exists():
            root_dir = pathlib.Path(config['plugins_dir']) / plugin_name.replace('_', '-')
    else:
        root_dir = module_dir.parents[0]
        plugin_name = "sideboard"
    return module_dir, root_dir, plugin_name


def get_config_files(requesting_file_path, is_plugin):
    """
    Returns a list of absolute paths to config files for the given file path.
    
    If the file is in a plugin we check the environment variable
    <PLUGIN NAME>_CONFIG_FILES and return any paths from there, seperated by ;

    Args:
        requesting_file_path (str): The Python __file__ of the module
            requesting its config files.
        is_plugin (bool): Indicates whether a plugin is making the request or
            Sideboard itself is making the request, since this affects which
            config files we return.

    Returns:
        list(str): List of absolute paths to config files for the given module.
    """
    module_dir, root_dir, plugin_name = get_module_and_root_dirs(requesting_file_path, is_plugin)
    config_files_str = os.environ.get(f"{plugin_name.upper()}_CONFIG_FILES", "")
    absolute_config_files = []
    if config_files_str:
        config_files = [pathlib.Path(x) for x in config_files_str.split(";")]
        for path in config_files:
            if path.is_absolute():
                if not path.exists():
                    raise ValueError(f"Config file {path} specified in {plugin_name.upper()}_CONFIG_FILES does not exist!")
                absolute_config_files.append(path)
            else:
                if not (root_dir / path).exists():
                    raise ValueError(f"Config file {root_dir / path} specified in {plugin_name.upper()}_CONFIG_FILES does not exist!")
                absolute_config_files.append(root_dir / path)
    return absolute_config_files

def normalize_name(name):
    return name.replace(".", "_")

def load_section_from_environment(path, section):
    """
    Looks for configuration in environment variables. 
    
    Args:
        path (str): The prefix of the current config section. For example,
            sideboard.ini:
                [cherrypy]
                server.thread_pool: 10
            would translate to sideboard_cherrypy_server.thread_pool
        section (configobj.ConfigObj): The section of the configspec to search
            for the current path in.
    """
    config = {}
    for setting in section:
        if setting == "__many__":
            prefix = f"{path}_"
            for envvar in os.environ:
                if envvar.startswith(prefix) and not envvar.split(prefix, 1)[1] in [normalize_name(x) for x in section]:
                    config[envvar.split(prefix, 1)[1]] = os.environ[envvar]
        else:
            if isinstance(section[setting], configobj.Section):
                child_path = f"{path}_{setting}"
                child = load_section_from_environment(child_path, section[setting])
                if child:
                    config[setting] = child
            else:
                name = normalize_name(f"{path}_{setting}")
                if name in os.environ:
                    config[setting] = yaml.safe_load(os.environ.get(normalize_name(name)))
    return config

def parse_config(requesting_file_path, is_plugin=True):
    """
    Parse the config files for a given sideboard plugin, or sideboard itself.

    It's expected that this function is called from one of the files in the
    top-level of your module (typically the __init__.py file)

    Args:
        requesting_file_path (str): The __file__ of the module requesting the
            parsed config file. An example value is::

                /opt/sideboard/plugins/plugin-package-name/plugin_module_name/__init__.py

            the containing directory (here, `plugin_module_name`) is assumed
            to be the module name of the plugin that is requesting a parsed
            config.
        is_plugin (bool): Indicates whether a plugin is making the request or
            Sideboard itself is making the request. If True (default) add
            plugin-relevant information to the returned config. Also, treat it
            as if it's a plugin

    Returns:
        ConfigObj: The resulting configuration object.
    """
    module_dir, root_dir, plugin_name = get_module_and_root_dirs(requesting_file_path, is_plugin)

    specfile = module_dir / 'configspec.ini'
    spec = configobj.ConfigObj(str(specfile), interpolation=False, list_values=False, encoding='utf-8', _inspec=True)

    # to allow more/better interpolations
    root_conf = ['root = "{}"\n'.format(root_dir), 'module_root = "{}"\n'.format(module_dir)]
    temp_config = configobj.ConfigObj(root_conf, interpolation=False, encoding='utf-8')

    for config_path in get_config_files(requesting_file_path, is_plugin):
        # this gracefully handles nonexistent files
        file_config = configobj.ConfigObj(str(config_path), encoding='utf-8', interpolation=False)
        if os.environ.get("LOG_CONFIG", "false").lower() == "true":
            print(f"File config for {plugin_name} from {config_path}")
            print(json.dumps(file_config, indent=2, sort_keys=True))
        temp_config.merge(file_config)

    environment_config = load_section_from_environment(plugin_name, spec)
    if os.environ.get("LOG_CONFIG", "false").lower() == "true":
        print(f"Environment config for {plugin_name}")
        print(json.dumps(environment_config, indent=2, sort_keys=True))
    temp_config.merge(configobj.ConfigObj(environment_config, encoding='utf-8', interpolation=False))

    # combining the merge files to one file helps configspecs with interpolation
    with NamedTemporaryFile(delete=False) as config_outfile:
        temp_config.write(config_outfile)
        temp_name = config_outfile.name

    config = configobj.ConfigObj(temp_name, encoding='utf-8', configspec=spec)

    validation = config.validate(Validator(), preserve_errors=True)
    unlink(temp_name)

    if validation is not True:
        raise RuntimeError('configuration validation error(s) (): {!r}'.format(
            configobj.flatten_errors(config, validation))
        )

    if is_plugin:
        sideboard_config = globals()['config']

        if 'default_url' in config:
            priority = config.get('default_url_priority', 0)
            if priority >= sideboard_config['default_url_priority']:
                sideboard_config['default_url'] = config['default_url']

    return config

config = parse_config(__file__, is_plugin=False)
