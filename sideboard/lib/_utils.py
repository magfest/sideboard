from __future__ import unicode_literals
import json
from datetime import datetime, date

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
