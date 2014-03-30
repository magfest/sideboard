from __future__ import unicode_literals
import json
from logging import WARNING
from itertools import count
from unittest import TestCase
from datetime import datetime, date
from collections import Sequence, Set

import cherrypy

from sideboard.lib._services import _Services
from sideboard.tests import SideboardTest, SideboardServerTest
from sideboard.lib import Model, WebSocket, subscribes, notifies, serializer, render_with_templates, ajax, threadlocal, is_listy


class TestServices(TestCase):
    def setUp(self):
        self.services = _Services()

    def test_service_registration(self):
        self.services.register(self, 'foo')
        self.services.foo.assertTrue(True)

    def test_service_double_registration(self):
        self.services.register(self, 'foo')
        self.services.register(self, 'bar')
        self.assertRaises(AssertionError, self.services.register, self, 'foo')

    def test_service_preregistration_getattr(self):
        foo = self.services.foo
        self.services.register(self, 'foo')
        foo.assertTrue(True)


class TestModel(TestCase):
    def assert_model(self, data, unpromoted=None):
        model = Model(data, 'test', unpromoted)
        self.assertEqual('some_uuid', model.id)
        self.assertEqual('some_uuid', model['id'])
        self.assertEqual(5, model.foo)
        self.assertEqual(5, model['foo'])
        self.assertEqual({'baz': 'baf'}, model.bar)
        self.assertEqual({'baz': 'baf'}, model['bar'])
    
    def test_missing_key(self):
        model = Model({}, 'test')
        self.assertIs(None, model.does_not_exist)
    
    def test_id_unsettable(self):
        model = Model({'id': 'some_uuid'}, 'test')
        model.id = 'some_uuid'
        model['id'] = 'some_uuid'
        self.assertEqual(model.id, 'some_uuid')
        with self.assertRaises(Exception):
            model.id = 'another_uuid'
        with self.assertRaises(Exception):
            model['id'] = 'another_uuid'
    
    def test_extra_data_only(self):
        d = {
            'id': 'some_uuid',
            'extra_data': {
                'test_foo': 5,
                'test_bar': {'baz': 'baf'}
            }
        }
        for data in [d, dict(d, test_data={})]:
            self.assert_model(data)

        model = Model(d, 'test')
        model.fizz = 'buzz'
        model['buzz'] = 'fizz'
        self.assertEqual('fizz', model._data['extra_data']['test_buzz'])
        self.assertEqual('buzz', model._data['extra_data']['test_fizz'])

    def test_project_data(self):
        d = {
            'id': 'some_uuid',
            'test_data': {
                'foo': 5,
                'bar': {'baz': 'baf'}
            }
        }
        for data in [d, dict(d, extra_data={})]:
            self.assert_model(data)
            model = Model(data, 'test')
            model.fizz = 'buzz'
            model['buzz'] = 'fizz'
            self.assertEqual('fizz', model._data['test_data']['buzz'])
            self.assertEqual('buzz', model._data['test_data']['fizz'])

    def test_both_data(self):
        data = {
            'id': 'some_uuid',
            'extra_data': {
                'test_foo': 5
            },
            'test_data': {
                'bar': {'baz': 'baf'}
            }
        }
        self.assert_model(data)
        model = Model(data, 'test')
        model.fizz = 'buzz'
        model['buzz'] = 'fizz'
        self.assertEqual('fizz', model._data['test_data']['buzz'])
        self.assertEqual('buzz', model._data['test_data']['fizz'])
        model.foo = 6
        model.bar = {'baf': 'baz'}
        self.assertEqual({}, model._data['extra_data'])
        self.assertEqual(6, model.foo)
        self.assertEqual({'baf': 'baz'}, model['bar'])
        self.assertEqual(6, model._data['test_data']['foo'])
        self.assertEqual({'baf': 'baz'}, model._data['test_data']['bar'])

    def test_unpromoted_prepromotion(self):
        data = {
            'id': 'some_uuid',
            'extra_data': {
                'foo': 5,
                'test_bar': {'baz': 'baf'}
            }
        }
        self.assert_model(data, {'foo'})
        model = Model(data, 'test', unpromoted={'foo'})
        model.foo = 6
        self.assertEqual(6, model.foo)
        self.assertNotIn('foo', model._data)
        self.assertEqual(6, model._data['extra_data']['foo'])

    def test_unpromoted_postpromotion(self):
        data = {
            'id': 'some_uuid',
            'foo': 5,
            'extra_data': {
                'test_bar': {'baz': 'baf'}
            }
        }
        self.assert_model(data, {'foo'})
        model = Model(data, 'test', unpromoted={'foo'})
        model.foo = 6
        self.assertEqual(6, model.foo)
        self.assertEqual(6, model._data['foo'])
        self.assertNotIn('foo', model._data['extra_data'])

    def test_unpromoted_not_present(self):
        data = {'id': 'some_uuid'}
        model = Model(data, 'test', unpromoted={'foo'})
        self.assertIs(None, model.foo)
        model.foo = 'bar'
        self.assertEqual('bar', model.foo)
        self.assertNotIn('foo', model._data)
        self.assertEqual('bar', model._data['extra_data']['foo'])

    def test_subclass(self):
        self.assertRaises(Exception, Model, {})

        class TestModel(Model):
            _prefix = 'test'
            _unpromoted = {'foo'}
            _defaults = {'baz': 'baf'}

        data = {'id': 'some_uuid'}
        model = TestModel(data)
        self.assertIs(None, model.foo)
        model.foo = 'bar'
        self.assertEqual('baf', model.baz)
        self.assertEqual('bar', model.foo)
        self.assertNotIn('foo', model._data)
        self.assertEqual('bar', model._data['extra_data']['foo'])
    
    def test_defaults(self):
        data = {
            'extra_data': {
                'test_foo': -1,
                'bar': -2
            },
            'test_data': {
                'baz': -3
            },
            'baf': -4
        }
        model = Model(data, 'test', {'bar','baf','fizz'}, {
            'foo': 1,
            'bar': 2,
            'baz': 3,
            'baf': 4,
            'fizz': 5,
            'buzz': 6
        })
        self.assertEqual(model.foo, -1)
        self.assertEqual(model.bar, -2)
        self.assertEqual(model.baz, -3)
        self.assertEqual(model.baf, -4)
        self.assertEqual(model.fizz, 5)
        self.assertEqual(model.buzz, 6)
        model.foo, model.bar, model.baz, model.baf = range(11, 15)
        self.assertEqual(model.foo, 11)
        self.assertEqual(model.bar, 12)
        self.assertEqual(model.baz, 13)
        self.assertEqual(model.baf, 14)
        self.assertEqual(model.fizz, 5)
        self.assertEqual(model.buzz, 6)
    
    def test_to_dict(self):
        data = {
            'id': 'some_uuid',
            'extra_data': {
                'test_foo': 5,
                'fizz': 'buzz',
                'spam': 'eggs'
            },
            'test_data': {'bar': 'baz'}
        }
        model = Model(data, 'test', {'fizz'})
        serialized = {
            'id': 'some_uuid',
            'foo': 5,
            'bar': 'baz',
            'fizz': 'buzz',
            'extra_data': {'spam': 'eggs'}
        }
        self.assertEqual(model.to_dict(), serialized)
        serialized.pop('extra_data')
        self.assertEqual(dict(model), serialized)
    
    def test_query(self):
        model = Model({'_model': 'Test', 'id': 'some_uuid'}, 'test')
        self.assertEqual(model.query, {
            '_model': 'Test',
            'field': 'id',
            'value': 'some_uuid'
        })
        for data in [{}, {'_model': 'Test'}, {'id': 'some_uuid'}]:
            with self.assertRaises(Exception):
                Model(data, 'test').query
    
    def test_dirty(self):
        data = {
            'id': 'some_uuid',
            'spam': 'eggs',
            'extra_data': {
                'test_foo': 5
            },
            'test_data': {
                'bar': {'baz': 'baf'}
            }
        }
        self.assertEqual(Model(data, 'test').dirty, {})
        
        model = Model(data, 'test')
        model.spam = 'nee'
        self.assertEqual(model.dirty, {'spam': 'nee'})
        
        model = Model(data, 'test')
        model.foo = 6
        self.assertEqual(model.dirty, {'extra_data': {}, 'test_data': {'foo': 6, 'bar': {'baz': 'baf'}}})
        
        model = Model(data, 'test')
        model.bar = {'fizz': 'buzz'}
        self.assertEqual(model.dirty, {'test_data': {'bar': {'fizz': 'buzz'}}})
        
        model = Model(data, 'test')
        model.bar['baz'] = 'zab'
        self.assertEqual(model.dirty, {'test_data': {'bar': {'baz': 'zab'}}})
        
        model = Model(data, 'test')
        model.foo = 6
        model.bar = 'baz'
        model.spam = 'nee'
        model.fizz = 'buzz'
        self.assertEqual(model.dirty, {
            'spam': 'nee',
            'test_data': {
                'foo': 6,
                'bar': 'baz',
                'fizz': 'buzz'
            },
            'extra_data': {}
        })
        
        model = Model({}, 'test')
        model.foo = 'bar'
        self.assertEqual(model.dirty, {'extra_data': {'test_foo': 'bar'}})


class TestWebSocket(SideboardServerTest):
    def callee(self):
        return 'Hello World!'

    @subscribes('test')
    def subscribee(self):
        return next(self.counter)

    @notifies('test')
    def notifier(self):
        return 'updated'

    def setUp(self):
        self.results = []
        self.counter = count()
        self.override('self', self)
        self.ws = WebSocket(connect_immediately=True, max_wait=5)
        assert self.ws.connected

    def test_call_success(self):
        self.assertEqual('Hello World!', self.ws.call('self.callee'))

    def test_call_invalid(self):
        self.assertRaises(Exception, self.ws.call, 'self.does_not_exist')

    def test_call_exception(self):
        message = 'some exception message'
        try:
            self.ws.call('self.fail', message)
        except Exception as e:
            self.assertIn(message, str(e))
        else:
            self.fail('no exception raised')

    def test_call_on_closed(self):
        self.ws.ws.close()
        self.assertRaises(Exception, self.ws.call, 'self.callee')

    def test_subscribe_success(self):
        self.ws.subscribe(self.results.append, 'self.subscribee')
        self.wait_for_eq([0], lambda: self.results)
        self.notifier()
        self.wait_for_eq([0, 1], lambda: self.results)

    def test_subscribe_reconnect_triggering(self):
        self.ws.subscribe(self.results.append, 'self.subscribee')
        self.wait_for_eq([0], lambda: self.results)
        self.ws.ws.close()
        self.wait_for_eq([0, 1], lambda: self.results)

    def test_subscribe_initial_failure(self):
        self.ws.ws.close()
        with self.assert_logged(WARNING, 'initial subscription to self.subscribee at .* failed, will retry on reconnect'):
            self.ws.subscribe(self.results.append, 'self.subscribee')
        self.wait_for_eq([0], lambda: self.results)

    def test_subscribe_client(self):
        client = self.ws.subscribe(self.results.append, 'self.subscribee')
        self.wait_for_eq([0], lambda: self.results)
        self.ws._send(method='self.notifier', client=client)
        self.wait_for_eq([0, 'updated'], lambda: self.results)
        self.assertRaises(Exception, self.wait_for_ne, [0, 'updated'], lambda: self.results)


class TestSerializer(SideboardTest):
    class Foo(object):
        def __init__(self, x):
            self.x = x
    
    class Bar(Foo): pass
    
    def setUp(self):
        self.addCleanup(setattr, serializer, '_registry', serializer._registry.copy())

    def test_date(self):
        d = date(2001, 2, 3)
        self.assertEqual('"2001-02-03"', json.dumps(d, cls=serializer))
    
    def test_datetime(self):
        dt = datetime(2001, 2, 3, 4, 5, 6)
        self.assertEqual('"' + dt.strftime(serializer._datetime_format) + '"', json.dumps(dt, cls=serializer))
    
    def test_duplicate_registration(self):
        self.assertRaises(Exception, serializer.register, datetime, lambda dt: None)
    
    def test_new_type(self):
        serializer.register(self.Foo, lambda foo: foo.x)
        self.assertEqual('5', json.dumps(self.Foo(5), cls=serializer))
        self.assertEqual('6', json.dumps(self.Foo(6), cls=serializer))
    
    def test_new_type_subclass(self):
        serializer.register(self.Foo, lambda foo: 'Hello World!')
        serializer.register(self.Bar, lambda bar: 'Hello Kitty!')
        self.assertEqual('"Hello World!"', json.dumps(self.Foo(5), cls=serializer))
        self.assertEqual('"Hello Kitty!"', json.dumps(self.Bar(6), cls=serializer))

    """
    Here are some cases which are currently undefined (and I'm okay with it):
    
    class Foo(object): pass
    class Bar(object): pass
    class Baz(Foo, Bar): pass
    class Baf(Foo): pass
    class Bax(Foo): pass
    
    serializer.register(Foo, foo_preprocessor)
    serializer.register(Bar, bar_preprocessor)
    serializer.register(Baf, baf_preprocessor)
    
    json.dumps(Baz(), cls=serializer)   # undefined which function will be used
    json.dumps(Bax(), cls=serializer)   # undefined which function will be used
    """


class TestServerHelpers(SideboardServerTest):
    rsess_username = 'helper'
    
    @classmethod
    def setUpClass(cls):
        @render_with_templates()
        class Root(object):
            def index(self):
                return threadlocal.get('username')
            
            @ajax
            def dynamic(self, hello='world', goodbye='world'):
                return {'hello': hello, 'goodbye': goodbye}
        
        cherrypy.tree.mount(Root(), '/helper')
        super(TestServerHelpers, cls).setUpClass()
    
    def test_url(self):
        self.assertEqual('http://localhost:8282/foo', self.url('/foo'))
        self.assertEqual('http://localhost:8282/foo?bar=baz', self.url('/foo?bar=baz'))
        self.assertEqual('http://localhost:8282/foo?bar=baz', self.url('/foo', bar='baz'))
        try:
            self.assertEqual('http://localhost:8282/foo?bar=baz&baf=bax', self.url('/foo?bar=baz', baf='bax'))
        except:
            self.assertEqual('http://localhost:8282/foo?baf=bax&bar=baz', self.url('/foo?bar=baz', baf='bax'))

    def test_get(self):
        self.assertEqual(self.rsess_username, self.get('/helper'))

    def test_get_json(self):
        self.assertEqual({'hello': 'world', 'goodbye': 'world'}, self.get_json('/helper/dynamic'))
        self.assertEqual({'hello': 'kitty', 'goodbye': 'world'}, self.get_json('/helper/dynamic?hello=kitty'))
        self.assertEqual({'hello': 'kitty', 'goodbye': 'world'}, self.get_json('/helper/dynamic', hello='kitty'))
        self.assertEqual({'hello': 'kitty', 'goodbye': 'cruel world'}, self.get_json('/helper/dynamic?hello=kitty', goodbye='cruel world'))


class TestIsListy(SideboardTest):
    """
    We test all sequence types, set types, and mapping types listed at
    http://docs.python.org/2/library/stdtypes.html plus a few example
    user-defined collections subclasses.
    """

    def test_sized_builtin(self):
        for x in [(), (1,), [], [1], set(), set([1]), frozenset(), frozenset([1]),
                  xrange(0), xrange(2), bytearray(), bytearray(1), buffer(''), buffer('x')]:
            self.assertTrue(is_listy(x))

    def test_excluded(self):
        self.assertFalse(is_listy({}))
        self.assertFalse(is_listy(''))
        self.assertFalse(is_listy(b''))

    def test_unsized_builtin(self):
        self.assertFalse(is_listy(iter([])))
        self.assertFalse(is_listy(i for i in range(2)))

    def test_user_defined_types(self):
        self.assertFalse(is_listy(Model({}, 'test')))

        class AlwaysEmptySequence(Sequence):
            def __len__(self): return 0
            def __getitem__(self, i): return [][i]

        self.assertTrue(is_listy(AlwaysEmptySequence()))

        class AlwaysEmptySet(Set):
            def __len__(self): return 0
            def __iter__(self): return iter([])
            def __contains__(self, x): return False

        self.assertTrue(is_listy(AlwaysEmptySet()))

    def test_miscellaneous(self):
        class Foo(object): pass
        
        for x in [0, 1, False, True, Foo, object, object()]:
            self.assertFalse(is_listy(x))


class TestDoubleMounting(SideboardTest):
    def test_double_mount(self):
        class Root(object): pass
        
        self.addCleanup(cherrypy.tree.apps.pop, '/test', None)
        cherrypy.tree.mount(Root(), '/test')
        self.assertRaises(Exception, cherrypy.tree.mount, Root(), '/test')


class TestAjaxSerialization(SideboardTest):
    def test_custom_serialization(self):
        class Root(object):
            @ajax
            def returns_date(self):
                return date(2001, 2, 3)
        
        self.assertEqual('"2001-02-03"', Root().returns_date())
