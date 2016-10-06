from __future__ import unicode_literals
import os

# create a list of status functions which can inspect information of the running process
status_functions = []


def gather_diagnostics_status_information():
    """
    Return textual information about current system state / diagnostics
    Useful for debugging threading / db / cpu load / etc
    """
    out = ''
    for func in status_functions:
        out += '--------- {} ---------\n{}\n\n\n'.format(func.__name__.replace('_', ' ').upper(), func())
    return out


def register_diagnostics_status_function(func):
    status_functions.append(func)
    return func


def _get_all_session_lock_filenames():
    path_of_this_python_script = os.path.dirname(os.path.realpath(__file__))
    session_path = path_of_this_python_script + "/../data/sessions/"
    return [session_path + lockfile for lockfile in os.listdir(session_path) if lockfile.endswith(".lock")]


def _debugger_helper_remove_any_session_lockfiles():
    """
    When debugging, if you force kill the server, occasionally
    there will be cherrypy session lockfiles leftover.
    Calling this function will remove any stray lockfiles.

    DO NOT CALL THIS IN PRODUCTION.
    """
    for lockfile in _get_all_session_lock_filenames():
        os.remove(lockfile)


def debugger_helpers_all_init():
    """
    Prepare sideboard to launch from a debugger.
    This will do a few extra steps to make sure the environment is friendly.

    DO NOT CALL THIS IN PRODUCTION.
    """
    _debugger_helper_remove_any_session_lockfiles()
