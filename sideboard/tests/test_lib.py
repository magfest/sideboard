from __future__ import unicode_literals
import json
from time import sleep
from itertools import count
from unittest import TestCase
from datetime import datetime, date
from collections.abc import Sequence, Set
from threading import current_thread, Thread

import six
import pytest
import cherrypy
from mock import Mock

from sideboard.lib._services import _Services
from sideboard.websockets import local_broadcast, local_subscriptions, local_broadcaster
from sideboard.lib import Model, serializer, ajax, is_listy, log, notify, locally_subscribes, cached_property, request_cached_property, threadlocal, register_authenticator, restricted, all_restricted, RWGuard


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

    def test_method_whitelisting(self):
        """
        When __all__ is defined for a service, we should raise an exception if
        a client calls a method whose name is not inclueded in __all__.
        """
        self.__all__ = ['bar']
        self.bar = self.baz = lambda: 'Hello World'
        self.services.register(self, 'foo')
        assert 'Hello World' == self.services.foo.bar()
        with pytest.raises(AssertionError):
            self.services.foo.baz()


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
        model = Model(data, 'test', {'bar', 'baf', 'fizz'}, {
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


class TestSerializer(TestCase):
    class Foo(object):
        def __init__(self, x):
            self.x = x

    class Bar(Foo):
        pass

    def setUp(self):
        self.addCleanup(setattr, serializer, '_registry', serializer._registry.copy())

    def test_date(self):
        d = date(2001, 2, 3)
        assert '"2001-02-03"' == json.dumps(d, cls=serializer)

    def test_datetime(self):
        dt = datetime(2001, 2, 3, 4, 5, 6)
        assert '"{}"'.format(dt.strftime(serializer._datetime_format)) == json.dumps(dt, cls=serializer)

    def test_set(self):
        st = set(['ya', 'ba', 'da', 'ba', 'da', 'ba', 'doo'])
        assert '["ba", "da", "doo", "ya"]' == json.dumps(st, cls=serializer)

    def test_duplicate_registration(self):
        pytest.raises(Exception, serializer.register, datetime, lambda dt: None)

    def test_new_type(self):
        serializer.register(self.Foo, lambda foo: foo.x)
        assert '5' == json.dumps(self.Foo(5), cls=serializer)
        assert '6' == json.dumps(self.Foo(6), cls=serializer)

    def test_new_type_subclass(self):
        serializer.register(self.Foo, lambda foo: 'Hello World!')
        serializer.register(self.Bar, lambda bar: 'Hello Kitty!')
        assert '"Hello World!"' == json.dumps(self.Foo(5), cls=serializer)
        assert '"Hello Kitty!"' == json.dumps(self.Bar(6), cls=serializer)

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


class TestIsListy(TestCase):
    """
    We test all sequence types, set types, and mapping types listed at
    http://docs.python.org/2/library/stdtypes.html plus a few example
    user-defined collections subclasses.
    """

    def test_sized_builtin(self):
        sized = [(), (1,), [], [1], set(), set([1]), frozenset(), frozenset([1]),
                 bytearray(), bytearray(1)]
        if six.PY2:
            sized.extend([xrange(0), xrange(2), buffer(''), buffer('x')])
        for x in sized:
            assert is_listy(x)

    def test_excluded(self):
        assert not is_listy({})
        assert not is_listy('')
        assert not is_listy(b'')

    def test_unsized_builtin(self):
        assert not is_listy(iter([]))
        assert not is_listy(i for i in range(2))

    def test_user_defined_types(self):
        assert not is_listy(Model({}, 'test'))

        class AlwaysEmptySequence(Sequence):
            def __len__(self): return 0

            def __getitem__(self, i): return [][i]

        assert is_listy(AlwaysEmptySequence())

        class AlwaysEmptySet(Set):
            def __len__(self): return 0

            def __iter__(self): return iter([])

            def __contains__(self, x): return False

        assert is_listy(AlwaysEmptySet())

    def test_miscellaneous(self):
        class Foo(object):
            pass

        for x in [0, 1, False, True, Foo, object, object()]:
            assert not is_listy(x)


def test_double_mount(request):
    class Root(object):
        pass
    request.addfinalizer(lambda: cherrypy.tree.apps.pop('/test', None))
    cherrypy.tree.mount(Root(), '/test')
    pytest.raises(Exception, cherrypy.tree.mount, Root(), '/test')


def test_ajaz_serialization():
    class Root(object):
        @ajax
        def returns_date(self):
            return date(2001, 2, 3)
    assert '"2001-02-03"' == Root().returns_date()


def test_trace_logging():
    log.trace('normally this would be an error')


class TestLocallySubscribes(object):
    @pytest.fixture(autouse=True)
    def counter(self):
        _counter = count()

        @locally_subscribes('foo', 'bar')
        def counter():
            return next(_counter)

        yield counter
        local_subscriptions.clear()

    def test_basic(self, counter):
        local_broadcast(['foo', 'bar'])
        assert 1 == counter()  # was only called once even though it matched multiple channels

    def test_exception(self):
        errored = Mock(side_effect=ValueError)
        working = Mock()
        locally_subscribes('foo')(errored)
        locally_subscribes('foo')(working)
        local_broadcast('foo')
        assert errored.called and working.called  # exception didn't halt execution

    def test_notify_triggers_local_updates(self, monkeypatch):
        monkeypatch.setattr(local_broadcaster, 'defer', Mock())
        notify('foo')
        local_broadcaster.defer.assert_called_with(['foo'], trigger='manual', originating_client=None)


def test_cached_property():
    class Foo(object):
        @cached_property
        def bar(self):
            return 5

    foo = Foo()
    assert not hasattr(foo, '_cached_bar')
    assert 5 == foo.bar
    assert 5 == foo._cached_bar
    foo._cached_bar = 6
    assert 6 == foo.bar
    assert 5 == Foo().bar  # per-instance caching


def test_request_cached_property():
    class Foo(object):
        @request_cached_property
        def bar(self):
            return 5

    name = __name__ + '.bar'
    foo = Foo()
    assert threadlocal.get(name) is None
    assert 5 == foo.bar
    assert 5 == threadlocal.get(name)
    threadlocal.set(name, 6)
    assert 6 == foo.bar
    assert 6 == Foo().bar  # cache is shared between instances


class TestPluggableAuth(object):
    @pytest.fixture(scope='session', autouse=True)
    def mock_authenticator(self):
        register_authenticator('test', '/mock_login_page', lambda: 'uid' in cherrypy.session)

    @pytest.fixture(autouse=True)
    def mock_session(self, monkeypatch):
        monkeypatch.setattr(cherrypy, 'session', {}, raising=False)

    def mock_login(self):
        cherrypy.session['uid'] = 123

    def test_double_registration(self):
        pytest.raises(Exception, register_authenticator, 'test', 'already registered', lambda: 'this will not register due to an exception')

    def test_unknown_authenticator(self):
        pytest.raises(Exception, all_restricted, 'unknown_authenticator')

    def test_all_restricted(self):
        self.called = False

        @all_restricted('test')
        class AllRestricted(object):
            def index(inner_self):
                self.called = True

        with pytest.raises(cherrypy.HTTPRedirect) as exc:
            AllRestricted().index()
        assert not self.called and exc.value.args[0][0].endswith('/mock_login_page')

        self.mock_login()
        AllRestricted().index()
        assert self.called

    def test_restricted(self):
        self.called = False

        class SingleRestricted(object):
            @restricted('test')
            def index(inner_self):
                self.called = True

        with pytest.raises(cherrypy.HTTPRedirect) as exc:
            SingleRestricted().index()
        assert not self.called and exc.value.args[0][0].endswith('/mock_login_page')

        self.mock_login()
        SingleRestricted().index()
        assert self.called


class TestRWGuard(object):
    @pytest.fixture
    def guard(self, monkeypatch):
        guard = RWGuard()
        monkeypatch.setattr(guard.ready_for_writes, 'notify', Mock())
        monkeypatch.setattr(guard.ready_for_reads, 'notify_all', Mock())
        return guard

    def test_read_locked_tracking(self, guard):
        assert {} == guard.acquired_readers
        with guard.read_locked:
            assert {current_thread().ident: 1} == guard.acquired_readers
            with guard.read_locked:
                assert {current_thread().ident: 2} == guard.acquired_readers
            assert {current_thread().ident: 1} == guard.acquired_readers
        assert {} == guard.acquired_readers

    def test_write_locked_tracking(self, guard):
        assert {} == guard.acquired_writer
        with guard.write_locked:
            assert {current_thread().ident: 1} == guard.acquired_writer
            with guard.write_locked:
                assert {current_thread().ident: 2} == guard.acquired_writer
            assert {current_thread().ident: 1} == guard.acquired_writer
        assert {} == guard.acquired_writer

    def test_multi_read_locking_allowed(self, guard):
        guard.acquired_readers['mock-thread-ident'] = 1
        with guard.read_locked:
            pass

    def test_read_write_exclusion(self, guard):
        with guard.read_locked:
            with pytest.raises(AssertionError):
                with guard.write_locked:
                    pass

    def test_write_read_exclusion(self, guard):
        with guard.write_locked:
            with pytest.raises(Exception):
                with guard.read_locked:
                    pass

    def test_release_requires_acquisition(self, guard):
        pytest.raises(AssertionError, guard.release)

    def test_wake_readers(self, guard):
        with guard.read_locked:
            guard.waiting_writer_count = 1
        assert not guard.ready_for_reads.notify_all.called

        guard.waiting_writer_count = 0
        with guard.read_locked:
            pass
        assert guard.ready_for_reads.notify_all.called

    def test_wake_writers(self, guard):
        with guard.write_locked:
            guard.acquired_readers['mock-tid'] = 1
            guard.waiting_writer_count = 1
        assert not guard.ready_for_writes.notify.called

        guard.acquired_readers.clear()
        with guard.write_locked:
            guard.waiting_writer_count = 0
        assert not guard.ready_for_writes.notify.called

        with guard.write_locked:
            guard.waiting_writer_count = 1
        assert guard.ready_for_writes.notify.called

    def test_threading(self):
        guard = RWGuard()
        read, written = [False], [False]

        def reader():
            with guard.read_locked:
                read[0] = True

        def writer():
            with guard.write_locked:
                written[0] = True

        with guard.write_locked:
            Thread(target=reader).start()
            Thread(target=writer).start()
            sleep(0.1)
            assert not read[0] and not written[0]
        sleep(0.1)
        assert read[0] and written[0]

        read, written = [False], [False]
        with guard.read_locked:
            Thread(target=reader).start()
            Thread(target=writer).start()
            sleep(0.1)
            assert read[0] and not written[0]
        sleep(0.1)
        assert read[0] and written[0]
