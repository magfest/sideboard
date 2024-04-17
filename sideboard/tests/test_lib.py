from __future__ import unicode_literals
import json
from unittest import TestCase
from datetime import datetime, date

import pytest

from sideboard.lib import serializer


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
