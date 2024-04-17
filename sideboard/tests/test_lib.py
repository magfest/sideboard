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

from sideboard.lib import serializer, ajax, is_listy, log, cached_property, request_cached_property, threadlocal, register_authenticator, restricted, all_restricted, RWGuard


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


def test_ajaz_serialization():
    class Root(object):
        @ajax
        def returns_date(self):
            return date(2001, 2, 3)
    assert '"2001-02-03"' == Root().returns_date()


def test_trace_logging():
    log.trace('normally this would be an error')


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
