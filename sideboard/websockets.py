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

import six
import cherrypy

from ws4py.websocket import WebSocket
from ws4py.server.cherrypyserver import WebSocketPlugin, WebSocketTool

import sideboard.lib
from sideboard.lib import log, class_property, Caller
from sideboard.config import config

local_subscriptions = defaultdict(list)


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
    _threadlocal = local()

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


def _normalize_channels(*channels):
    """
    Converts a list of types, strings, or whatever else into a list of strings.

    >>> _normalize_channels()
    []

    >>> _normalize_channels('')
    []

    >>> _normalize_channels('   ')
    []

    >>> _normalize_channels(None)
    []

    >>> _normalize_channels('topic-one', 'topic-two')
    ['topic-one', 'topic-two']

    >>> _normalize_channels('repeated-topic', 'repeated-topic')
    ['repeated-topic']

    >>> _normalize_channels('topic-left', None, 'topic-right', None)
    ['topic-left', 'topic-right']

    >>> _normalize_channels('', 'topic-left', '', 'topic-right')
    ['topic-left', 'topic-right']

    >>> _normalize_channels('   ', '   topic-padded-left', '   ', 'topic-padded-right   ', '   ')
    ['topic-padded-left', 'topic-padded-right']

    >>> _normalize_channels(type)
    ['type']

    >>> _normalize_channels(dict)
    ['dict']

    >>> _normalize_channels(dict(foo="bar"))
    ["{'foo': 'bar'}"]
    """
    normalized_channels = []
    for topic in channels:
        if topic is not None:
            if isinstance(topic, type):
                normalized_channels.append(topic.__name__)
            elif isinstance(topic, six.string_types):
                topic = topic.strip()
                if topic != '':
                    normalized_channels.append(topic)
            else:
                normalized_channels.append(str(topic))
    return list(set(normalized_channels))


def notify(channels, trigger="manual", delay=0, originating_client=None):
    """
    Manually trigger all subscriptions on the given channels.  The following
    optional parameters may be specified:

    trigger: Used in log messages if you want to distinguish between triggers.
    delay: If provided, wait this many seconds before triggering the broadcast.
    originating_client: Websocket subscriptions will NOT fire if they have the
                        same client as the trigger.
    """
    channels = _normalize_channels(*sideboard.lib.listify(channels))
    context = {
        'trigger': trigger,
        'originating_client': originating_client or threadlocal.get_client()
    }
    broadcaster.delayed(delay, channels, **context)
    local_broadcaster.delayed(delay, channels, **context)


def notifies(*args, **kwargs):
    """
    Adds a notifies attribute to the decorated function. The notifies
    attribute specifies a list of the channels which the function notifies.

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
    channels = _normalize_channels(*args)

    def decorated_func(func):
        @wraps(func)
        def notifier_func(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            finally:
                notify(channels, trigger=func.__name__, delay=delay)

        notifier_func.notifies = channels
        return notifier_func

    return decorated_func


def subscribes(*args):
    """
    Adds a subscribes attribute to the decorated function. The subscribes
    attribute specifies a list of the channels to which the function subscribes.

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
    channels = _normalize_channels(*args)

    def decorated_func(func):
        func.subscribes = channels
        return func

    return decorated_func


def locally_subscribes(*args):
    """
    The @subscribes decorator registers a function as being one which clients
    may subscribe to via websocket.  This decorator may be used to register a
    function which shall be called locally anytime a notify occurs, e.g.

    @locally_subscribes('example.channel')
    def f():
        print('f was called')

    notify('example.channel')  # causes f() to be called in a separate thread
    """
    def decorated_func(func):
        for channel in _normalize_channels(*args):
            local_subscriptions[channel].append(func)
        return func

    return decorated_func


def local_broadcast(channels, trigger=None, originating_client=None):
    """Triggers callbacks registered via @locally_subscribes"""
    triggered = set()
    for channel in sideboard.lib.listify(channels):
        for callback in local_subscriptions[channel]:
            triggered.add(callback)

    for callback in triggered:
        threadlocal.reset(trigger=trigger, originating_client=originating_client)
        try:
            callback()
        except:
            log.error('unexpected error on local broadcast callback', exc_info=True)


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
    if not isinstance(x, six.string_types):
        x = json.dumps(x, cls=sideboard.lib.serializer, sort_keys=True, separators=(',', ':'))
    md5.update(x.encode('utf-8') if six.PY3 else x)
    return md5.hexdigest()


def get_params(params):
    if params is None:
        return [], {}
    elif isinstance(params, dict):
        return [], params
    elif isinstance(params, list):
        return params, {}
    else:
        return [params], {}


class WebSocketDispatcher(WebSocket):
    """
    This class is instantiated for each incoming websocket connection.  Each
    instance of this class has its own socket object and its own thread.  This
    class is where we respond to RPC requests.
    """

    username = None
    """
    See __init__ for documentation on this field.  It also exists as a class
    variable so that instances which do not set it have a default value.
    """

    NO_RESPONSE = object()
    """
    This object is used as a sentinel value for situations where we want to
    avoid double-sending a response.  For example, when an RPC request for a
    subscription arrives, we "trigger" a subscription response immediately, so
    there's no need to actually call "send" on the return value.

    This is an internal implementation detail and plugins shouldn't need to know
    or care that this field exists.
    """

    subscriptions = defaultdict(lambda: defaultdict(lambda: defaultdict(set)))
    """
    This tracks all subscriptions for all incoming websocket connections.  The
    structure looks like this:

        {
            'channel_id': {
                <WebSocketDispatcher-instance>: {
                    'client_id': {'callback_id_one', 'callback_id_two', ...},
                },
                ...
            },
            ...
        }

    This allows us to do things like trigger a broadcast to all websockets
    subscribed on a channel.  Instances of this class are responsible for
    adding and removing their subscriptions from this data structure.
    """

    def __init__(self, *args, **kwargs):
        """
        This passes all arguments to the parent constructor.  In addition, it
        defines the following instance variables:

        send_lock: Used to guarantee thread-safety when sending RPC responses.

        client_locks: A dict mapping client ids to locks used by those clients.

        passthru_subscriptions: When we recieve a subscription request for a
            service method registered on a remote service, we pass that request
            along to the remote service and send back the responses.  This
            dictionary maps client ids to those subscription objects.

        username: The username of the currently-authenticated user who made the
            incoming websocket connection.  Remember that Sideboard exposes two
            websocket handlers at /ws and /wsrpc, with /ws being auth-protected
            (so the username field will be meaningful) and /wsrpc being client-
            cert protected (so the username will always be 'rpc').

        cached_queries and cached_fingerprints: When we receive a subscription
            update, Sideboard re-runs all of the subscription methods to see if
            new data needs to be pushed out.  We do this by storing all of the
            rpc methods and an MD5 hash of their return values.  We store a hash
            rather than the return values themselves to save on memory, since
            return values may be very large.

            The cached_queries dict has this structure:
                {
                    'client_id': {
                        'callback_id': (func, args, kwargs, client_data),
                        ...
                    },
                    ...
                }

            The cached_fingerprints dict has this structure:
                {
                    'client_id': {
                        'callback_id': 'md5_hash_of_return_value',
                        ...
                    },
                    ...
                }
        """
        WebSocket.__init__(self, *args, **kwargs)
        self.send_lock = RLock()
        self.passthru_subscriptions = {}
        self.client_locks = defaultdict(RLock)
        self.cached_queries, self.cached_fingerprints = defaultdict(dict), defaultdict(dict)
        self.username = self.check_authentication()

    @classmethod
    def check_authentication(cls):
        """
        This method raises an exception if the user is not currently logged in,
        and otherwise returns the username of the currently-logged-in user.
        Subclasses can override this method to change the authentication method.
        """
        return cherrypy.session['username']

    @classmethod
    def get_all_subscribed(cls):
        """Returns a set of all instances of this class with active subscriptions."""
        websockets = set()
        for channel, subscriptions in cls.subscriptions.items():
            for websocket, clients in subscriptions.items():
                websockets.add(websocket)
        return websockets

    @classmethod
    def broadcast(cls, channels, trigger=None, originating_client=None):
        """
        Trigger all subscriptions on the given channel(s).  This method is
        called in the "broadcaster" thread, which means that all subscription
        updates happen in the same thread.

        Callers can pass an "originating_client" id, which will prevent data
        from being pushed to those clients.  This is useful in cases like this:
        -> a Javascipt application makes a call like "ecard.delete"
        -> not wanting to wait for a subscription update, the Javascript app
           preemptively updates its local data store to remove the item
        -> the response to the delete call comes back as a success
        -> because the local data store was already updated, there's no need
           for this client to get a subscription update

        Callers can pass a "trigger" field, which will be included in the
        subscription update message as the reason for the update.  This doesn't
        affect anything, but might be useful for logging.
        """
        triggered = set()
        for channel in sideboard.lib.listify(channels):
            for websocket, clients in cls.subscriptions[channel].items():
                for client, callbacks in clients.copy().items():
                    if client != originating_client:
                        for callback in callbacks:
                            triggered.add((websocket, client, callback))

        for websocket, client, callback in triggered:
            try:
                websocket.trigger(client=client, callback=callback, trigger=trigger)
            except:
                log.warn('ignoring unexpected trigger error', exc_info=True)

    @property
    def is_closed(self):
        """
        The "terminated" attribute tells us whether the socket was explictly
        closed, this property performs a more rigorous check to let us know
        if any of the fields which indicate the socket has been closed have been
        set; this allows us to avoid spurious error messages by not attempting
        to send messages on a socket which is in the process of closing.
        """
        return not self.stream or self.client_terminated or self.server_terminated or not self.sock

    def client_lock(self, client):
        """
        Sideboard has a pool of background threads which simultaneously executes
        method calls, but it performs per-subscription locking to ensure thread
        safety for our subscription-related data structures.  Thus, if the same
        connected websocket sends two method calls with the same client id,
        those calls will be handled sequentially rather than concurrently.

        This utility method supports this by returning a context manager which
        acquires the necessary locks on entrance and releases them on exit.  It
        takes either a client id or list of client ids.
        """
        ordered_clients = sorted(sideboard.lib.listify(client or []))
        ordered_locks = [self.client_locks[oc] for oc in ordered_clients]

        class MultiLock(object):
            def __enter__(inner_self):
                for lock in ordered_locks:
                    lock.acquire()

            def __exit__(inner_self, *args, **kwargs):
                for lock in reversed(ordered_locks):
                    lock.release()

        return MultiLock()

    def send(self, **message):
        """
        This overrides the ws4py-provided send to implement three new features:

        1) Instead of taking a string, this method treats its keyword arguments
           as the message, serializes them to JSON, and sends that.

        2) For subscription responses, we keep track of the most recent response
           we sent for the given subscription.  If neither the request or
           response have changed since the last time we pushed data back to the
           client for this subscription, we don't send anything.

        3) We lock when sending to ensure that our sends are thread-safe.
           Surprisingly, the "ws4py.threadedclient" class isn't thread-safe!

        4) Subscriptions firing will sometimes trigger a send on a websocket
           which has already been marked as closed.  When this happens we log a
           debug message and then exit without error.
        """
        if self.is_closed:
            log.debug('ignoring send on an already closed websocket: {}', message)
            return

        message = {k: v for k, v in message.items() if v is not None}
        if 'data' in message and 'client' in message:
            fingerprint = _fingerprint(message['data'])
            client, callback = message['client'], message.get('callback')
            repeat_send = callback in self.cached_fingerprints[client]
            cached_fingerprint = self.cached_fingerprints[client].get(callback)
            self.cached_fingerprints[client][callback] = fingerprint
            if cached_fingerprint == fingerprint and repeat_send:
                return

        log.debug('sending {}', message)
        message = json.dumps(message, cls=sideboard.lib.serializer,
                                      separators=(',', ':'), sort_keys=True)
        with self.send_lock:
            if not self.is_closed:
                WebSocket.send(self, message)

    def closed(self, code, reason=''):
        """
        This overrides the default closed handler to first clean up all of our
        subscriptions and log a message before closing.
        """
        log.info('closing: code={!r} reason={!r}', code, reason)
        self.unsubscribe_all()
        WebSocket.closed(self, code, reason)

    def teardown_passthru(self, client):
        """
        Given a client id, check whether there's a "passthrough subscription"
        for that client and clean it up if one exists.
        """
        subscription = self.passthru_subscriptions.pop(client, None)
        if subscription:
            subscription.unsubscribe()

    def get_method(self, action):
        """
        Given a method string in the format "module_name.function_name",
        return a callable object representing that function, raising an
        exception if the format is invalid or no such method exists.
        """
        service_name, method_name = action.split('.')
        service = getattr(sideboard.lib.services, service_name)
        method = getattr(service, method_name)
        return method

    def unsubscribe(self, clients):
        """
        Given a client id or list of client ids, clean up those subscriptions
        from the internal data structures of this class.
        """
        for client in sideboard.lib.listify(clients or []):
            self.teardown_passthru(client)
            self.client_locks.pop(client, None)
            self.cached_queries.pop(client, None)
            self.cached_fingerprints.pop(client, None)
            for clients in self.subscriptions.values():
                clients[self].pop(client, None)

    def unsubscribe_all(self):
        """Called on close to tear down all of this websocket's subscriptions."""
        for clients in self.subscriptions.values():
            for client in clients.pop(self, {}):
                self.teardown_passthru(client)

    def update_subscriptions(self, client, callback, channels):
        """Updates WebSocketDispatcher.subscriptions for the given client/channels."""
        for clients in self.subscriptions.values():
            clients[self][client].discard(callback)

        for channel in sideboard.lib.listify(channels):
            self.subscriptions[channel][self][client].add(callback)

    def trigger(self, client, callback, trigger=None):
        """
        This is the method called by the global broadcaster thread when a
        notification is posted to a channel this client is subscribed to.  It
        re-calls the function and sends the result back to the client.
        """
        if callback in self.cached_queries[client]:
            function, args, kwargs, client_data = self.cached_queries[client][callback]
            threadlocal.reset(websocket=self, username=self.username, client_data=client_data)
            result = function(*args, **kwargs)
            self.send(trigger=trigger, client=client, callback=callback, data=result)

    def update_triggers(self, client, callback, function, args, kwargs, result, duration=None):
        """
        This is called after an RPC function is invoked; it takes the function
        and its return value and updates our internal data structures then sends
        the response back to the client.
        """
        if hasattr(function, 'subscribes') and client is not None:
            self.cached_queries[client][callback] = (function, args, kwargs, threadlocal.client_data)
            self.update_subscriptions(client, callback, function.subscribes)
        if client is not None and callback is None and result is not self.NO_RESPONSE:
            self.send(trigger='subscribe', client=client, data=result, _time=duration)

    def internal_action(self, action, client, callback):
        """
        Sideboard currently supports both method calls and "internal actions"
        which affect the state of the websocket connection itself.  This
        implements the command-dispatch pattern to perform the given action and
        raises an exception if that action doesn't exist.

        The only action currently implemented is "unsubscribe".
        """
        if action == 'unsubscribe':
            self.unsubscribe(client)
        elif action is not None:
            log.warn('unknown action {!r}', action)

    def received_message(self, message):
        """
        This overrides the default ws4py event handler to parse the incoming
        message and pass it off to our pool of background threads, which call
        this class' handle_message function to perform the relevant RPC actions.
        """
        try:
            data = message.data if isinstance(message.data, six.text_type) else message.data.decode('utf-8')
            fields = json.loads(data)
            assert isinstance(fields, dict)
        except:
            message = 'incoming websocket message was not a json object: {}'.format(message.data)
            log.error(message)
            self.send(error=message)
        else:
            log.debug('received {}', fields)
            responder.defer(self, fields)

    def handle_message(self, message):
        """
        Given a message dictionary, perform the relevant RPC actions and send
        out the response.  This function is called from a pool of background
        threads
        """
        before = time.time()
        duration, result = None, None
        threadlocal.reset(websocket=self, message=message, username=self.username)
        action, callback, client, method = message.get('action'), message.get('callback'), message.get('client'), message.get('method')
        try:
            with self.client_lock(client):
                self.internal_action(action, client, callback)
                if method:
                    func = self.get_method(method)
                    args, kwargs = get_params(message.get('params'))
                    result = self.NO_RESPONSE
                    try:
                        result = func(*args, **kwargs)
                        duration = (time.time() - before) if config['debug'] else None
                    finally:
                        self.update_triggers(client, callback, func, args, kwargs, result, duration)
        except:
            log.error('unexpected websocket dispatch error', exc_info=True)
            exc_class, exc, tb = sys.exc_info()
            str_content = str(exc) or 'Unexpected Error.'
            message = (str_content + '\n' + traceback.format_exc()) if config['debug'] else str_content
            self.send(error=message, callback=callback, client=client)
        else:
            if callback is not None and result is not self.NO_RESPONSE:
                self.send(data=result, callback=callback, client=client, _time=duration)

    def __repr__(self):
        return '<%s username=%s>' % (self.__class__.__name__, self.username)


class WebSocketAuthError(Exception):
    """
    Exception raised by WebSocketDispatcher subclasses to indicate that there is
    not a currently-logged-in user able to make a websocket connection.
    """


class WebSocketRoot(object):
    @cherrypy.expose
    def default(self):
        pass


class WebSocketChecker(WebSocketTool):
    def __init__(self):
        cherrypy.Tool.__init__(self, 'before_handler', self.upgrade)
        self._priority = cherrypy.tools.sessions._priority + 1  # must be initialized after the sessions tool

    def upgrade(self, **kwargs):
        try:
            kwargs['handler_cls'].check_authentication()
        except WebSocketAuthError:
            raise cherrypy.HTTPError(401, 'You must be logged in to establish a websocket connection.')
        except:
            log.error('unexpected websocket authentication error', exc_info=True)
            raise cherrypy.HTTPError(401, 'unexpected authentication error')
        else:
            return WebSocketTool.upgrade(self, **kwargs)

cherrypy.tools.websockets = WebSocketChecker()

websocket_plugin = WebSocketPlugin(cherrypy.engine)
if hasattr(WebSocketPlugin.start, '__func__'):
    WebSocketPlugin.start.__func__.priority = 66
else:
    WebSocketPlugin.start.priority = 66
websocket_plugin.subscribe()

local_broadcaster = Caller(local_broadcast)
broadcaster = Caller(WebSocketDispatcher.broadcast)
responder = Caller(WebSocketDispatcher.handle_message, threads=config['ws.thread_pool'])
