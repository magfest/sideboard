from __future__ import unicode_literals
import os
import re
import sys
import importlib
from glob import glob
from os.path import join
from threading import RLock

from sideboard.config import config
from sideboard.internal.autolog import log

_path_cache = {}
_module_cache = {}

VALID_PYTHON_FILENAME = '^[_A-Za-z][_a-zA-Z0-9]*$'

FORCE_PLUGIN_VERSIONS = {'sideboard.lib.sa', 'sqlalchemy'}


class SideboardImportError(ImportError):
    pass


class patch_path(object):
    def __init__(self, plugin, *paths):
        self.plugin = plugin
        self.paths = list(paths)

    def __enter__(self):
        self.old_path = sys.path
        sys.path = self.old_path[:1] + self.paths + self.old_path[1:]

    def __exit__(self, exc_type, exc_value, traceback):
        _path_cache[self.plugin] = [d for d in sys.path if d not in self.old_path]
        sys.path = self.old_path


class clear_module_cache(object):
    def __init__(self, plugin):
        self.plugin = plugin

    def __enter__(self):
        self.keys = list(sys.modules.keys())

    def __exit__(self, exc_type, exc_value, traceback):
        assert set(self.keys).issubset(sys.modules.keys())
        new_modules = set(sys.modules.keys()).difference(self.keys)
        _module_cache[self.plugin] = {modname: sys.modules[modname] for modname in new_modules}
        for module in new_modules:
            if not module.startswith(self.plugin):
                del sys.modules[module]


class set_aside(object):
    def __init__(self, prefixes=FORCE_PLUGIN_VERSIONS):
        self.prefixes = prefixes

    @staticmethod
    def snapshot(prefixes=FORCE_PLUGIN_VERSIONS):
        backups = {}
        for prefix in prefixes:
            for modname in sys.modules.keys():
                if modname.startswith(prefix):
                    backups[modname] = sys.modules.pop(modname)
        return backups

    @staticmethod
    def restore(modules):
        for modname, module in modules.items():
            sys.modules[modname] = module

    def __enter__(self):
        self.backups = self.snapshot(self.prefixes)

    def __exit__(self, exc_type, exc_value, traceback):
        self.restore(self.backups)


class use_plugin_virtualenv(object):
    """
    context-manager to support dispatching dynamic imports to the appropriate plugin virtualenv.
    The manager is in charge of temporarily overriding sys.path and sys.modules on entry and
    undoing the changes on exit.
    """
    lock = RLock()

    def __init__(self, plugin_name=None):
        """
        :param plugin_name: the name of the plugin whose virtualenv we should activate. If this
                            is 'sideboard' then this context manager will do nothing.  If this
                            parameter is omitted, then we attempt to get the current plugin name
                            from the call stack, and if the call stack does not involve a plugin
                            then this context manager does nothing.
        """
        self.plugin_name = plugin_name or get_current_plugin()

    def __enter__(self):
        """
        Temporarily setting sys.path and sys.modules to values that point to the appropriate plugin
        virtualenv ensures that dynamic imports don't try to import from sideboard's virtualenv which
        would either mean we don't find it, or worse find a different version of the module we
        import.

        If sys.path or sys.modules are modified outside of this context manager, those changes will
        be thrown away
        """
        if self.plugin_name not in ['sideboard', None]:
            self.lock.acquire()
            try:
                self._original_path = sys.path
                self._original_modules = sys.modules.copy()
                self.original_keys = set(self._original_modules.keys())

                #TODO: determine if there a sufficiently negative performance
                #      implication to rethink doing this in recursive imports
                sys.path = _path_cache[self.plugin_name] + sys.path

                # This really does need to be an update in place.
                # Setting sys.modules = SOME_NEW_DICTIONARY means
                # imports still write to the original sys.modules
                sys.modules.update(_module_cache[self.plugin_name])
            except:
                self.lock.release()
                raise

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        Put the original sys.path and sys.modules back to not mess up other imports
        """
        if self.plugin_name not in ['sideboard', None]:
            try:
                difference = set(sys.modules.keys()) - self.original_keys
                if difference:
                    # we apparently imported something new within the context and we should persist
                    # it to the module cache
                    _module_cache[self.plugin_name].update({k:sys.modules[k] for k in difference})

                # sanity check that original sys.modules was not overwritten underneath us
                assert self.original_keys == set(self._original_modules.keys()), \
                    'DETECTED CHANGE IN SAVED SYS.MODULES REFERENCE'

                sys.path = self._original_path

                for module_name in difference:
                    # much like in __enter__, we need to update in place
                    # TODO: determine if there's a danger for overwriting a module reference
                    #  in the main sys.modules with a plug-in's version of the same module?

                    # we explicitly want to error if the module name somehow isn't there
                    del sys.modules[module_name]
            finally:
                self.lock.release()

def get_plugin_path_extension(plugin_path):
    """
    Given a plugin path, return a list of directories to add to sys.path.
    """
    package_dirs = get_plugin_venv_package_directories(plugin_path)
    return [plugin_path] + package_dirs \
         + [join(package_dir, package) for package_dir in package_dirs
                                       for package in os.listdir(package_dir)
                                       if not package.endswith('.pth')]


def get_plugin_venv_package_directories(plugin_path):
    """
    Given a plugin path, return the list of package directories. On most
    platforms this will just be its site-packages directory, but on Ubuntu this
    will also include the dist-packages directory.
    """
    python = 'python{}.{}'.format(*sys.version_info)
    paths = [
        join(plugin_path, 'env', 'lib', python, 'site-packages'),
        join(plugin_path, 'env', 'local', 'lib', python, 'dist-packages')
    ]
    if not os.path.exists(paths[0]):
        raise SideboardImportError('plugin site-packages path "{}" does not exist'.format(paths[0]))
    return [p for p in paths if os.path.exists(p)]  


def filter_distribute_modules(module_names):
    distribute_modules = {
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
        }
    for module_name in module_names:
        if module_name not in distribute_modules:
            yield module_name


def get_modules_to_import_from_directory(dirpath):
    for dname, dirs, files in os.walk(dirpath):
        module = dname[len(os.path.dirname(dirpath)) + 1:].split(os.path.sep)
        for fname in files:
            if fname.endswith('.py'):
                if fname == '__init__.py':
                    modparts = module
                elif fname.startswith('__'):
                    continue  # e.g. pip has a __main__.py file
                else:
                    modparts = module + [fname[:-3]]
                yield '.'.join(modparts)


def get_modules(site_path):
    """
    Yield all modules to be imported (recursively), given a path to a
    site-packages directory. This includes:
        * source eggs
        * link eggs
        * regular python modules
    Compiled egg support isn't complete. For now it returns only the top-level
    module name.
    """
    for dirpath, dirnames, filenames in os.walk(site_path):
        module = dirpath[len(site_path) + 1:].split(os.path.sep)
        if module[0].endswith('.egg-info'):
            continue
        if module[0].endswith('.egg') or not module[0]:
            module.pop(0)

        for filename in filenames:
            root, ext = os.path.splitext(filename)
            if ext == '.py':
                if not re.match(VALID_PYTHON_FILENAME, root):
                    continue
                if root == '__init__':
                    yield '.'.join(module)
                else:
                    yield '.'.join(module + [root])
            elif ext == '.egg-link':
                with open(os.path.join(dirpath, filename)) as f:
                    egglink_path = f.readline().strip()
                linked_module_path = os.path.join(egglink_path, root.replace('-', '_'))
                for modname in get_modules_to_import_from_directory(linked_module_path):
                    yield modname
            elif ext == '.egg':
                yield filename.split('-', 1)[0]


def handle_exception(exception, plugin_name, module_name, log=log):
    error_msg = '{exception_name} caught while importing {module_name}'.format(
        exception_name=type(exception).__name__,
        module_name=module_name,
    )
    if module_name.startswith(plugin_name):
        log.warning('error importing plugin {}', plugin_name, exc_info=True)
        raise SideboardImportError(error_msg)
    else:
        if isinstance(exception, ImportError):
            import_error_msg = str(exception)
            imported_module = import_error_msg.rsplit(' ', 1)[-1]
            if imported_module == module_name:
                log.warning(error_msg)  # this shouldn't ever happen
            else:
                log.debug(error_msg)
        else:
            log.debug(error_msg)


def ensure_plugin_module_loaded(plugin_name):
    if plugin_name not in sys.modules:
        raise SideboardImportError(('plugin module {} not loaded; '
            'did you forget to run `setup.py develop`?').format(plugin_name))


def _discover_plugins():
    plugin_paths = glob(join(config['plugins_dir'], '*'))
    for plugin_path in plugin_paths:
        if os.path.isdir(plugin_path) and not os.path.split(plugin_path)[-1].startswith('_'):
            extra_path = get_plugin_path_extension(plugin_path)
            plugin_name = os.path.basename(plugin_path).replace('-', '_')
            with set_aside(), patch_path(plugin_name, *extra_path), clear_module_cache(plugin_name):
                for package_dir in get_plugin_venv_package_directories(plugin_path):
                    for module_name in filter_distribute_modules(get_modules(package_dir)):
                        if module_name.startswith(plugin_name):
                            try:
                                importlib.import_module(module_name)
                            except Exception as e:
                                handle_exception(e, plugin_name, module_name)
            ensure_plugin_module_loaded(plugin_name)


def _yield_frames():
    """
    :return: Generator to support pythonically iterating of the call stack from top to bottom
    """
    depth = 0
    while True:
        try:
            yield sys._getframe(depth)
        except ValueError:
            raise StopIteration
        else:
            depth += 1


def _yield_module_names_and_filenames_from_callstack():
    for frame in _yield_frames():
        try:
            module_name = frame.f_globals.get('__name__', '')
            filename = frame.f_globals.get('__file__', '')
        except:
            log.debug('unable to get module name or filename from frame: {0.f_code.co_filename}',
                      frame)
        else:
            yield module_name, filename


def get_current_plugin():
    """
    Determine whether or not the import was called from a plugin or third-party module
    in a plugin. If it did, return the plugin name.

    since this method uses sys._getframes under the hood, we are limited to CPython

    :return: plugin name as a unicode object or None if the import was not from a plugin
    """
    for module_name, filename in _yield_module_names_and_filenames_from_callstack():
        potential_plugin_name = module_name.split('.')[0]
        if _is_plugin_name(potential_plugin_name):
            return potential_plugin_name

        potential_plugin_name = _venv_plugin_name(filename)
        if _is_plugin_name(potential_plugin_name):
            return potential_plugin_name


def _is_plugin_name(name):
    """
    Is the string provided here a name of a sideboard plugin?

    :param name: potential name of a plugin as a str
    :return: True if the provided name matches up to a plugin name that we've discovered,
        else False
    """
    return name in _path_cache and name in _module_cache


def _venv_plugin_name(file):
    """
    Returns the name of the plugin whose virtualenv this filename exists in, or None.
    
    :param file: the __file__ of a module
    """
    abspath = os.path.realpath(os.path.abspath(file))
    for plugin_name, paths in _path_cache.items():
        try:
            [spdir] = [p for p in paths if p.rstrip('/').endswith('site-packages')]
        except ValueError:
            # there's a plugin without a site-packages; this is most likely because of a
            # unittest/mocking situation
            continue
        else:
            if abspath.startswith(spdir):
                return plugin_name
