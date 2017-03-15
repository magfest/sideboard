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
from sideboard.lib import log, config, subscribes, notifies, services, cached_property, WebSocket
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


@pytest.mark.functional
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

    def tearDown(self):
        while not self.ws.q.empty():
            self.ws.q.get_nowait()

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
        pytest.raises(Empty, self.next)

    def assert_error_with(self, *args, **kwargs):
        if args:
            self.ws.ws.send(str(args[0]))
        else:
            self.ws._send(**kwargs)
        assert 'error' in self.next()

    def call(self, **params):
        callback = 'callback{}'.format(randrange(1000000))
        self.ws._send(callback=callback, **params)
        result = self.next()
        assert callback == result['callback']
        return result

    def subscribe(self, **params):
        params.setdefault('client', self.client)
        return self.call(**params)

    def unsubscribe(self, client=None):
        self.call(action='unsubscribe', client=client or self.client)


class JsonrpcTest(SideboardServerTest):
    @pytest.fixture(autouse=True)
    def override(self, service_patcher):
        service_patcher('testservice', self)

    def get_message(self, name):
        return 'Hello {}!'.format(name)

    def send_json(self, body, content_type='application/json'):
        if isinstance(body, dict):
            body['id'] = self._testMethodName
        resp = requests.post(self.jsonrpc_url, data=json.dumps(body),
                             headers={'Content-Type': 'application/json'})
        assert resp.json
        return resp.json()

    def test_rpctools(self):
        assert 'Hello World!' == self.jsonrpc.testservice.get_message('World')

    def test_content_types(self):
        for ct in ['text/html', 'text/plain', 'application/javascript', 'text/javascript', 'image/gif']:
            response = self.send_json({
                'method': 'testservice.get_message',
                'params': ['World']
            }, content_type=ct)
            assert 'Hello World!' == response['result'], 'Expected success with valid reqeust using Content-Type {}'.format(ct)


class TestWebsocketSubscriptions(SideboardServerTest):
    @pytest.fixture(autouse=True)
    def override(self, service_patcher, config_patcher):
        config_patcher(1, 'ws.call_timeout')
        service_patcher('self', self)

    def echo(self, s):
        self.echoes.append(s)
        return s

    def slow_echo(self, s):
        sleep(2)
        return s

    @subscribes('names')
    def get_names(self):
        return self.names

    @notifies('names')
    def change_name(self, name=None):
        self.names[-1] = name or uuid4().hex

    @notifies('names')
    def change_name_then_error(self):
        self.names[:] = reversed(self.names)
        self.fail()

    def indirectly_change_name(self):
        self.change_name(uuid4().hex)

    @subscribes('places')
    def get_places(self):
        return self.places

    @notifies('places')
    def change_place(self):
        self.places[0] = uuid4().hex

    @subscribes('names', 'places')
    def get_names_and_places(self):
        return self.names + self.places

    def setUp(self):
        SideboardServerTest.setUp(self)
        self.echoes = []
        self.places = ['Here']
        self.names = ['Hello', 'World']
        self.client = self._testMethodName

    def test_echo(self):
        self.ws._send(method='self.echo', params='hello')
        self.ws._send(method='self.echo', params=['hello'])
        self.ws._send(method='self.echo', params={'s': 'hello'})
        self.assert_no_response()
        self.ws._send(method='self.echo', params='hello', callback='cb123')
        self.next()
        assert ['hello'] * 4 == self.echoes

    def test_errors(self):
        self.assert_error_with(0)
        self.assert_error_with([])
        self.assert_error_with('')
        self.assert_error_with('x')
        self.assert_error_with(None)

        self.assert_error_with(method='missing')
        self.assert_error_with(method='close_all')
        self.assert_error_with(method='crud.missing')
        self.assert_error_with(method='too.many.dots')
        self.assert_error_with(method='self.echo.extra')

        self.assert_error_with(method='self.echo')
        self.assert_error_with(method='self.echo', params=['too', 'many'])
        self.assert_error_with(method='self.echo', params={'invalid': 'name'})
        self.assertEqual([], self.echoes)

        self.assert_error_with(method='self.fail')

    def test_callback(self):
        result = self.call(method='self.echo', params='hello')
        assert 'hello' == result['data']
        assert 'client' not in result

        result = self.call(method='crud.echo', params='hello', client='ds123')
        assert 'ds123' == result['client']

    def test_client_and_callback(self):
        self.call(method='self.get_name', client=self.client)
        self.assert_no_response()

    def test_triggered(self):
        self.subscribe(method='self.get_names')
        with self.open_ws() as other_ws:
            other_ws._send(method='self.change_name', params=['Kitty'])
        self.assert_incoming()

    def test_indirect_trigger(self):
        self.subscribe(method='self.get_names')
        with self.open_ws() as other_ws:
            other_ws._send(method='self.indirectly_change_name')
        self.assert_incoming()

    def test_unsubscribe(self):
        self.test_triggered()
        self.unsubscribe()
        self.call(method='self.change_name', params=[uuid4().hex])
        self.assert_no_response()

    def test_errors_still_triggers(self):
        with self.open_ws() as other_ws:
            self.subscribe(method='self.get_names')
            other_ws._send(method='self.change_name_then_error')
            self.assert_incoming()

    def test_triggered_error(self):
        with self.open_ws() as other_ws:
            self.subscribe(method='self.get_names')
            self.names.append(object())
            other_ws._send(method='self.change_name_then_error')
            self.names[:] = ['Hello'] * 2
            other_ws._send(method='self.change_name')
            self.assert_incoming()

    def test_multiple_subscriptions(self):
        self.subscribe(method='self.get_names')
        self.subscribe(method='self.get_places')
        self.assert_no_response()
        with self.open_ws() as other_ws:
            other_ws._send(method='self.change_name')
            self.assert_incoming()
            other_ws._send(method='self.change_place')
            self.assert_incoming()
            other_ws._send(method='self.echo', params='Hello')
            self.assert_no_response()

    def test_multiple_triggers(self):
        self.subscribe(method='self.get_names_and_places')
        self.assert_no_response()
        with self.open_ws() as other_ws:
            other_ws._send(method='self.change_name')
            self.assert_incoming()
            other_ws._send(method='self.change_place')
            self.assert_incoming()
            other_ws._send(method='self.echo', params='Hello')
            self.assert_no_response()

    def test_multiple_clients(self):
        self.subscribe(method='self.get_names', client='client1')
        self.subscribe(method='self.get_names', client='client2')
        self.assert_no_response()
        with self.open_ws() as other_ws:
            other_ws._send(method='self.change_name')
            assert {'client1', 'client2'} == {self.next()['client'], self.next()['client']}

    def test_nonlocking_echo(self):
        self.ws._send(method='self.slow_echo', params=['foo'],
                          client='client1', callback='cb11')
        sleep(1)
        self.ws._send(method='self.echo', params=['bar'], client='client2',
                          callback='cb22')
        self.assert_incoming(data='bar', client='client2')
        self.assert_incoming(data='foo', client='client1', timeout=2)

    def test_client_locking(self):
        self.ws._send(method='self.slow_echo', params=['foo'],
                          client=self.client, callback='cb1')
        sleep(1)
        self.ws._send(method='self.echo', params=['bar'],
                          client=self.client, callback='cb2')
        self.assert_incoming(data='foo', timeout=2)
        self.assert_incoming(data='bar')

    def test_jsonrpc_notification(self):
        self.subscribe(method='self.get_names')
        self.jsonrpc.self.change_name()
        self.assert_incoming()

    def test_jsonrpc_websocket_client(self):
        self.addCleanup(setattr, self.jsonrpc, "_prepare_request",
                        self.jsonrpc._prepare_request)
        self.jsonrpc._prepare_request = lambda data, headers: data.update(
            {'websocket_client': self.client})
        self.jsonrpc.self.change_name()
        self.assert_no_response()


class TestWebsocketCall(SideboardServerTest):
    @pytest.fixture(autouse=True)
    def override(self, service_patcher, config_patcher):
        config_patcher(1, 'ws.call_timeout')
        service_patcher('test', self)

    def fast(self):
        return 'fast'

    def slow(self):
        sleep(2)
        return 'slow'

    def test_fast(self):
        assert self.ws.call('test.fast') == 'fast'

    def test_slow(self):
        pytest.raises(Exception, self.ws.call, 'test.slow')


class TestWebsocketsCrudSubscriptions(SideboardServerTest):
    @pytest.fixture(autouse=True)
    def override(self, service_patcher):
        class MockCrud:
            pass
        mr = self.mr = MockCrud()
        for name in ['create', 'update', 'delete']:
            setattr(mr, name, Session.crud.crud_notifies(self.make_crud_method(name), delay=0.5))
        for name in ['read', 'count']:
            setattr(mr, name, Session.crud.crud_subscribes(self.make_crud_method(name)))
        service_patcher('crud', mr)

    def setUp(self):
        SideboardServerTest.setUp(self)
        self.ws.close()
        self.ws = self.open_ws()
        self.client = self._testMethodName

    def make_crud_method(self, name):
        def crud_method(*args, **kwargs):
            log.debug('mocked crud.{}'.format(name))
            assert not getattr(self.mr, name + '_error', False)
            return uuid4().hex

        crud_method.__name__ = name.encode('utf-8') if six.PY2 else name
        return crud_method

    def models(self, *models):
        return [{'_model': model} for model in models]

    def read(self, *models):
        self.ws._send(method='crud.read', client=self.client, params=self.models(*models))
        self.assert_incoming(trigger='subscribe')

    def update(self, *models, **kwargs):
        client = kwargs.get('client', 'unique_client_' + uuid4().hex)
        self.ws._send(method='crud.update', client=client, params=self.models(*models))
        self.assert_incoming(client=client)

    def test_read(self):
        self.read('User')
        self.assert_no_response()

    def test_triggered_read(self):
        self.read('User')
        self.update('User')
        self.assert_incoming(trigger='update')

    def test_unsubscribe(self):
        self.test_triggered_read()
        self.unsubscribe()
        self.update('User')
        self.assert_no_response()

    def test_triggered_error(self):
        self.mr.update_error = True
        with self.open_ws() as other_ws:
            other_ws._send(method='crud.read', client='other_tte', params=self.models('User'))
            self.assert_incoming(other_ws, client='other_tte')
            self.update('User')
            self.ws._send(method='crud.update', client=self.client, params=self.models('User'))
            assert 'error' in self.next()
            self.assert_incoming(other_ws, client='other_tte', trigger='update')

    def test_indirect_trigger(self):
        def account(*attrs):
            if len(attrs) == 1:
                return {'_model': 'Account', 'field': attrs[0]}
            else:
                return {'_model': 'Account',
                        'or': [{'field': attr} for attr in attrs]}

        def call(*attrs):
            self.call(method='crud.read', client=self.client, params=account(*attrs))

        def assert_update_triggers(model):
            self.update(model)
            self.assert_incoming()

        call('xxx')
        assert_update_triggers('Account')
        self.unsubscribe()

        call('user.xxx')
        assert_update_triggers('User')
        assert_update_triggers('Account')
        self.unsubscribe()

        call('user.xxx', 'boss.xxx')
        assert_update_triggers('Account')
        assert_update_triggers('User')
        assert_update_triggers('Account')
        self.unsubscribe()

        call('user.tags.xxx')
        assert_update_triggers('Account')
        assert_update_triggers('User')
        assert_update_triggers('Tag')

        self.update('Boss')
        self.assert_no_response()

    def test_trigger_and_callback(self):
        result = self.call(method='crud.read', params=self.models('User'), client='ds_ttac')
        self.assert_no_response()

    def test_multiple_triggers(self):
        self.read('User', 'Boss')
        self.update('User')
        self.assert_incoming()
        self.update('Boss')
        self.assert_incoming()
        self.update('Account')
        self.assert_no_response()

    def test_trigger_changed(self):
        self.read('User')
        self.read('Boss')
        self.update('User')
        self.assert_no_response()
        self.update('Boss')
        self.assert_incoming()
        self.assert_no_response()

    def test_multiple_clients(self):
        self.read('Boss')
        self.ws._send(method='crud.read', client='other_tmc', params=self.models('Boss'))
        self.assert_incoming(client='other_tmc')
        self.update('User')
        self.assert_no_response()
        self.read('Boss')
        self.ws._send(method='crud.update', client='unused_client', params=self.models('Boss'))
        self.next()
        assert {self.client, 'other_tmc'} == {self.next()['client'], self.next()['client']}

    def test_broadcast_error(self):
        with self.open_ws() as other_ws:
            self.read('User')
            other_ws._send(method='crud.count', client='other_tbe', params=self.models('User'))
            self.assert_incoming(other_ws, client='other_tbe')
            self.mr.count_error = True
            self.update('User', client='other_client_so_everything_will_trigger')
            self.assert_incoming(trigger='update', timeout=5)

    def test_jsonrpc_notifications(self):
        self.read('User')
        self.jsonrpc.crud.delete({'_model': 'User', 'field': 'name', 'value': 'Does Not Exist'})
        self.assert_incoming(trigger='delete')

        self.jsonrpc._prepare_request = lambda data, headers: data.update({'websocket_client': self.client})
        self.jsonrpc.crud.delete({'_model': 'User', 'field': 'name', 'value': 'Does Not Exist'})
        self.assert_no_response()
