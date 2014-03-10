import heapq
from warnings import warn
from Queue import Queue, Empty
from threading import Thread, Timer, Event, RLock

time = __import__("time")
logging = __import__("logging")

log = logging.getLogger(__name__)


class DaemonTask(object):
    def __init__(self, func, interval = 0.1, threads = 1, stopped=None):
        self.threads = []
        self.stopped = stopped or Event()
        self.func, self.interval, self.thread_count = func, interval, threads
    
    @property
    def running(self):
        return any(t.is_alive() for t in self.threads)
    
    def run(self):
        while not self.stopped.is_set():
            try:
                self.func()
            except:
                log.error("unexpected error", exc_info=True)
            
            if self.interval:
                self.stopped.wait(self.interval)
    
    def start(self):
        self.stopped.clear()
        self.threads[:] = []
        for i in range(self.thread_count):
            t = Thread(target = self.run)
            t.name = "%s-%s" % (self.func.__name__, i + 1)
            t.daemon = True
            t.start()
            self.threads.append(t)
    
    def stop(self):
        self.stopped.set()
        for i in range(50):
            self.threads[:] = [t for t in self.threads if t.is_alive()]
            if self.threads:
                time.sleep(0.1)
            else:
                break
        else:
            log.warning("not all daemons have been joined: %s", self.threads)


class TimeDelayQueue(Queue):
    def __init__(self, maxsize=0, stopped=None):
        self.delayed = []
        Queue.__init__(self, maxsize)
        self.task = DaemonTask(self._put_and_notify, stopped = stopped)
    
    def start(self):
        self.task.start()
    
    def put(self, item, block=True, timeout=None, delay=0):
        Queue.put(self, (delay, item), block, timeout)
    
    def _put(self, item):
        delay, item = item
        if delay:
            if self.task.running:
                heapq.heappush(self.delayed, (time.time() + delay, item))
            else:
                warn("TimeDelayQueue.put called with a delay parameter without background task having been started")
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
    def __init__(self, func, interval = 0, threads = 1, stopped = None):
        DaemonTask.__init__(self, self.call, interval, threads, stopped)
        self.callee = func
        self.q = TimeDelayQueue(stopped = self.stopped)
    
    def call(self):
        try:
            args, kwargs = self.q.get(timeout = 0.1)
            self.callee(*args, **kwargs)
        except Empty:
            pass
    
    def start(self):
        self.q.start()
        DaemonTask.start(self)
    
    def defer(self, *args, **kwargs):
        self.q.put([args, kwargs])
    
    def delayed(self, delay, *args, **kwargs):
        self.q.put([args, kwargs], delay=delay)


class GenericCaller(DaemonTask):
    def __init__(self, interval = 0, threads = 1, stopped = None):
        DaemonTask.__init__(self, self.call, interval, threads, stopped)
        self.q = TimeDelayQueue(stopped = self.stopped)
    
    def call(self):
        try:
            func, args, kwargs = self.q.get(timeout = 0.1)
            func(*args, **kwargs)
        except Empty:
            pass
    
    def start(self):
        self.q.start()
        DaemonTask.start(self)
    
    def defer(self, func, *args, **kwargs):
        self.q.put([func, args, kwargs])
    
    def delayed(self, delay, func, *args, **kwargs):
        self.q.put([func, args, kwargs], delay=delay)
