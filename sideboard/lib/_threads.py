from __future__ import unicode_literals
import time
import heapq
from warnings import warn
from Queue import Queue, Empty
from threading import Thread, Timer, Event, Lock

from sideboard.lib import log, on_startup, on_shutdown


class DaemonTask(object):
    def __init__(self, func, interval=0.1, threads=1):
        self.lock = Lock()
        self.threads = []
        self.stopped = Event()
        self.func, self.interval, self.thread_count = func, interval, threads
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

            if self.interval:
                self.stopped.wait(self.interval)

    def start(self):
        with self.lock:
            if not self.running:
                self.stopped.clear()
                del self.threads[:]
                for i in range(self.thread_count):
                    t = Thread(target = self.run)
                    t.name = '{}-{}'.format(self.func.__name__, i + 1)
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
                    log.warning('not all daemons have been joined: {}', self.threads)
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
    def __init__(self, func, interval=0, threads=1):
        self.q = TimeDelayQueue()
        DaemonTask.__init__(self, self.call, interval=interval, threads=threads)
        self.callee = func

    def call(self):
        try:
            args, kwargs = self.q.get(timeout = 0.1)
            self.callee(*args, **kwargs)
        except Empty:
            pass

    def start(self):
        self.q.task.start()
        DaemonTask.start(self)

    def stop(self):
        self.q.task.stop()
        DaemonTask.stop(self)

    def defer(self, *args, **kwargs):
        self.q.put([args, kwargs])

    def delayed(self, delay, *args, **kwargs):
        self.q.put([args, kwargs], delay=delay)


class GenericCaller(DaemonTask):
    def __init__(self, interval=0, threads=1):
        DaemonTask.__init__(self, self.call, interval=interval, threads=threads)
        self.q = TimeDelayQueue()

    def call(self):
        try:
            func, args, kwargs = self.q.get(timeout = 0.1)
            func(*args, **kwargs)
        except Empty:
            pass

    def start(self):
        self.q.task.start()
        DaemonTask.start(self)

    def stop(self):
        self.q.task.stop()
        DaemonTask.stop(self)

    def defer(self, func, *args, **kwargs):
        self.q.put([func, args, kwargs])

    def delayed(self, delay, func, *args, **kwargs):
        self.q.put([func, args, kwargs], delay=delay)
