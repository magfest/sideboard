from __future__ import unicode_literals

import pytest
from mock import Mock, ANY

import ws4py.websocket

from sideboard.websockets import WebSocketDispatcher
from sideboard.lib import log, WebSocket, threadlocal, stopped
from sideboard.tests import config_patcher


@pytest.fixture(autouse=True)
def reset_stopped():
    stopped.clear()


@pytest.fixture
def ws(monkeypatch):
    ws = WebSocket(connect_immediately=False)
    monkeypatch.setattr(log, 'warn', Mock())
    ws._send = Mock()
    ws._next_id = lambda prefix: 'xxx'
    return ws


@pytest.fixture
def orig_ws(monkeypatch):
    monkeypatch.setattr(ws4py.websocket.WebSocket, '__init__', Mock(return_value=None))
    monkeypatch.setattr(WebSocketDispatcher, 'check_authentication', Mock(return_value={'username': 'mock_username'}))
    return WebSocketDispatcher()


def test_subscribe_basic(ws):
    callback = Mock()
    assert 'xxx' == ws.subscribe(callback, 'foo.bar', 'x', 'y')
    registered = ws._callbacks['xxx'].copy()
    del registered['errback']
    assert registered == {
        'client': 'xxx',
        'callback': callback,
        'method': 'foo.bar',
        'params': ('x', 'y')
    }
    ws._send.assert_called_with(method='foo.bar', params=('x', 'y'), client='xxx')
    assert not log.warn.called


def test_subscribe_advanced(ws):
    callback, errback = Mock(), Mock()
    request = {
        'client': 'yyy',
        'callback': callback,
        'errback': errback
    }
    assert 'yyy' == ws.subscribe(request, 'foo.bar', 'x', 'y')
    assert ws._callbacks['yyy'] == {
        'client': 'yyy',
        'callback': callback,
        'errback': errback,
        'method': 'foo.bar',
        'params': ('x', 'y')
    }
    ws._send.assert_called_with(method='foo.bar', params=('x', 'y'), client='yyy')
    assert not log.warn.called


def test_subscribe_error(ws):
    ws._send = Mock(side_effect=Exception)
    ws.subscribe(Mock(), 'foo.bar')
    assert 'xxx' in ws._callbacks
    assert log.warn.called


def test_subscribe_paramback(ws):
    paramback = lambda: (5, 6)
    callback, errback = Mock(), Mock()
    request = {
        'client': 'yyy',
        'callback': callback,
        'errback': errback,
        'paramback': paramback
    }
    assert 'yyy' == ws.subscribe(request, 'foo.bar')
    assert ws._callbacks['yyy'] == {
        'client': 'yyy',
        'callback': callback,
        'errback': errback,
        'paramback': paramback,
        'method': 'foo.bar',
        'params': (5, 6)
    }
    ws._send.assert_called_with(method='foo.bar', params=(5, 6), client='yyy')
    assert not log.warn.called


def test_unsubscribe(ws):
    ws._callbacks['xxx'] = {}
    ws.unsubscribe('xxx')
    assert 'xxx' not in ws._callbacks
    ws._send.assert_called_with(client='xxx', action='unsubscribe')


@pytest.fixture
def returner(ws):
    ws._send = Mock(side_effect=lambda **kwargs: ws._callbacks['xxx']['callback'](123))
    return ws


@pytest.fixture
def errorer(ws):
    ws._send = Mock(side_effect=lambda **kwargs: ws._callbacks['xxx']['errback']('fail'))
    return ws


def test_call_raises_on_send_error(ws):
    ws._send = Mock(side_effect=Exception)
    pytest.raises(Exception, ws.call, 'foo.bar')
    assert 'xxx' not in ws._callbacks


def test_call_returns_value(returner):
    assert 123 == returner.call('foo.bar')
    assert 'xxx' not in returner._callbacks


def test_call_error(errorer):
    pytest.raises(Exception, errorer.call, 'foo.bar')
    assert 'xxx' not in errorer._callbacks


def test_call_timeout(ws, config_patcher, monkeypatch):
    monkeypatch.setattr(stopped, 'is_set', Mock(return_value=False))
    config_patcher(1, 'ws.call_timeout')
    pytest.raises(Exception, ws.call, 'foo.bar')
    assert 'xxx' not in ws._callbacks
    assert 9 <= stopped.is_set.call_count <= 11


def test_call_stopped_set(ws, request, monkeypatch):
    request.addfinalizer(stopped.clear)
    stopped.set()
    pytest.raises(Exception, ws.call, 'foo.bar')


@pytest.fixture
def refirer(ws):
    ws._callbacks.update({
        'xxx': {'method': 'x.x', 'params': (1, 2), 'client': 'xxx'},
        'yyy': {'method': 'y.y', 'params': (3, 4)},
        'zzz': {'method': 'z.z', 'params': (5, 6), 'client': 'zzz'}
    })
    return ws


def test_refire(refirer):
    refirer._refire_subscriptions()
    assert refirer._send.call_count == 2
    refirer._send.assert_any_call(method='x.x', params=(1, 2), client='xxx')
    refirer._send.assert_any_call(method='z.z', params=(5, 6), client='zzz')


def test_refire_error(refirer):
    refirer._send = Mock(side_effect=Exception)
    refirer._refire_subscriptions()
    assert refirer._send.call_count == 1


def test_make_method_caller(ws):
    ws.call = Mock()
    func = ws.make_caller('foo.bar')
    func(1, 2)
    ws.call.assert_called_with('foo.bar', 1, 2)


def test_make_subscription_caller(ws, orig_ws):
    threadlocal.reset(message={'client': 'xxx'}, websocket=orig_ws)
    func = ws.make_caller('foo.bar')
    assert func(1, 2) == orig_ws.NO_RESPONSE
    ws._send.assert_called_with(method='foo.bar', params=(1, 2), client=ANY)


def test_make_updated_subscription_caller(ws, orig_ws):
    threadlocal.reset(message={'client': 'xxx'}, websocket=orig_ws)
    func = ws.make_caller('foo.bar')
    assert func is ws.make_caller('foo.baz')


def test_make_subscription_unsubscribe(ws, orig_ws):
    ws.unsubscribe = Mock()
    ws._next_id = Mock(return_value='xxx')
    threadlocal.reset(message={'client': 'yyy'}, websocket=orig_ws)
    ws.make_caller('foo.bar').unsubscribe()
    ws.unsubscribe.assert_called_with('xxx')


def test_preprocess_call(ws, returner):
    ws.preprocess = lambda method, params: ['mock_modified_params']
    assert 123 == ws.call('foo.bar')
    ws._send.assert_called_with(method='foo.bar', params=['mock_modified_params'], callback='xxx')


def test_preprocess_subscribe(ws):
    ws.preprocess = lambda method, params: ['mock_modified_params']
    callback = Mock()
    assert 'xxx' == ws.subscribe(callback, 'foo.bar')
    registered = ws._callbacks['xxx'].copy()
    del registered['errback']
    assert registered == {
        'client': 'xxx',
        'callback': callback,
        'method': 'foo.bar',
        'params': ['mock_modified_params']
    }
    ws._send.assert_called_with(method='foo.bar', params=['mock_modified_params'], client='xxx')
