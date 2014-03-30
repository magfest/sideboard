from __future__ import unicode_literals
import os
import json
from copy import deepcopy
from itertools import count
from threading import RLock
from collections import MutableMapping
from datetime import datetime, timedelta

from ws4py.client.threadedclient import WebSocketClient

import sideboard.lib
from sideboard.lib import log, config, stopped, on_startup, on_shutdown, DaemonTask, Caller


class _WebSocketClientDispatcher(WebSocketClient):
    def __init__(self, dispatcher, url, ssl_opts=None):
        self.connected = False
        self.dispatcher = dispatcher
        WebSocketClient.__init__(self, url, ssl_options=ssl_opts)

    def pre_connect(self):
        pass

    def connect(self, *args, **kwargs):
        self.pre_connect()
        WebSocketClient.connect(self, *args, **kwargs)
        self.connected = True

    def close(self, code=1000, reason=''):
        try:
            WebSocketClient.close(self, code=code, reason=reason)
        except:
            pass
        try:
            WebSocketClient.close_connection(self)
        except:
            pass
        self.connected = False

    def send(self, data):
        log.debug('sending {!r}', data)
        assert self.connected, 'tried to send data on closed websocket {!r}'.format(self.url)
        if isinstance(data, dict):
            data = json.dumps(data)
        return WebSocketClient.send(self, data)

    def received_message(self, message):
        message = str(message)
        log.debug('received {!r}', message)
        try:
            message = json.loads(message)
        except:
            log.warn('failed to parse incoming message', exc_info=True)
        finally:
            self.dispatcher.defer(message)


class WebSocket(object):
    """
    Utility class for making websocket connections.  This improves on the ws4py
    websocket client classes mainly by adding several features:
    - automatically detecting dead connections and re-connecting
    - utility methods for making synchronous rpc calls and for making
        asynchronous subscription calls with callbacks
    - adding locking to make sending messages thread-safe
    """
    poll_method = 'sideboard.poll'
    WebSocketDispatcher = _WebSocketClientDispatcher

    def __init__(self, url=None, ssl_opts=None, connect_immediately=True, max_wait=2):
        self.ws = None
        self.url = url or 'ws://localhost:{}/wsrpc'.format(config['cherrypy']['server.socket_port'])
        self._lock = RLock()
        self._callbacks = {}
        self._counter = count()
        self.ssl_opts = ssl_opts
        self._reconnect_attempts = 0
        self._last_poll, self._last_reconnect_attempt = None, None
        self._dispatcher = Caller(self._dispatch, threads=1)
        self._checker = DaemonTask(self._check, interval=1)
        if connect_immediately:
            self.connect(max_wait=max_wait)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    @property
    def _should_reconnect(self):
        interval = min(config['ws_reconnect_interval'], 2 ** self._reconnect_attempts)
        cutoff = datetime.now() - timedelta(seconds=interval)
        return not self.connected and (self._reconnect_attempts == 0 or self._last_reconnect_attempt < cutoff)

    @property
    def _should_poll(self):
        cutoff = datetime.now() - timedelta(seconds=config['ws_poll_interval'])
        return self.connected and (self._last_poll is None or self._last_poll < cutoff)

    def _check(self):
        if self._should_reconnect:
            self._reconnect()
        if self._should_poll:
            self._poll()

    def _poll(self):
        assert self.ws and self.ws.connected, 'cannot poll while websocket is not connected'
        try:
            self.call(self.poll_method)
        except:
            log.error('no poll response received from {!r}, closing connection, will attempt to reconnect', self.url, exc_info=True)
            self.ws.close()
        else:
            self._last_poll = datetime.now()

    def _reconnect(self):
        with self._lock:
            assert not self.connected, 'connection is still active'
            try:
                self.ws = self.WebSocketDispatcher(self._dispatcher, self.url, ssl_opts=self.ssl_opts)
                self.ws.connect()
            except Exception as e:
                log.warn('failed to connect to {}: {}', self.url, str(e))
                self._last_reconnect_attempt = datetime.now()
                self._reconnect_attempts += 1
            else:
                self._reconnect_attempts = 0
                try:
                    for cb in self._callbacks.values():
                        if 'client' in cb:
                            self._send(method=cb['method'], params=cb['params'], client=cb['client'])
                except:
                    pass  # self.send() already closes and logs on error

    def _next_id(self, prefix):
        return '{}-{}'.format(prefix, next(self._counter))

    def _send(self, **kwargs):
        log.debug('sending {}', kwargs)
        with self._lock:
            assert self.connected, 'tried to send data on closed websocket {!r}'.format(self.url)
            try:
                return self.ws.send(kwargs)
            except:
                log.error('failed to send {!r} on {!r}, closing websocket and will attempt to reconnect', kwargs, self.url)
                self.ws.close()
                raise

    def _dispatch(self, message):
        log.debug('dispatching {}', message)
        try:
            assert isinstance(message, dict), 'incoming message is not a dictionary'
            assert 'client' in message or 'callback' in message, 'no callback or client in message {}'.format(message)
            id = message.get('client') or message.get('callback')
            assert id in self._callbacks, 'unknown dispatchee {}'.format(id)
        except AssertionError:
            self.fallback(message)
        else:
            if 'error' in message:
                self._callbacks[id]['errback'](message['error'])
            else:
                self._callbacks[id]['callback'](message.get('data'))

    def fallback(self, message):
        log.error('no callback registered for message {!r}', message, exc_info=True)
        raise

    @property
    def connected(self):
        """boolean indicating whether or not this connection is currently active"""
        return bool(self.ws) and self.ws.connected

    def connect(self, max_wait=0):
        self._checker.start()
        self._dispatcher.start()
        for i in range(10 * max_wait):
            if not self.connected:
                stopped.wait(0.1)
            else:
                break
        else:
            if max_wait:
                log.warn('websocket {!r} not connected after {} seconds', self.url, max_wait)

    def close(self):
        """
        Closes the underlying websocket connection and stops background tasks.
        This method is always safe to call; exceptions will be swallowed and
        logged, and calling close on an already-closed websocket is a no-op.
        """
        self._checker.stop()
        self._dispatcher.stop()
        if self.ws:
            self.ws.close()

    def subscribe(self, callback, method, *args, **kwargs):
        """
        Send a websocket request which you expect to subscribe you to a channel
        with a callback which will be called every time there is new data, and
        return the client id which uniquely identifies this subscription.
        
        Callback may be either a function or a dictionary in the form
        {
            'callback': <function>,
            'errback': <function>
        }
        Both callback and errback take a single argument; for callback, this is
        the return value of the method, for errback it is the error message
        returning.  If no errback is specified, we will log errors at the ERROR
        level and do nothing further.
        
        The positional and keyword arguments passed to this function will be
        used as the arguments to the remote method.
        """
        client = self._next_id('client')
        if isinstance(callback, dict):
            assert 'callback' in callback and 'errback' in callback, 'callback and errback are required'
            client = callback.setdefault('client', client)
            self._callbacks[client] = callback
        else:
            self._callbacks[client] = {
                'client': client,
                'callback': callback,
                'errback': lambda result: log.error('{}(*{}, **{}) returned an error: {!r}', method, args, kwargs, result)
            }
        self._callbacks[client].update({
            'method': method,
            'params': args or kwargs
        })
        try:
            self._send(method=method, params=args or kwargs, client=client)
        except:
            log.warn('initial subscription to {} at {!r} failed, will retry on reconnect', method, self.url)
        return client

    def unsubscribe(self, client):
        """
        Cancel the websocket subscription identified by the specified client id.
        This id is returned from the subscribe() method, e.g.
        
        >>> client = ws.subscribe(some_callback, 'foo.some_function')
        >>> ws.unsubscribe(client)
        """
        self._callbacks.pop(client, None)
        if self.connected:
            self._send(action='unsubscribe', client=client)

    def call(self, method, *args, **kwargs):
        """
        Send a websocket rpc method call, then wait for and return the eventual
        response, or raise an exception if we get back an error.  This method
        will raise an AssertionError after 10 seconds if no response of any
        kind was received.  The positional and keyword arguments to this method
        are used as the arguments to the rpc function call.
        """
        result, error = [], []
        callback = self._next_id('callback')
        self._callbacks[callback] = {
            'callback': result.append,
            'errback': error.append
        }
        try:
            self._send(method=method, params=args or kwargs, callback=callback)
        except:
            self._callbacks.pop(callback, None)
            raise

        for i in range(10 * config['ws_call_timeout']):
            stopped.wait(0.1)
            if stopped.is_set() or result or error:
                break
        self._callbacks.pop(callback, None)
        assert not stopped.is_set(), 'websocket closed before response was received'
        assert result, error[0] if error else 'no response received for 10 seconds'
        return result[0]

    def make_caller(self, method):
        """
        Returns a function which calls the specified method; useful for creating
        callbacks, e.g.
        
        >>> authenticate = ws.make_caller('auth.authenticate')
        >>> authenticate('username', 'password')
        True
        """
        return lambda *args, **kwargs: self.call(method, *args, **kwargs)


class Model(MutableMapping):
    """
    Utility class for representing database objects found in the databases of
    other Sideboard plugins.  Instances of this class can have their values accessed
    as either attributes or dictionary keys.
    """
    _prefix = None
    _unpromoted = ()
    _defaults = None

    def __init__(self, data, prefix=None, unpromoted=None, defaults=None):
        assert prefix or self._prefix
        object.__setattr__(self, '_data', deepcopy(data))
        object.__setattr__(self, '_orig_data', deepcopy(data))
        object.__setattr__(self, '_prefix', (prefix or self._prefix) + '_')
        object.__setattr__(self, '_project_key', self._prefix + 'data')
        object.__setattr__(self, '_unpromoted', self._unpromoted if unpromoted is None else unpromoted)
        object.__setattr__(self, '_defaults', defaults or self._defaults or {})

    @property
    def query(self):
        assert self.id, 'id was not set'
        assert self._model, '_model was not set'
        return {'_model': self._model, 'field': 'id', 'value': self.id}

    @property
    def dirty(self):
        return {k:v for k,v in self._data.items() if v != self._orig_data.get(k)}
    
    def to_dict(self):
        data = deepcopy(self._data)
        serialized = {k: v for k,v in data.pop(self._project_key, {}).items()}
        for k in data.get('extra_data', {}).keys():
            if k.startswith(self._prefix):
                serialized[k[len(self._prefix):]] = data['extra_data'].pop(k)
            elif k in self._unpromoted:
                serialized[k] = data['extra_data'].pop(k)
        serialized.update(data)
        return serialized
    
    @property
    def _extra_data(self):
        return self._data.setdefault('extra_data', {})

    def _extra_data_key(self, key):
        return ('' if key in self._unpromoted else self._prefix) + key

    def __len__(self):
        return len(self._data) + len(self._extra_data) + len(self._data.get(self._project_key, {}))

    def __setitem__(self, key, value):
        assert key != 'id' or value == self.id, 'id is not settable'
        if key in self._data:
            self._data[key] = value
        elif self._project_key in self._data:
            self._extra_data.pop(self._prefix + key, None)
            self._data[self._project_key][key] = value
        else:
            self._extra_data[self._extra_data_key(key)] = value

    def __getitem__(self, key):
        if key in self._data:
            return self._data[key]
        elif key in self._data.get(self._project_key, {}):
            return self._data[self._project_key][key]
        else:
            return self._extra_data.get(self._extra_data_key(key), self._defaults.get(key))

    def __delitem__(self, key):
        if key in self._data:
            del self._data[key]
        elif key in self._data.get(self._project_key, {}):
            del self._data[self._project_key][key]
        else:
            self._extra_data.pop(self._extra_data_key(key), None)

    def __iter__(self):
        return iter(k for k in self.to_dict() if k != 'extra_data')
    
    def __repr__(self):
        return repr(dict(self.items()))

    def __getattr__(self, name):
        return self.__getitem__(name)

    def __setattr__(self, name, value):
        return self.__setitem__(name, value)

    def __delattr__(self, name):
        self.__delitem__(name)


class Subscription(object):
    """
    Utility class for opening a websocket to a given destination, subscribing to an rpc call,
    and processing the response.

    >>> logged_in_users = Subscription('admin.get_logged_in_users')
    >>> logged_in_users.result  # this will always be the latest return value of your rpc method

    If you want to do postprocessing on the results, you can override the "callback" method:

    >>> class UserList(Subscription):
    ...     def __init__(self):
    ...         self.usernames = []
    ...         Subscription.__init__(self, 'admin.get_logged_in_users')
    ...     
    ...     def callback(self, users):
    ...         self.usernames = [user['username'] for user in users]
    ... 
    >>> users = UserList()

    The above code gives you a "users" object with a "usernames" attribute; when Sideboard
    starts, it opens a websocket connection to whichever remote server defines the "admin"
    service (as defined in the rpc_services config section), then subscribes the the 
    "admin.get_logged_in_users" method and calls the "callback" methon on every response.
    """

    def __init__(self, rpc_method, *args, **kwargs):
        self.result = None
        connect_immediately = kwargs.pop('connect_immediately', False)
        self.method, self.args, self.kwargs = rpc_method, args, kwargs
        self.ws = sideboard.lib.services.get_websocket(rpc_method.split('.')[0])
        on_startup(self._subscribe)
        on_shutdown(self._unsubscribe)
        if connect_immediately:
            self.ws.connect(max_wait=2)
            self._subscribe()

    def _subscribe(self):
        self._client_id = self.ws.subscribe(self._callback, self.method, *self.args, **self.kwargs)

    def _unsubscribe(self):
        self.ws.unsubscribe(self._client_id)

    def refresh(self):
        """
        re-fire your subscription method and invoke the callback method with
        the response; this will manually check for changes if you are
        subscribed to a method which by design doesn't re-fire on every change
        """
        assert self.ws.connected, 'cannot refresh {}: websocket not connected'.format(self.method)
        self._callback(self.ws.call(self.method, *self.args, **self.kwargs))

    def _callback(self, response_data):
        self.result = response_data
        self.callback(response_data)

    def callback(self, response_data):
        """override this to define what to do with your rpc method return values"""
        pass
