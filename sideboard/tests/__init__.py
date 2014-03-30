from __future__ import unicode_literals
import os
import py
import re
import sys
import socket
import logging
from time import sleep
from urllib import urlencode
from random import randrange
from unittest import TestCase
from Queue import Queue, Empty
from contextlib import closing
from urlparse import urlparse, parse_qsl

import cherrypy
import requests
from rpctools.jsonrpc import ServerProxy
from ws4py.server.cherrypyserver import WebSocketPlugin

import sideboard.websockets
from sideboard.lib import config, services, WebSocket, cached_property
from sideboard.internal.imports import use_plugin_virtualenv, _is_plugin_name


class LogCatcher(object):
    class Handler(logging.Handler):
        def __init__(self):
            self.records = []
            logging.Handler.__init__(self)
        
        def emit(self, record):
            self.records.append(record)
    
    def __init__(self, present, level, message=''):
        self.entered = False
        self.present, self.level, self.message = present, level, message
    
    def __del__(self):
        if not self.entered:
            os.write(1, 'WARNING: assert_logged must be used as a context manager; your assertion is probably not checking what you think it is\n')
    
    def __enter__(self):
        self.entered = True
        self.handler = self.Handler()
        logging.getLogger().addHandler(self.handler)
        return self
    
    def __exit__(self, exc_type, exc_value, traceback):
        logging.getLogger().removeHandler(self.handler)
        if exc_type is None:
            at_level = [r for r in self.handler.records if r.levelno == self.level]
            messages = [r.message for r in at_level]
            if self.present:
                assert at_level, 'no log messages emitted at {} level'.format(logging.getLevelName(self.level))
            elif not self.message:
                assert not at_level, 'log messages emitted at {} level: {}'.format(logging.getLevelName(self.level), messages)
            
            if self.message:
                matched = [r for r in at_level if re.findall(self.message, r.message)]
                if self.present:
                    assert matched, 'no log messages matched your pattern {!r}: {}'.format(self.message, messages)
                else:
                    assert not matched, 'log message found which matched your pattern {!r}'.format(self.message)


@py.test.mark.functional
class SideboardTest(TestCase):
    maxDiff = None
    Session = None

    def assert_logged(self, level, message=''):
        return LogCatcher(True, level, message)

    def assert_not_logged(self, level, message=''):
        return LogCatcher(False, level, message)

    def override(self, name, module=None):
        services._services[name] = module or self

    def wait_for(self, func, *args, **kwargs):
        for i in range(50):
            cherrypy.engine.publish('main')  # since our unit tests don't call cherrypy.engine.block, we must publish this event manually
            try:
                result = func(*args, **kwargs)
                assert result or result is None
            except:
                sleep(0.1)
            else:
                break
        else:
            self.fail()

    def wait_for_eq(self, target, func, *args, **kwargs):
        try:
            self.wait_for(lambda: target == func(*args, **kwargs))
        except:
            self.fail('{!r} != {!r}'.format(target, func(*args, **kwargs)))

    def wait_for_ne(self, target, func, *args, **kwargs):
        try:
            self.wait_for(lambda: target != func(*args, **kwargs))
        except:
            self.fail('{!r} == {!r}'.format(target, func(*args, **kwargs)))

    def patch_config(self, value, *path):
        conf = config
        for section in path[:-1]:
            conf = conf[section]
        self.addCleanup(conf.__setitem__, path[-1], value)
        conf[path[-1]] = value

    def configure_db(self):
        def _patch_session():
            import sqlalchemy
            from sqlalchemy import event
            from sqlalchemy.orm import sessionmaker
            
            self.addCleanup(setattr, self.Session, 'engine', self.Session.engine)
            self.addCleanup(setattr, self.Session, 'session_factory', self.Session.session_factory)
            
            self.Session.engine = sqlalchemy.create_engine('sqlite:///' + os.path.join(config['root'], 'data', 'test.db'))
            event.listen(self.Session.engine, 'connect', lambda conn, record: conn.execute('pragma foreign_keys=ON'))
            self.Session.session_factory = sessionmaker(bind=self.Session.engine, autoflush=False, autocommit=False)
        
        if self.Session:
            possible_plugin = self.__class__.__module__.split('.')[0]
            if _is_plugin_name(possible_plugin):
                with use_plugin_virtualenv(possible_plugin):
                    _patch_session()
            else:
                _patch_session()

    @classmethod
    def setUpClass(cls):
        cls.orig_services = dict(services._services)  # shallow copy

    def setUp(self):
        self.configure_db()
        self.addCleanup(services._services.update, self.orig_services)
        if self.Session:
            self.Session.initialize_db(drop=True)


@py.test.mark.functional
class SideboardServerTest(SideboardTest):
    port = config['cherrypy']['server.socket_port']
    jsonrpc_url = 'http://localhost:{}/jsonrpc'.format(port)
    jsonrpc = ServerProxy(jsonrpc_url)

    rsess_username = 'unit_tests'

    @staticmethod
    def assert_port_open(port):
        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(('0.0.0.0', port))

    @classmethod
    def start_cherrypy(cls):
        class Root(object):
            @cherrypy.expose
            def index(self):
                cherrypy.session['username'] = cls.rsess_username
                return cls.rsess_username

        cherrypy.tree.apps.pop('/mock_login', None)
        cherrypy.tree.mount(Root(), '/mock_login')

        cls.assert_port_open(cls.port)
        cherrypy.config.update({'engine.autoreload_on': False})
        cherrypy.engine.start()
        cherrypy.engine.wait(cherrypy.engine.states.STARTED)

    @classmethod
    def stop_cherrypy(cls):
        cherrypy.engine.stop()
        cherrypy.engine.wait(cherrypy.engine.states.STOPPED)
        cherrypy.engine.state = cherrypy.engine.states.EXITING

        # ws4py does not support stopping and restarting CherryPy
        sideboard.websockets.websocket_plugin.unsubscribe()
        sideboard.websockets.websocket_plugin = WebSocketPlugin(cherrypy.engine)
        sideboard.websockets.websocket_plugin.subscribe()

    @classmethod
    def setUpClass(cls):
        super(SideboardServerTest, cls).setUpClass()
        cls.start_cherrypy()
        cls.ws = cls.patch_websocket(services.get_websocket())
        cls.ws.connect(max_wait=5)
        assert cls.ws.connected

    @classmethod
    def tearDownClass(cls):
        cls.stop_cherrypy()
        super(SideboardServerTest, cls).tearDownClass()

    @staticmethod
    def patch_websocket(ws):
        ws.q = Queue()
        ws.fallback = ws.q.put
        return ws

    def setUp(self):
        SideboardTest.setUp(self)

    @cached_property
    def rsess(self):
        rsess = requests.Session()
        rsess.trust_env = False
        self._get(rsess, '/mock_login')
        return rsess

    def url(self, path, **query_params):
        params = dict(parse_qsl(urlparse(path).query))
        params.update(query_params)
        url = 'http://localhost:{}{}'.format(self.port, urlparse(path).path)
        if params:
            url += '?' + urlencode(params)
        return url

    def _get(self, rsess, path, **params):
        return rsess.get(self.url(path, **params))

    def get(self, path, **params):
        return self._get(self.rsess, path, **params).content

    def get_json(self, path, **params):
        return self._get(self.rsess, path, **params).json()

    def open_ws(self):
        return self.patch_websocket(WebSocket(connect_immediately=True, max_wait=5))

    def next(self, ws=None, timeout=2):
        return (ws or self.ws).q.get(timeout=timeout)

    def assert_incoming(self, ws=None, client=None, timeout=1, **params):
        data = self.next(ws, timeout)
        assert (client or self.client) == data.get('client')
        for key, val in params.items():
            assert val == data[key]

    def assert_no_response(self):
        self.assertRaises(Empty, self.next)

    def assert_error_with(self, *args, **kwargs):
        if args:
            self.ws.ws.send(str(args[0]))
        else:
            self.ws._send(**kwargs)
        self.assertIn('error', self.next())

    def call(self, **params):
        callback = 'callback{}'.format(randrange(1000000))
        self.ws._send(callback=callback, **params)
        result = self.next()
        self.assertEqual(callback, result['callback'])
        return result

    def subscribe(self, **params):
        params.setdefault('client', self.client)
        return self.call(**params)

    def unsubscribe(self, client=None):
        self.call(action='unsubscribe', client=client or self.client)
