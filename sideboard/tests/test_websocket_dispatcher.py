from __future__ import unicode_literals
from threading import RLock
from collections import namedtuple

import pytest
from mock import Mock, ANY
from ws4py.websocket import WebSocket

from sideboard.lib import log, services, subscribes, threadlocal
from sideboard.websockets import WebSocketDispatcher, responder, threadlocal
from sideboard.tests import service_patcher
from sideboard.tests.test_websocket import ws

mock_session_data = {'username': 'mock_user', 'user_id': 'mock_id'}
mock_header_data = {'REMOTE_USER': 'mock_user', 'REMOTE_USER_ID': 'mock_id'}


def mock_wsd():
    wsd = Mock()
    wsd.is_closed = False
    return wsd


@pytest.fixture(autouse=True)
def cleanup():
    yield
    threadlocal.reset()
    WebSocketDispatcher.instances.clear()


@pytest.fixture
def wsd(monkeypatch):
    WebSocketDispatcher.instances.clear()
    monkeypatch.setattr(WebSocket, 'send', Mock())
    monkeypatch.setattr(WebSocket, 'closed', Mock())
    monkeypatch.setattr(WebSocketDispatcher, 'is_closed', False)
    monkeypatch.setattr(WebSocketDispatcher, 'check_authentication', lambda cls: mock_session_data)
    monkeypatch.setattr(WebSocketDispatcher, 'fetch_headers', lambda cls: mock_header_data)
    return WebSocketDispatcher(None)


@pytest.fixture
def ws1(): return mock_wsd()


@pytest.fixture
def ws2(): return mock_wsd()


@pytest.fixture
def ws3(): return mock_wsd()


@pytest.fixture
def ws4():
    class RaisesError:
        is_closed = False
        unsubscribe_all = Mock()
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


def test_instances(wsd):
    assert WebSocketDispatcher.instances == {wsd}
    wsd.closed('code', 'reason')
    assert WebSocketDispatcher.instances == set()


def test_get_all_subscribed(wsd, ws1, ws2, ws3, ws4):
    assert WebSocketDispatcher.get_all_subscribed() == {wsd, ws1, ws2, ws3, ws4}


class TestBroadcast(object):
    def test_basic_broadcast(self, ws1, ws2):
        WebSocketDispatcher.broadcast('bar', trigger='manual')
        ws1.trigger.assert_called_with(client='client-1', callback='callback-1', trigger='manual')
        assert not ws2.trigger.called
        assert not ws1.unsubscribe_all.called and not ws2.unsubscribe_all.called

    def test_broadcast_with_originating_client(self, ws1, ws2):
        WebSocketDispatcher.broadcast('foo', originating_client='client-1')
        assert ws2.trigger.called and not ws1.trigger.called

    def test_multi_broadcast(self, ws1, ws2, ws3, ws4):
        WebSocketDispatcher.broadcast(['foo', 'bar'])
        assert ws1.trigger.called and ws2.trigger.called and not ws3.trigger.called and not ws4.trigger.called

    def test_broadcast_error(self, ws4, monkeypatch):
        monkeypatch.setattr(log, 'warning', Mock())
        WebSocketDispatcher.broadcast('foo')
        assert not ws4.trigger.called and not log.warning.called
        WebSocketDispatcher.broadcast('baf')
        assert ws4.trigger.called and log.warning.called and not ws4.unsubscribe_all.called

    def test_broadcast_closed(self, ws1, ws2):
        ws1.is_closed = True
        WebSocketDispatcher.broadcast('foo')
        assert ws2.trigger.called and not ws1.trigger.called
        assert ws1.unsubscribe_all.called and not ws2.unsubscribe_all.called


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
    wsd.client_locks[client] = RLock()
    wsd.cached_queries[client] = {None: (Mock(), (), {}, {})}
    wsd.cached_fingerprints[client][None] = 'fingerprint'
    WebSocketDispatcher.subscriptions['foo'] = {wsd: {client: 'subscription'}}
    wsd.handle_message({'action': 'unsubscribe', 'client': client})
    for d in [wsd.client_locks, wsd.cached_queries, wsd.cached_fingerprints, WebSocketDispatcher.subscriptions['foo']]:
        assert client not in d


def test_multi_unsubscribe(wsd):
    client = ['client-1', 'client-2']
    wsd.client_locks = {'client-1': RLock(), 'client-2': RLock()}
    wsd.cached_fingerprints = {'client-1': 'fingerprint', 'client-2': 'fingerprint'}
    wsd.cached_queries = {'client-1': {None: (Mock(), (), {}, {})}, 'client-2': {None: (Mock(), (), {}, {})}}
    WebSocketDispatcher.subscriptions['foo'] = {wsd: {'client-1': 'subscription', 'client-2': 'subscription'}}
    wsd.handle_message({'action': 'unsubscribe', 'client': client})
    for d in [wsd.client_locks, wsd.cached_queries, wsd.cached_fingerprints, WebSocketDispatcher.subscriptions['foo']]:
        assert 'client-1' not in d
        assert 'client-2' not in d


def test_unsubscribe_all(wsd, subscriptions):
    assert wsd in WebSocketDispatcher.subscriptions['foo']
    assert wsd in WebSocketDispatcher.subscriptions['bar']
    sub1 = wsd.passthru_subscriptions['client-0'] = Mock()
    sub2 = wsd.passthru_subscriptions['client-x'] = Mock()

    wsd.unsubscribe_all()

    assert wsd not in WebSocketDispatcher.subscriptions['foo']
    assert wsd not in WebSocketDispatcher.subscriptions['bar']
    assert 'client-0' not in wsd.passthru_subscriptions and 'client-x' not in wsd.passthru_subscriptions
    assert sub1.unsubscribe.called and sub2.unsubscribe.called


def test_remote_unsubscribe(wsd, ws):
    ws.unsubscribe = Mock()
    ws._next_id = Mock(return_value='yyy')
    threadlocal.reset(websocket=wsd, message={'client': 'xxx'})
    wsd.cached_queries['xxx'] = {None: (ws.make_caller('remote.foo'), (), {}, {})}
    wsd.unsubscribe('xxx')
    ws.unsubscribe.assert_called_with('yyy')


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
    wsd.cached_queries['xxx']['yyy'] = (lambda *args, **kwargs: [args, kwargs], ('a', 'b'), {'c': 'd'}, {})
    wsd.send = Mock()
    return wsd


def increment():
    count = threadlocal.client_data.setdefault('count', 0)
    count += 1
    threadlocal.client_data['count'] = count
    return count


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


def test_trigger_with_client_data(wsd, trig, monkeypatch):
    client = 'client-1'
    monkeypatch.setitem(wsd.subscriptions['foo'][wsd], client, [None])
    monkeypatch.setitem(wsd.cached_fingerprints, client, {None: 'fingerprint'})
    monkeypatch.setitem(wsd.cached_queries, client, {None: (increment, (), {}, {'count': 7})})

    wsd.trigger(client=client, callback=None)
    wsd.send.assert_called_with(client=client, callback=None, trigger=None, data=8)


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
    assert up.cached_queries['xxx']['yyy'] == (foosub, ('a', 'b'), {'c': 'd'}, {})
    assert not up.send.called


def test_update_triggers_client_no_callback(up):
    up.update_triggers('xxx', None, foosub, ('a', 'b'), {'c': 'd'}, 'e', 123)
    up.update_subscriptions.assert_called_with('xxx', None, ['foo'])
    assert up.cached_queries['xxx'][None] == (foosub, ('a', 'b'), {'c': 'd'}, {})
    up.send.assert_called_with(trigger='subscribe', client='xxx', data='e', _time=123)


def test_update_triggers_no_client(up):
    for callback in [None, 'yyy']:
        up.update_triggers(None, 'yyy', foosub, ('a', 'b'), {'c': 'd'}, 'e', 123)
        assert not up.update_subscriptions.called
        assert 'yyy' not in up.cached_queries[None]
        assert not up.send.called


def test_update_triggers_with_error(up):
    up.update_triggers('xxx', None, foosub, ('a', 'b'), {'c': 'd'}, up.NO_RESPONSE, 123)
    up.update_subscriptions.assert_called_with('xxx', None, ['foo'])
    assert up.cached_queries['xxx'][None] == (foosub, ('a', 'b'), {'c': 'd'}, {})
    assert not up.send.called


@pytest.fixture
def act(wsd, monkeypatch):
    wsd.unsubscribe = Mock()
    monkeypatch.setattr(log, 'warning', Mock())
    return wsd


def test_unsubscribe_action(act):
    act.unsubscribe = Mock()
    act.internal_action('unsubscribe', 'xxx', 'yyy')
    act.unsubscribe.assert_called_with('xxx')
    assert not log.warning.called


def test_unknown_action(act):
    act.internal_action('does_not_exist', 'xxx', 'yyy')
    assert not act.unsubscribe.called
    assert log.warning.called


def test_no_action(act):
    act.internal_action(None, 'xxx', 'yyy')
    assert not act.unsubscribe.called
    assert not log.warning.called


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
def handler(ws, wsd, service_patcher, monkeypatch):
    service_patcher('remote', ws)
    service_patcher('foo', {
        'bar': Mock(return_value='baz'),
        'err': Mock(side_effect=Exception)
    })
    ws.subscribe = Mock()
    ws.call = Mock(return_value=12345)
    monkeypatch.setattr(log, 'error', Mock())
    monkeypatch.setattr(threadlocal, 'reset', Mock(side_effect=threadlocal.reset))
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
    threadlocal.reset.assert_called_with(websocket=handler, message=message, headers=mock_header_data,
                                         **mock_session_data)
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
    threadlocal.reset.assert_called_with(websocket=handler, message=message, headers=mock_header_data,
                                         **mock_session_data)
    handler.internal_action.assert_called_with(None, 'xxx', None)
    handler.update_triggers.assert_called_with('xxx', None, services.foo.bar, [], {'baf': 1}, 'baz', ANY)
    assert not handler.send.called
    assert not log.error.called


def test_handle_message_client_error(handler):
    message = {'method': 'foo.err', 'client': 'xxx'}
    handler.handle_message(message)
    threadlocal.reset.assert_called_with(websocket=handler, message=message, headers=mock_header_data,
                                         **mock_session_data)
    handler.internal_action.assert_called_with(None, 'xxx', None)
    handler.update_triggers.assert_called_with('xxx', None, services.foo.err, [], {}, handler.NO_RESPONSE, ANY)
    assert log.error.called
    handler.send.assert_called_with(error=ANY, client='xxx', callback=None)
    assert handler.send.call_count == 1


def test_handle_message_callback_error(handler):
    message = {'method': 'foo.err', 'callback': 'xxx'}
    handler.handle_message(message)
    threadlocal.reset.assert_called_with(websocket=handler, message=message, headers=mock_header_data,
                                         **mock_session_data)
    handler.internal_action.assert_called_with(None, None, 'xxx')
    handler.update_triggers.assert_called_with(None, 'xxx', services.foo.err, [], {}, handler.NO_RESPONSE, ANY)
    assert log.error.called
    handler.send.assert_called_with(error=ANY, callback='xxx', client=None)
    assert handler.send.call_count == 1


def test_handle_message_remote_call(handler, ws):
    message = {'method': 'remote.method', 'callback': 'xxx', 'params': [1, 2]}
    handler.handle_message(message)
    ws.call.assert_called_with('remote.method', 1, 2)
    assert not ws.subscribe.called
    handler.send.assert_called_with(callback='xxx', data=12345, client=None, _time=ANY)


def test_handle_message_remote_subscribe(handler, ws):
    message = {'method': 'remote.method', 'client': 'xxx', 'params': [1, 2]}
    handler.handle_message(message)
    ws.subscribe.assert_called_with(ANY, 'remote.method', 1, 2)
    assert not ws.call.called
    assert not handler.send.called


def test_skip_send_if_closed(monkeypatch, wsd):
    wsd.send()
    monkeypatch.setattr(WebSocketDispatcher, 'is_closed', True)
    wsd.send()
    assert WebSocket.send.call_count == 1


def test_explicit_call_resets_cache(service_patcher, wsd):
    service_patcher('foo', {
        'bar': lambda: 'Hello World'
    })
    message = {'method': 'foo.bar', 'client': 'client-1', 'callback': 'callback-2'}
    wsd.handle_message(message)
    assert 'callback-2' in wsd.cached_fingerprints['client-1']
    assert WebSocket.send.call_count == 1
    wsd.handle_message(message)
    assert WebSocket.send.call_count == 2
