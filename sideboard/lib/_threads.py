from __future__ import unicode_literals
import sys
import time
import heapq
import ctypes, ctypes.util
import psutil
import platform
import traceback
import threading
from warnings import warn
from threading import Thread, Timer, Event, Lock

import six
from six.moves.queue import Queue, Empty

from sideboard.lib import log, config, on_startup, on_shutdown
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


def _get_linux_thread_tid():
    """
    Get the current linux thread ID as it appears in /proc/[pid]/task/[tid]
    :return: Linux thread ID if available, or -1 if any errors / not on linux
    """
    try:
        if not platform.system().startswith('Linux'):
            raise ValueError('Can only get thread id on Linux systems')
        syscalls = {
          'i386':   224,   # unistd_32.h: #define __NR_gettid 224
          'x86_64': 186,   # unistd_64.h: #define __NR_gettid 186
        }
        syscall_num = syscalls[platform.machine()]
        tid = ctypes.CDLL('libc.so.6').syscall(syscall_num)
    except:
        tid = -1
    return tid


def _set_current_thread_ids_from(thread):
    # thread ID part 1: set externally visible thread name in /proc/[pid]/tasks/[tid]/comm to our internal name
    if pthread_setname_np and thread.name:
        # linux doesn't allow thread names > 15 chars, and we ideally want to see the end of the name.
        # attempt to shorten the name if we need to.
        shorter_name = thread.name if len(thread.name) < 15 else thread.name.replace('CP Server Thread', 'CPServ')
        if thread.ident is not None:
            pthread_setname_np(thread.ident, shorter_name)


    # thread ID part 2: capture linux-specific thread ID (TID) and store it with this thread object
    # if TID can't be obtained or system call fails, tid will be -1
    thread.linux_tid = _get_linux_thread_tid()


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


class DaemonTask(object):
    def __init__(self, func, interval=None, threads=1, name=None):
        self.lock = Lock()
        self.threads = []
        self.stopped = Event()
        self.func, self.interval, self.thread_count = func, interval, threads
        self.name = name or self.func.__name__

        on_startup(self.start)
        on_shutdown(self.stop)

    @property
    def running(self):
        return any(t.is_alive() for t in self.threads)

    def run(self):
        while not self.stopped.is_set():
            try:
                self.func()
            except:
                log.error('unexpected error', exc_info=True)

            interval = config['thread_wait_interval'] if self.interval is None else self.interval
            if interval:
                self.stopped.wait(interval)

    def start(self):
        with self.lock:
            if not self.running:
                self.stopped.clear()
                del self.threads[:]
                for i in range(self.thread_count):
                    t = Thread(target=self.run)
                    t.name = '{}-{}'.format(self.name, i + 1)
                    t.daemon = True
                    t.start()
                    self.threads.append(t)

    def stop(self):
        with self.lock:
            if self.running:
                self.stopped.set()
                for i in range(50):
                    self.threads[:] = [t for t in self.threads if t.is_alive()]
                    if self.threads:
                        time.sleep(0.1)
                    else:
                        break
                else:
                    log.warning('not all daemons have been joined: %s', self.threads)
                    del self.threads[:]


class TimeDelayQueue(Queue):
    def __init__(self, maxsize=0):
        self.delayed = []
        Queue.__init__(self, maxsize)
        self.task = DaemonTask(self._put_and_notify)

    def put(self, item, block=True, timeout=None, delay=0):
        Queue.put(self, (delay, item), block, timeout)

    def _put(self, item):
        delay, item = item
        if delay:
            if self.task.running:
                heapq.heappush(self.delayed, (time.time() + delay, item))
            else:
                message = 'TimeDelayQueue.put called with a delay parameter without background task having been started'
                log.warning(message)
                warn(message)
        else:
            Queue._put(self, item)

    def _put_and_notify(self):
        with self.not_empty:
            while self.delayed:
                when, item = heapq.heappop(self.delayed)
                if when <= time.time():
                    Queue._put(self, item)
                    self.not_empty.notify()
                else:
                    heapq.heappush(self.delayed, (when, item))
                    break


class Caller(DaemonTask):
    def __init__(self, func, interval=0, threads=1, name=None):
        self.q = Queue()
        DaemonTask.__init__(self, self.call, interval=interval, threads=threads, name=name or func.__name__)
        self.callee = func

    def call(self):
        try:
            args, kwargs = self.q.get(timeout=config['thread_wait_interval'])
            self.callee(*args, **kwargs)
        except Empty:
            pass

    def defer(self, *args, **kwargs):
        self.q.put([args, kwargs])


class GenericCaller(DaemonTask):
    def __init__(self, interval=0, threads=1, name=None):
        DaemonTask.__init__(self, self.call, interval=interval, threads=threads, name=name)
        self.q = Queue()

    def call(self):
        try:
            func, args, kwargs = self.q.get(timeout=config['thread_wait_interval'])
            func(*args, **kwargs)
        except Empty:
            pass

    def defer(self, func, *args, **kwargs):
        self.q.put([func, args, kwargs])


def _get_thread_current_stacktrace(thread_stack, thread):
    out = []
    linux_tid = getattr(thread, 'linux_tid', -1)
    status = '[unknown]'
    if psutil and linux_tid != -1:
        status = psutil.Process(linux_tid).status()
    out.append('\n--------------------------------------------------------------------------')
    out.append('# Thread name: "%s"\n# Python thread.ident: %d\n# Linux Thread PID (TID): %d\n# Run Status: %s'
                % (thread.name, thread.ident, linux_tid, status))
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
