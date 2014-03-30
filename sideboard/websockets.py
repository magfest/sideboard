from __future__ import unicode_literals
import sys
import json
import time
import hashlib
import logging
import traceback
from copy import deepcopy
from functools import wraps
from threading import local, RLock
from collections import defaultdict

import cherrypy

from ws4py.websocket import WebSocket
from ws4py.server.cherrypyserver import WebSocketPlugin, WebSocketTool

import sideboard.lib
from sideboard.lib import Caller
from sideboard.config import config


class threadlocal(object):
    _threadlocal = local()

    @classmethod
    def get(cls, key, default=None):
        return getattr(cls._threadlocal, key, default)

    @classmethod
    def set(cls, key, val):
        return setattr(cls._threadlocal, key, val)

    @classmethod
    def clear(cls):
        cls._threadlocal.__dict__.clear()

    @classmethod
    def get_client(cls):
        return cls.get("client") or cls.get("message", {}).get("client")

    @classmethod
    def reset(cls, **kwargs):
        cls.clear()
        for key, val in kwargs.items():
            cls.set(key, val)


def _normalize_topics(*topics):
    """
    Converts a list of types, strings, or whatever else into a list of strings.

    >>> _normalize_topics()
    []

    >>> _normalize_topics('')
    []

    >>> _normalize_topics('   ')
    []

    >>> _normalize_topics(None)
    []

    >>> _normalize_topics('topic-one', 'topic-two')
    ['topic-one', 'topic-two']

    >>> _normalize_topics('repeated-topic', 'repeated-topic')
    ['repeated-topic']

    >>> _normalize_topics('topic-left', None, 'topic-right', None)
    ['topic-left', 'topic-right']

    >>> _normalize_topics('', 'topic-left', '', 'topic-right')
    ['topic-left', 'topic-right']

    >>> _normalize_topics('   ', '   topic-padded-left', '   ', 'topic-padded-right   ', '   ')
    ['topic-padded-left', 'topic-padded-right']

    >>> _normalize_topics(type)
    ['type']

    >>> _normalize_topics(dict)
    ['dict']

    >>> _normalize_topics(dict(foo="bar"))
    ["{'foo': 'bar'}"]
    """
    normalized_topics = []
    for topic in topics:
        if topic is not None:
            if isinstance(topic, type):
                normalized_topics.append(topic.__name__)
            elif isinstance(topic, basestring):
                topic = topic.strip()
                if topic != '':
                    normalized_topics.append(topic)
            else:
                normalized_topics.append(str(topic))
    return list(set(normalized_topics))


def notify(topics, trigger="manual", delay=0, originating_client=None):
    broadcaster.delayed(delay, trigger, _normalize_topics(*sideboard.lib.listify(topics)),
                        originating_client or threadlocal.get_client())


def notifies(*args, **kwargs):
    """
    Adds a notifies attribute to the decorated function. The notifies
    attribute specifies a list of the topics which the function notifies.

    >>> @notifies('topic-one', 'topic-two')
    ... def fn():
    ...     pass
    >>> getattr(fn, 'notifies')
    ['topic-one', 'topic-two']

    >>> @notifies(dict)
    ... def fn_dict():
    ...     pass
    >>> getattr(fn_dict, 'notifies')
    ['dict']
    """
    delay = kwargs.pop("delay", 0)
    topics = _normalize_topics(*args)

    def decorated_func(func):
        @wraps(func)
        def notifier_func(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            finally:
                notify(topics, trigger=func.__name__, delay=delay)

        notifier_func.notifies = topics
        return notifier_func

    return decorated_func


def subscribes(*args):
    """
    Adds a subscribes attribute to the decorated function. The subscribes
    attribute specifies a list of the topics to which the function subscribes.

    >>> @subscribes('topic-one', 'topic-two')
    ... def fn():
    ...     pass
    >>> getattr(fn, 'subscribes')
    ['topic-one', 'topic-two']

    >>> @subscribes(dict)
    ... def fn_dict():
    ...     pass
    >>> getattr(fn_dict, 'subscribes')
    ['dict']
    """
    topics = _normalize_topics(*args)

    def decorated_func(func):
        func.subscribes = topics
        return func

    return decorated_func


def _fingerprint(x):
    """
    Calculates the md5 sum of the given argument.

    If _fingerprint is passed a string, it calculates the md5 sum of the
    string. If _fingerprint is passed anything else, then the json encoding
    of the argument is used to calculate the md5 sum.

    >>> _fingerprint(None)
    '37a6259cc0c1dae299a7866489dff0bd'

    >>> _fingerprint('test')
    '098f6bcd4621d373cade4e832627b4f6'

    >>> _fingerprint({'key':'value'})
    'a7353f7cddce808de0032747a0b7be50'

    >>> _fingerprint(dict(key='value'))
    'a7353f7cddce808de0032747a0b7be50'

    >>> _fingerprint({'a':1, 'b':2})
    '608de49a4600dbb5b173492759792e4a'

    >>> _fingerprint({'b':2, 'a':1})
    '608de49a4600dbb5b173492759792e4a'

    >>> _fingerprint({'a':{'x':3, 'y':4}, 'b':2})
    '2c22e445e9278c66dd7ea78b757defe6'

    >>> _fingerprint({'b':2, 'a':{'y':4, 'x':3}})
    '2c22e445e9278c66dd7ea78b757defe6'
    """
    md5 = hashlib.md5()
    if isinstance(x, basestring):
        md5.update(x)
    else:
        md5.update(json.dumps(x, cls=sideboard.lib.serializer, sort_keys=True, separators=(',', ':')))
    return md5.hexdigest()


def get_params(params):
    if params is None:
        return [], {}
    elif isinstance(params, dict):
        return [], params
    elif isinstance(params, (list, tuple)):
        return params, {}
    else:
        return [params], {}


class WebSocketDispatcher(WebSocket):
    ERROR = object()
    username = None
    subscriptions = defaultdict(lambda: defaultdict(lambda: defaultdict(set)))

    debug = True
    services = {}
    log = logging.getLogger(__name__)

    def __init__(self, *args, **kwargs):
        WebSocket.__init__(self, *args, **kwargs)
        self.send_lock = RLock()
        self.client_locks, self.cached_queries, self.cached_fingerprints = \
            defaultdict(RLock), defaultdict(dict), defaultdict(dict)
        self.username = self.check_authentication()

    @classmethod
    def check_authentication(cls):
        return cherrypy.session["username"]

    @classmethod
    def get_all_subscribed(cls):
        websockets = set()
        for model, subscriptions in cls.subscriptions.items():
            for websocket, clients in subscriptions.items():
                websockets.add(websocket)
        return websockets

    def send(self, **message):
        message = {k: v for k, v in message.items() if v is not None}
        if "data" in message and "client" in message:
            fingerprint = _fingerprint(message["data"])
            client, callback = message["client"], message.get("callback")
            repeat_send = callback in self.cached_fingerprints[client]
            cached_fingerprint = self.cached_fingerprints[client].get(callback)
            self.cached_fingerprints[client][callback] = fingerprint
            if cached_fingerprint == fingerprint and repeat_send:
                return

        self.log.debug("sending {}", message)
        message = json.dumps(message, cls=sideboard.lib.serializer, separators=(",", ":"), sort_keys=True)
        with self.send_lock:
            WebSocket.send(self, message)

    def closed(self, code, reason=""):
        self.log.info("closing: code={!r} reason={!r}", code, reason)
        self.unsubscribe_all()
        WebSocket.closed(self, code, reason)
        notify("Site")

    @classmethod
    def broadcast(cls, trigger, models, originating_client=None):
        triggered = set()
        for model in models:
            for websocket, clients in cls.subscriptions[model].items():
                for client, callbacks in clients.copy().items():
                    if client != originating_client:
                        for callback in callbacks:
                            triggered.add((websocket, client, callback))

        for websocket, client, callback in triggered:
            try:
                websocket.trigger(trigger, client, callback)
            except:
                cls.log.warn("ignoring unexpected trigger error", exc_info=True)

    def get_method(self, action):
        service, method = action.split(".")
        return service, getattr(self.services[service], method)

    def unsubscribe(self, client):
        self.client_locks.pop(client, None)
        self.cached_queries.pop(client, None)
        self.cached_fingerprints.pop(client, None)
        for clients in self.subscriptions.values():
            clients[self].pop(client, None)

    def unsubscribe_all(self):
        for clients in self.subscriptions.values():
            clients.pop(self, None)

    def update_subscriptions(self, client, callback, models):
        for clients in self.subscriptions.values():
            clients[self][client].discard(callback)

        for model in models:
            self.subscriptions[model][self][client].add(callback)

    def trigger(self, trigger, client, callback):
        if callback in self.cached_queries[client]:
            function, args, kwargs = self.cached_queries[client][callback]
            result = function(*args, **kwargs)
            self.send(trigger=trigger, client=client, callback=callback,
                      data=result)

    def update_triggers(self, client, callback, function, result,
                        delta_time=None, *args, **kwargs):
        if hasattr(function, "subscribes") and client is not None:
            self.cached_queries[client][callback] = (function, args, kwargs)
            self.update_subscriptions(client, callback, function.subscribes)
        if client is not None and callback is None and result is not self.ERROR:
            self.send(trigger="subscribe", client=client, data=result,
                      _time=delta_time)

    def internal_action(self, action, client, callback):
        if action == "unsubscribe":
            self.unsubscribe(client)
        elif action is not None:
            self.log.warn("unknown action {!r}", action)

    def received_message(self, message):
        responder.defer(self, deepcopy(message))

    def handle_message(self, message):
        self.log.debug("received {}", message.data)
        callback, client, delta_time, result = None, None, None, None
        try:
            message = json.loads(str(message.data))
            threadlocal.reset(websocket=self, message=message, username=self.username)
            action, callback, client, method = message.get("action"), message.get("callback"), message.get("client"), message.get("method")
            with self.client_locks[client] if client else RLock():
                self.internal_action(action, client, callback)
                if method:
                    service, function = self.get_method(method)
                    args, kwargs = get_params(message.get("params"))
                    result = self.ERROR
                    try:
                        before_time = time.time()
                        result = function(*args, **kwargs)
                        delta_time = (time.time() - before_time) if self.debug else None
                    finally:
                        self.update_triggers(client, callback, function, result, delta_time,
                                             *args, **kwargs)
        except:
            self.log.error("unexpected websocket dispatch error", exc_info=True)
            exc_class, exc, tb = sys.exc_info()
            str_content = str(exc) or 'Unexpected Error.'
            message = (str_content + '\n' + traceback.format_exc()) if self.debug else str_content
            self.send(error=message, callback=callback, client=client)
        else:
            if callback is not None:
                self.send(data=result, callback=callback, client=client, _time=delta_time)

    def __repr__(self):
        return '<%s username=%s>' % (self.__class__.__name__, self.username)


class WebSocketRoot(object):
    @cherrypy.expose
    def default(self):
        pass


class WebSocketChecker(WebSocketTool):
    def __init__(self):
        cherrypy.Tool.__init__(self, "before_handler", self.upgrade)

    def upgrade(self, **kwargs):
        try:
            kwargs["handler_cls"].check_authentication()
        except:
            raise cherrypy.HTTPError(401, "You must be logged in to establish a websocket connection.")
        else:
            return WebSocketTool.upgrade(self, **kwargs)

cherrypy.tools.websockets = WebSocketChecker()

websocket_plugin = WebSocketPlugin(cherrypy.engine)
websocket_plugin.subscribe()

broadcaster = Caller(WebSocketDispatcher.broadcast)
responder = Caller(WebSocketDispatcher.handle_message, threads=config['ws_thread_pool'])
