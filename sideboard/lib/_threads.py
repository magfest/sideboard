from __future__ import unicode_literals
import sys
import ctypes, ctypes.util
import psutil
import platform
import traceback
import threading

import six

from sideboard.lib import log, config, on_startup, on_shutdown, class_property
from sideboard.debugging import register_diagnostics_status_function

# Replaces the prior prctl implementation with a direct call to pthread to change thread names
libpthread_path = ctypes.util.find_library("pthread")
pthread_setname_np = None
if libpthread_path:
    libpthread = ctypes.CDLL(libpthread_path)
    if hasattr(libpthread, "pthread_setname_np"):
        pthread_setname_np = libpthread.pthread_setname_np
        pthread_setname_np.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        pthread_setname_np.restype = ctypes.c_int


def _set_current_thread_ids_from(thread):
    # thread ID part 1: set externally visible thread name in /proc/[pid]/tasks/[tid]/comm to our internal name
    if pthread_setname_np and thread.name:
        # linux doesn't allow thread names > 15 chars, and we ideally want to see the end of the name.
        # attempt to shorten the name if we need to.
        shorter_name = thread.name if len(thread.name) < 15 else thread.name.replace('CP Server Thread', 'CPServ')
        if thread.ident is not None:
            pthread_setname_np(thread.ident, shorter_name.encode('ASCII'))


# inject our own code at the start of every thread's start() method which sets the thread name via pthread().
# Python thread names will now be shown in external system tools like 'top', '/proc', etc.
def _thread_name_insert(self):
    _set_current_thread_ids_from(self)
    threading.Thread._bootstrap_inner_original(self)

if six.PY3:
    threading.Thread._bootstrap_inner_original = threading.Thread._bootstrap_inner
    threading.Thread._bootstrap_inner = _thread_name_insert
else:
    threading.Thread._bootstrap_inner_original = threading.Thread._Thread__bootstrap
    threading.Thread._Thread__bootstrap = _thread_name_insert

# set the ID's of the main thread
threading.current_thread().name = 'sideboard_main'
_set_current_thread_ids_from(threading.current_thread())


def _get_thread_current_stacktrace(thread_stack, thread):
    out = []
    status = '[unknown]'
    if psutil and thread.native_id != -1:
        status = psutil.Process(thread.native_id).status()
    out.append('\n--------------------------------------------------------------------------')
    out.append('# Thread name: "%s"\n# Python thread.ident: %d\n# Linux Thread PID (TID): %d\n# Run Status: %s'
                % (thread.name, thread.ident, thread.native_id, status))
    for filename, lineno, name, line in traceback.extract_stack(thread_stack):
        out.append('File: "%s", line %d, in %s' % (filename, lineno, name))
        if line:
            out.append('  %s' % (line.strip()))
    return out


@register_diagnostics_status_function
def threading_information():
    out = []
    threads_by_id = dict([(thread.ident, thread) for thread in threading.enumerate()])
    for thread_id, thread_stack in sys._current_frames().items():
        thread = threads_by_id.get(thread_id, '')
        out += _get_thread_current_stacktrace(thread_stack, thread)
    return '\n'.join(out)


def _to_megabytes(bytes):
    return str(int(bytes / 0x100000)) + 'MB'


@register_diagnostics_status_function
def general_system_info():
    """
    Print general system info
    TODO:
    - print memory nicer, convert mem to megabytes
    - disk partitions usage,
    - # of open file handles
    - # free inode count
    - # of cherrypy session files
    - # of cherrypy session locks (should be low)
    """
    out = []
    out += ['Mem: ' + repr(psutil.virtual_memory()) if psutil else '<unknown>']
    out += ['Swap: ' + repr(psutil.swap_memory()) if psutil else '<unknown>']
    return '\n'.join(out)

class threadlocal(object):
    """
    This class exposes a dict-like interface on top of the threading.local
    utility class; the "get", "set", "setdefault", and "clear" methods work the
    same as for a dict except that each thread gets its own keys and values.

    Sideboard clears out all existing values and then initializes some specific
    values in the following situations:

    1) CherryPy page handlers have the 'username' key set to whatever value is
        returned by cherrypy.session['username'].

    2) Service methods called via JSON-RPC have the following two fields set:
        -> username: as above
        -> websocket_client: if the JSON-RPC request has a "websocket_client"
            field, it's value is set here; this is used internally as the
            "originating_client" value in notify() and plugins can ignore this

    3) Service methods called via websocket have the following three fields set:
        -> username: as above
        -> websocket: the WebSocketDispatcher instance receiving the RPC call
        -> client_data: see the client_data property below for an explanation
        -> message: the RPC request body; this is present on the initial call
            but not on subscription triggers in the broadcast thread
    """
    _threadlocal = threading.local()

    @classmethod
    def get(cls, key, default=None):
        return getattr(cls._threadlocal, key, default)

    @classmethod
    def set(cls, key, val):
        return setattr(cls._threadlocal, key, val)

    @classmethod
    def setdefault(cls, key, val):
        val = cls.get(key, val)
        cls.set(key, val)
        return val

    @classmethod
    def clear(cls):
        cls._threadlocal.__dict__.clear()

    @classmethod
    def get_client(cls):
        """
        If called as part of an initial websocket RPC request, this returns the
        client id if one exists, and otherwise returns None.  Plugins probably
        shouldn't need to call this method themselves.
        """
        return cls.get('client') or cls.get('message', {}).get('client')

    @classmethod
    def reset(cls, **kwargs):
        """
        Plugins should never call this method directly without a good reason; it
        clears out all existing values and replaces them with the key-value
        pairs passed as keyword arguments to this function.
        """
        cls.clear()
        for key, val in kwargs.items():
            cls.set(key, val)

    @class_property
    def client_data(cls):
        """
        This propery is basically the websocket equivalent of cherrypy.session;
        it's a dictionary where your service methods can place data which you'd
        like to use in subsequent method calls.
        """
        return cls.setdefault('client_data', {})