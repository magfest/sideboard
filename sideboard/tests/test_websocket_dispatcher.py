from __future__ import unicode_literals
from collections import namedtuple

import pytest
from mock import Mock, ANY
from ws4py.websocket import WebSocket

from sideboard.lib import log, services, subscribes
from sideboard.websockets import WebSocketDispatcher, responder, threadlocal
from sideboard.tests import service_patcher


@pytest.fixture
def wsd(monkeypatch):
    monkeypatch.setattr(WebSocket, 'send', Mock())
    monkeypatch.setattr(WebSocket, 'closed', Mock())
    monkeypatch.setattr(WebSocketDispatcher, 'check_authentication', lambda self: 'mock_user')
    return WebSocketDispatcher(None)

@pytest.fixture
def ws1(): return Mock()

@pytest.fixture
def ws2(): return Mock()

@pytest.fixture
def ws3(): return Mock()

@pytest.fixture
def ws4():
    class RaisesError:
        trigger = Mock(side_effect=Exception)
    return RaisesError

@pytest.fixture(autouse=True)
def subscriptions(request, wsd, ws1, ws2, ws3, ws4):
    def reset_subscriptions():
        WebSocketDispatcher.subscriptions.clear()
    reset_subscriptions()
    request.addfinalizer(reset_subscriptions)
    WebSocketDispatcher.subscriptions['foo'][wsd]['client-0'].add('callback-0')
    WebSocketDispatcher.subscriptions['bar'][wsd]['client-0'].add(None)
    WebSocketDispatcher.subscriptions['foo'][ws1]['client-1'].add(None)
    WebSocketDispatcher.subscriptions['bar'][ws1]['client-1'].add('callback-1')
    WebSocketDispatcher.subscriptions['foo'][ws2]['client-2'].add(None)
    WebSocketDispatcher.subscriptions['baz'][ws3]['client-3'].add(None)
    WebSocketDispatcher.subscriptions['baf'][ws4]['client-3'].add(None)


def test_get_all_subscribed(wsd, ws1, ws2, ws3, ws4):
    assert WebSocketDispatcher.get_all_subscribed() == {wsd, ws1, ws2, ws3, ws4}


def test_basic_broadcast(ws1, ws2):
    WebSocketDispatcher.broadcast('bar', trigger='manual')
    ws1.trigger.assert_called_with(client='client-1', callback='callback-1', trigger='manual')
    assert not ws2.trigger.called

def test_broadcast_with_originating_client(ws1, ws2):
    WebSocketDispatcher.broadcast('foo', originating_client='client-1')
    assert ws2.trigger.called and not ws1.trigger.called

def test_multi_broadcast(ws1, ws2, ws3, ws4):
    WebSocketDispatcher.broadcast(['foo', 'bar'])
    assert ws1.trigger.called and ws2.trigger.called and not ws3.trigger.called and not ws4.trigger.called

def test_broadcast_error(ws4, monkeypatch):
    monkeypatch.setattr(log, 'warn', Mock())
    WebSocketDispatcher.broadcast('foo')
    assert not ws4.trigger.called and not log.warn.called
    WebSocketDispatcher.broadcast('baf')
    assert ws4.trigger.called and log.warn.called


def test_basic_send(wsd):
    wsd.send(foo='bar', baz=None)
    WebSocket.send.assert_called_with(ANY, '{"foo":"bar"}')

def test_send_client_caching(wsd):
    wsd.send(client='xxx', data=123)
    wsd.send(client='xxx', data=123)
    wsd.send(client='yyy', data=321)
    assert WebSocket.send.call_count == 2

def test_no_send_caching_without_client(wsd):
    wsd.send(data=123)
    wsd.send(data=123)
    wsd.send(data=321)
    assert WebSocket.send.call_count == 3

def test_callback_based_send_caching(wsd):
    wsd.send(client='xxx', callback='yyy', data=123)
    wsd.send(client='xxx', callback='yyy', data=123)
    assert WebSocket.send.call_count == 1
    wsd.send(client='xxx', callback='zzz', data=123)
    assert WebSocket.send.call_count == 2
    wsd.send(client='xxx', callback='yyy', data=123)
    wsd.send(client='xxx', callback='zzz', data=123)
    assert WebSocket.send.call_count == 2
    wsd.send(client='aaa', callback='yyy', data=123)
    assert WebSocket.send.call_count == 3
    wsd.send(client='xxx', callback='yyy', data=321)
    assert WebSocket.send.call_count == 4
    wsd.send(client='xxx', callback='zzz', data=123)
    assert WebSocket.send.call_count == 4


def test_get_method(wsd, service_patcher):
    service_patcher('foo', {
        'bar': lambda: 'Hello World!',
        'baz': 'not a function',
        '_private': lambda: 'private method'
    })
    assert wsd.get_method('foo.bar')() == 'Hello World!'
    pytest.raises(Exception, wsd.get_method, 'foo.baz')
    pytest.raises(Exception, wsd.get_method, 'foo.baf')
    pytest.raises(Exception, wsd.get_method, 'foo._private')


def test_unsubscribe_from_nonexistent(wsd):
    wsd.unsubscribe('nonexistent')  # does not error

def test_unsubscribe(wsd):
    client = 'client-1'
    wsd.client_locks[client] = 'lock'
    wsd.cached_queries[client] = 'query'
    wsd.cached_fingerprints[client] = 'fingerprint'
    WebSocketDispatcher.subscriptions['foo'] = {wsd: {client: 'subscription'}}
    wsd.unsubscribe(client)
    for d in [wsd.client_locks, wsd.cached_queries, wsd.cached_fingerprints, WebSocketDispatcher.subscriptions['foo']]:
        assert client not in d

def test_multi_unsubscribe(wsd):
    client = ['client-1', 'client-2']
    wsd.client_locks = {'client-1': 'lock', 'client-2': 'lock'}
    wsd.cached_queries = {'client-1': 'query', 'client-2': 'query'}
    wsd.cached_fingerprints = {'client-1': 'fingerprint', 'client-2': 'fingerprint'}
    WebSocketDispatcher.subscriptions['foo'] = {wsd: {'client-1': 'subscription', 'client-2': 'subscription'}}
    wsd.unsubscribe(client)
    for d in [wsd.client_locks, wsd.cached_queries, wsd.cached_fingerprints, WebSocketDispatcher.subscriptions['foo']]:
        assert 'client-1' not in d
        assert 'client-2' not in d

def test_unsubscribe_all(wsd):
    assert wsd in WebSocketDispatcher.subscriptions['foo']
    assert wsd in WebSocketDispatcher.subscriptions['bar']
    wsd.unsubscribe_all()
    assert wsd not in WebSocketDispatcher.subscriptions['foo']
    assert wsd not in WebSocketDispatcher.subscriptions['bar']


def test_update_subscriptions_with_new_callback(wsd):
    wsd.update_subscriptions(client='client-0', callback='xxx', channels='foo')
    assert WebSocketDispatcher.subscriptions['foo'][wsd]['client-0'] == {'callback-0', 'xxx'}
    assert WebSocketDispatcher.subscriptions['bar'][wsd]['client-0'] == {None}

def test_update_subscriptions_with_existing_null_callback(wsd):
    wsd.update_subscriptions(client='client-0', callback=None, channels='foo')
    assert WebSocketDispatcher.subscriptions['foo'][wsd]['client-0'] == {'callback-0', None}
    assert WebSocketDispatcher.subscriptions['bar'][wsd]['client-0'] == set()

def test_update_subscriptions_with_existing_callback(wsd):
    wsd.update_subscriptions(client='client-0', callback='callback-0', channels='baz')
    assert WebSocketDispatcher.subscriptions['foo'][wsd]['client-0'] == set()
    assert WebSocketDispatcher.subscriptions['bar'][wsd]['client-0'] == {None}
    assert WebSocketDispatcher.subscriptions['baz'][wsd]['client-0'] == {'callback-0'}

def test_update_subscriptions_with_multiple_channels(wsd):
    wsd.update_subscriptions(client='client-0', callback='callback-0', channels=['foo', 'baz'])
    assert WebSocketDispatcher.subscriptions['foo'][wsd]['client-0'] == {'callback-0'}
    assert WebSocketDispatcher.subscriptions['bar'][wsd]['client-0'] == {None}
    assert WebSocketDispatcher.subscriptions['baz'][wsd]['client-0'] == {'callback-0'}


@pytest.fixture
def trig(wsd):
    wsd.cached_queries['xxx']['yyy'] = (lambda *args, **kwargs: [args, kwargs], ('a', 'b'), {'c': 'd'})
    wsd.send = Mock()
    return wsd

def test_trigger(trig):
    trig.trigger(client='xxx', callback='yyy', trigger='zzz')
    trig.send.assert_called_with(client='xxx', callback='yyy', trigger='zzz', data=[('a', 'b'), {'c': 'd'}])

def test_trigger_without_id(trig):
    trig.trigger(client='xxx', callback='yyy')
    trig.send.assert_called_with(client='xxx', callback='yyy', trigger=None, data=[('a', 'b'), {'c': 'd'}])

def test_trigger_without_known_client(trig):
    trig.trigger(client='doesNotExist', callback='yyy')
    assert not trig.send.called

def test_trigger_without_known_callback(trig):
    trig.trigger(client='xxx', callback='doesNotExist')
    assert not trig.send.called


@pytest.fixture
def up(wsd):
    wsd.send = Mock()
    wsd.update_subscriptions = Mock()
    return wsd

@subscribes('foo')
def foosub():
    return 'e'

def test_update_triggers_client_and_callback(up):
    up.update_triggers('xxx', 'yyy', foosub, ('a', 'b'), {'c': 'd'}, 'e', 123)
    up.update_subscriptions.assert_called_with('xxx', 'yyy', ['foo'])
    assert up.cached_queries['xxx']['yyy'] == (foosub, ('a', 'b'), {'c': 'd'})
    assert not up.send.called

def test_update_triggers_client_no_callback(up):
    up.update_triggers('xxx', None, foosub, ('a', 'b'), {'c': 'd'}, 'e', 123)
    up.update_subscriptions.assert_called_with('xxx', None, ['foo'])
    assert up.cached_queries['xxx'][None] == (foosub, ('a', 'b'), {'c': 'd'})
    up.send.assert_called_with(trigger='subscribe', client='xxx', data='e', _time=123)

def test_update_triggers_no_client(up):
    for callback in [None, 'yyy']:
        up.update_triggers(None, 'yyy', foosub, ('a', 'b'), {'c': 'd'}, 'e', 123)
        assert not up.update_subscriptions.called
        assert 'yyy' not in up.cached_queries[None]
        assert not up.send.called

def test_update_triggers_with_error(up):
    up.update_triggers('xxx', None, foosub, ('a', 'b'), {'c': 'd'}, up.ERROR, 123)
    up.update_subscriptions.assert_called_with('xxx', None, ['foo'])
    assert up.cached_queries['xxx'][None] == (foosub, ('a', 'b'), {'c': 'd'})
    assert not up.send.called


@pytest.fixture
def act(wsd, monkeypatch):
    wsd.unsubscribe = Mock()
    monkeypatch.setattr(log, 'warn', Mock())
    return wsd

def test_unsubscribe_action(act):
    act.unsubscribe = Mock()
    act.internal_action('unsubscribe', 'xxx', 'yyy')
    act.unsubscribe.assert_called_with('xxx')
    assert not log.warn.called

def test_unknown_action(act):
    act.internal_action('does_not_exist', 'xxx', 'yyy')
    assert not act.unsubscribe.called
    assert log.warn.called

def test_no_action(act):
    act.internal_action(None, 'xxx', 'yyy')
    assert not act.unsubscribe.called
    assert not log.warn.called


@pytest.fixture
def receiver(wsd, monkeypatch):
    monkeypatch.setattr(log, 'error', Mock())
    monkeypatch.setattr(responder, 'defer', Mock())
    wsd.send = Mock()
    return wsd

Message = namedtuple('Message', ['data'])

def test_received_message(receiver):
    receiver.received_message(Message('{}'))
    responder.defer.assert_called_with(ANY, {})
    assert not receiver.send.called
    assert not log.error.called

def test_received_invalid_message(receiver):
    receiver.received_message(Message('not valid json'))
    assert not responder.defer.called
    receiver.send.assert_called_with(error=ANY)
    assert log.error.called

def test_received_non_dict(receiver):
    receiver.received_message(Message('"valid json but not a dict"'))
    assert not responder.defer.called
    receiver.send.assert_called_with(error=ANY)
    assert log.error.called


@pytest.fixture
def handler(wsd, service_patcher, monkeypatch):
    service_patcher('foo', {
        'bar': Mock(return_value='baz'),
        'err': Mock(side_effect=Exception)
    })
    monkeypatch.setattr(log, 'error', Mock())
    monkeypatch.setattr(threadlocal, 'reset', Mock())
    wsd.send = Mock()
    wsd.internal_action = Mock()
    wsd.update_triggers = Mock()
    return wsd

def test_handle_message_with_callback(handler):
    message = {
        'method': 'foo.bar',
        'params': 'baf',
        'callback': 'xxx'
    }
    handler.handle_message(message)
    threadlocal.reset.assert_called_with(websocket=handler, message=message, username=handler.username)
    handler.internal_action.assert_called_with(None, None, 'xxx')
    handler.update_triggers.assert_called_with(None, 'xxx', services.foo.bar, ['baf'], {}, 'baz', ANY)
    handler.send.assert_called_with(data='baz', callback='xxx', client=None, _time=ANY)
    assert not log.error.called

def test_handle_method_with_client(handler):
    message = {
        'method': 'foo.bar',
        'params': {'baf': 1},
        'client': 'xxx'
    }
    handler.handle_message(message)
    threadlocal.reset.assert_called_with(websocket=handler, message=message, username=handler.username)
    handler.internal_action.assert_called_with(None, 'xxx', None)
    handler.update_triggers.assert_called_with('xxx', None, services.foo.bar, [], {'baf': 1}, 'baz', ANY)
    assert not handler.send.called
    assert not log.error.called

def test_handle_message_client_error(handler):
    message = {'method': 'foo.err', 'client': 'xxx'}
    handler.handle_message(message)
    threadlocal.reset.assert_called_with(websocket=handler, message=message, username=handler.username)
    handler.internal_action.assert_called_with(None, 'xxx', None)
    handler.update_triggers.assert_called_with('xxx', None, services.foo.err, [], {}, handler.ERROR, ANY)
    assert log.error.called
    handler.send.assert_called_with(error=ANY, client='xxx', callback=None)
    assert handler.send.call_count == 1

def test_handle_message_callback_error(handler):
    message = {'method': 'foo.err', 'callback': 'xxx'}
    handler.handle_message(message)
    threadlocal.reset.assert_called_with(websocket=handler, message=message, username=handler.username)
    handler.internal_action.assert_called_with(None, None, 'xxx')
    handler.update_triggers.assert_called_with(None, 'xxx', services.foo.err, [], {}, handler.ERROR, ANY)
    assert log.error.called
    handler.send.assert_called_with(error=ANY, callback='xxx', client=None)
    assert handler.send.call_count == 1
