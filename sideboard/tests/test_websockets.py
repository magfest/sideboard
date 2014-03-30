from __future__ import unicode_literals
import json
from uuid import uuid4
from time import sleep

import cherrypy

from sideboard.lib import subscribes, notifies
from sideboard.tests import SideboardServerTest


class TestWebsocketSubscriptions(SideboardServerTest):
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
        self.patch_config(1, 'ws_call_timeout')
        self.override('self', self)

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
        self.assertEqual(['hello'] * 4, self.echoes)

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
        self.assertEqual('hello', result['data'])
        self.assertNotIn('client', result)

        result = self.call(method='crud.echo', params='hello', client='ds123')
        self.assertEqual('ds123', result['client'])

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
            self.assertEqual({'client1', 'client2'},
                             {self.next()['client'], self.next()['client']})

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
    def setUp(self):
        SideboardServerTest.setUp(self)
        self.override('test')
        self.patch_config(1, 'ws_call_timeout')

    def fast(self):
        return 'fast'

    def slow(self):
        sleep(2)
        return 'slow'

    def test_fast(self):
        assert self.ws.call('test.fast') == 'fast'

    def test_slow(self):
        self.assertRaises(Exception, self.ws.call, 'test.slow')
