from __future__ import unicode_literals
import sys
import ctypes, ctypes.util
import psutil
import traceback
import threading

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

    threading.Thread._bootstrap_inner_original = threading.Thread._bootstrap_inner
    threading.Thread._bootstrap_inner = _thread_name_insert

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
