from __future__ import unicode_literals
import json
import socket
from uuid import uuid4
from time import sleep
from random import randrange
from unittest import TestCase

import six
from six.moves.queue import Queue, Empty
from six.moves.urllib.parse import urlparse, urlencode, parse_qsl

import pytest
import cherrypy
import requests
from rpctools.jsonrpc import ServerProxy
from ws4py.server.cherrypyserver import WebSocketPlugin

import sideboard.websockets
from sideboard.lib import log, config, subscribes, notifies, notify, services, cached_property, WebSocket
from sideboard.tests import service_patcher, config_patcher, get_available_port
from sideboard.tests.test_sa import Session


if config['cherrypy']['server.socket_port'] == 0:
    available_port = get_available_port()

    # The config is updated in two places because by the time this code is
    # executed, cherrypy.config will already be populated with the values from
    # our config file. The configuration will already be living in two places,
    # each of which must be updated.
    config['cherrypy']['server.socket_port'] = available_port
    cherrypy.config.update({'server.socket_port': available_port})


class SideboardServerTest(TestCase):
    port = config['cherrypy']['server.socket_port']
    jsonrpc_url = 'http://127.0.0.1:{}/jsonrpc'.format(port)
    jsonrpc = ServerProxy(jsonrpc_url)

    rsess_username = 'unit_tests'

    @staticmethod
    def assert_can_connect_to_localhost(port):
        for i in range(50):
            try:
                socket.create_connection(('127.0.0.1', port)).close()
            except Exception as e:
                sleep(0.1)
            else:
                break
        else:
            raise e

    @classmethod
    def start_cherrypy(cls):
        config['thread_wait_interval'] = 0.1

        class Root(object):
            @cherrypy.expose
            def index(self):
                cherrypy.session['username'] = cls.rsess_username
                return cls.rsess_username

        cherrypy.tree.apps.pop('/mock_login', None)
        cherrypy.tree.mount(Root(), '/mock_login')

        cherrypy.config.update({'engine.autoreload_on': False})
        cherrypy.engine.start()
        cherrypy.engine.wait(cherrypy.engine.states.STARTED)
        cls.assert_can_connect_to_localhost(cls.port)

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

    @classmethod
    def tearDownClass(cls):
        cls.stop_cherrypy()
        super(SideboardServerTest, cls).tearDownClass()

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
            raise AssertionError('wait timed out')

    def wait_for_eq(self, target, func, *args, **kwargs):
        try:
            self.wait_for(lambda: target == func(*args, **kwargs))
        except:
            raise AssertionError('{!r} != {!r}'.format(target, func(*args, **kwargs)))

    def wait_for_ne(self, target, func, *args, **kwargs):
        try:
            self.wait_for(lambda: target != func(*args, **kwargs))
        except:
            raise AssertionError('{!r} == {!r}'.format(target, func(*args, **kwargs)))

    @cached_property
    def rsess(self):
        rsess = requests.Session()
        rsess.trust_env = False
        self._get(rsess, '/mock_login')
        return rsess

    def url(self, path, **query_params):
        params = dict(parse_qsl(urlparse(path).query))
        params.update(query_params)
        url = 'http://127.0.0.1:{}{}'.format(self.port, urlparse(path).path)
        if params:
            url += '?' + urlencode(params)
        return url

    def _get(self, rsess, path, **params):
        return rsess.get(self.url(path, **params))

    def get(self, path, **params):
        return self._get(self.rsess, path, **params).content

    def get_json(self, path, **params):
        return self._get(self.rsess, path, **params).json()

    def assert_no_response(self):
        pytest.raises(Empty, self.next)

    def subscribe(self, **params):
        params.setdefault('client', self.client)
        return self.call(**params)

    def unsubscribe(self, client=None):
        self.call(action='unsubscribe', client=client or self.client)
