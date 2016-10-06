from __future__ import unicode_literals
import os
import json
from functools import wraps
from datetime import datetime, date
from collections import Sized, Iterable, Mapping


def is_listy(x):
    """
    returns a boolean indicating whether the passed object is "listy",
    which we define as a sized iterable which is not a map or string
    """
    return isinstance(x, Sized) and isinstance(x, Iterable) and not isinstance(x, (Mapping, type(b''), type('')))


def listify(x):
    """
    returns a list version of x if x is a non-string iterable, otherwise
    returns a list with x as its only element
    """
    return list(x) if is_listy(x) else [x]


class serializer(json.JSONEncoder):
    """
    JSONEncoder subclass for plugins to register serializers for types.
    Plugins should not need to instantiate this class directly, but
    they are expected to call serializer.register() for new data types.
    """

    _registry = {}
    _datetime_format = '%Y-%m-%d %H:%M:%S.%f'

    def default(self, o):
        if type(o) in self._registry:
            preprocessor = self._registry[type(o)]
        else:
            for klass, preprocessor in self._registry.items():
                if isinstance(o, klass):
                    break
            else:
                raise json.JSONEncoder.default(self, o)

        return preprocessor(o)

    @classmethod
    def register(cls, type, preprocessor):
        """
        Associates a type with a preprocessor so that RPC handlers may
        pass non-builtin JSON types.  For example, Sideboard already
        does the equivalent of

        >>> serializer.register(datetime, lambda dt: dt.strftime('%Y-%m-%d %H:%M:%S.%f'))

        This method raises an exception if you try to register a
        preprocessor for a type which already has one.

        :param type: the type you are registering
        :param preprocessor: function which takes one argument which is
                             the value to serialize and returns a json-
                             serializable value
        """
        assert type not in cls._registry, '{} already has a preprocessor defined'.format(type)
        cls._registry[type] = preprocessor

serializer.register(date, lambda d: d.strftime('%Y-%m-%d'))
serializer.register(datetime, lambda dt: dt.strftime(serializer._datetime_format))
serializer.register(set, lambda s: sorted(list(s)))


def cached_property(func):
    """decorator for making readonly, memoized properties"""
    pname = "_" + func.__name__

    @property
    @wraps(func)
    def caching(self, *args, **kwargs):
        if not hasattr(self, pname):
            setattr(self, pname, func(self, *args, **kwargs))
        return getattr(self, pname)
    return caching


def request_cached_property(func):
    """
    Sometimes we want a property to be cached for the duration of a request,
    with concurrent requests each having their own cached version.  This does
    that via the threadlocal class, such that each HTTP request CherryPy serves
    and each RPC request served via websocket or JSON-RPC will have its own
    cached value, which is cleared and then re-generated on later requests.
    """
    from sideboard.lib import threadlocal
    name = func.__module__ + '.' + func.__name__

    @property
    @wraps(func)
    def with_caching(self):
        val = threadlocal.get(name)
        if val is None:
            val = func(self)
            threadlocal.set(name, val)
        return val
    return with_caching


class _class_property(property):
    def __get__(self, cls, owner):
        return self.fget.__get__(None, owner)()


def class_property(cls):
    """
    For whatever reason, the @property decorator isn't smart enough to recognize
    classmethods and behave differently on them than on instance methods.  This
    property may be used to create a class-level property, useful for singletons
    and other one-per-class properties.  Class properties are read-only.
    """
    return _class_property(classmethod(cls))


def entry_point(func):
    """
    Decorator used to define entry points for command-line scripts.  Sideboard
    ships with a "sep" (Sideboard Entry Point) command line script which can be
    used to call into any plugin-defined entry point after deleting sys.argv[0]
    so that the entry point name will be the first argument.  For example, if a
    plugin had this entry point:

        @entry_point
        def some_action():
            print(sys.argv)

    Then someone in a shell ran the command:

        sep some_action foo bar

    It would print:

        ['some_action', 'foo', 'bar']

    :param func: a function which takes no arguments; its name will be the name
                 of the command, and an exception is raised if a function with
                 the same name has already been registered as an entry point
    """
    assert func.__name__ not in _entry_points, 'An entry point named {} has already been implemented'.format(func.__name__)
    _entry_points[func.__name__] = func
    return func

_entry_points = {}
