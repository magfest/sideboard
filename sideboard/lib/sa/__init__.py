from __future__ import unicode_literals
import re
import json
import uuid
import types
import inspect

import six
import sqlalchemy
from sqlalchemy import event
from sqlalchemy.ext import declarative
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Query, sessionmaker, configure_mappers
from sqlalchemy.types import TypeDecorator, String, DateTime, CHAR, Unicode

from sideboard.lib import log, config

__all__ = ['UUID', 'JSON', 'CoerceUTF8', 'declarative_base', 'SessionManager',
           'CrudException', 'crudable', 'crud_validation', 'text_length_validation', 'regex_validation']


def _camelcase_to_underscore(value):
    """ Converts camelCase string to underscore_separated (aka joined_lower).

    >>> _camelcase_to_underscore('fooBarBaz')
    'foo_bar_baz'
    >>> _camelcase_to_underscore('fooBarBazXYZ')
    'foo_bar_baz_xyz'
    """
    s1 = re.sub(r'(.)([A-Z][a-z]+)', r'\1_\2', value)
    return re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', s1).lower()


def _underscore_to_camelcase(value, cap_segment=None):
    """ Converts underscore_separated string (aka joined_lower) into camelCase string.

    >>> _underscore_to_camelcase('foo_bar_baz')
    'FooBarBaz'
    >>> _underscore_to_camelcase('foo_bar_baz', cap_segment=0)
    'FOOBarBaz'
    >>> _underscore_to_camelcase('foo_bar_baz', cap_segment=1)
    'FooBARBaz'
    >>> _underscore_to_camelcase('foo_bar_baz', cap_segment=1000)
    'FooBarBaz'
    """
    return "".join([s.title() if idx != cap_segment else s.upper() for idx, s in enumerate(value.split('_'))])


class CoerceUTF8(TypeDecorator):
    """
    Safely coerce Python bytestrings to Unicode
    before passing off to the database.
    """
    impl = Unicode

    def process_bind_param(self, value, dialect):
        if isinstance(value, type(b'')):
            value = value.decode('utf-8')
        return value


class UUID(TypeDecorator):
    """
    Platform-independent UUID type.
    Uses Postgresql's UUID type, otherwise uses
    CHAR(32), storing as stringified hex values.
    """
    impl = CHAR

    def load_dialect_impl(self, dialect):
        if dialect.name == 'postgresql':
            return dialect.type_descriptor(postgresql.UUID())
        else:
            return dialect.type_descriptor(CHAR(32))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        elif dialect.name == 'postgresql':
            return str(value)
        else:
            if not isinstance(value, uuid.UUID):
                return uuid.UUID(value).hex
            else:
                return value.hex

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        else:
            return str(uuid.UUID(value))


class JSON(TypeDecorator):
    impl = String

    def __init__(self, comparator=None):
        self.comparator = comparator
        super(JSON, self).__init__()

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        elif isinstance(value, six.string_types):
            return value
        else:
            return json.dumps(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return json.loads(str(value))

    def copy_value(self, value):
        if self.mutable:
            return json.loads(json.dumps(value))
        else:
            return value

    def compare_values(self, x, y):
        if self.comparator:
            return self.comparator(x, y)
        else:
            return x == y


try:
    from pytz import UTC
except ImportError:
    pass
else:
    class UTCDateTime(TypeDecorator):
        impl = DateTime

        def process_bind_param(self, value, engine):
            if value is not None:
                return value.astimezone(UTC).replace(tzinfo=None)

        def process_result_value(self, value, engine):
            if value is not None:
                return value.replace(tzinfo=UTC)

    __all__.append('UTCDateTime')


def check_constraint_naming_convention(constraint, table):
    """Creates a unique name for an unnamed CheckConstraint.

    The generated name is the SQL text of the CheckConstraint with
    non-alphanumeric, non-underscore operators converted to text, and all
    other non-alphanumeric, non-underscore substrings replaced by underscores.

    If the generated name is longer than 32 characters, a uuid5 based on the
    generated name will be returned instead.

    >>> check_constraint_naming_convention(CheckConstraint('failed_logins > 3'), Table('account', MetaData()))
    'failed_logins_gt_3'

    See: http://docs.sqlalchemy.org/en/latest/core/constraints.html#configuring-constraint-naming-conventions
    """
    # The text of the replacements doesn't matter, so long as it's unique
    replacements = [
        ('||/', 'cr'), ('<=', 'le'), ('>=', 'ge'), ('<>', 'nq'), ('!=', 'ne'),
        ('||', 'ct'), ('<<', 'ls'), ('>>', 'rs'), ('!!', 'fa'), ('|/', 'sr'),
        ('@>', 'cn'), ('<@', 'cb'), ('&&', 'an'), ('<', 'lt'), ('=', 'eq'),
        ('>', 'gt'), ('!', 'ex'), ('"', 'qt'), ('#', 'hs'), ('$', 'dl'),
        ('%', 'pc'), ('&', 'am'), ('\'', 'ap'), ('(', 'lpr'), (')', 'rpr'),
        ('*', 'as'), ('+', 'pl'), (',', 'cm'), ('-', 'da'), ('.', 'pd'),
        ('/', 'sl'), (':', 'co'), (';', 'sc'), ('?', 'qn'), ('@', 'at'),
        ('[', 'lbk'), ('\\', 'bs'), (']', 'rbk'), ('^', 'ca'), ('`', 'tk'),
        ('{', 'lbc'), ('|', 'pi'), ('}', 'rbc'), ('~', 'td')]

    constraint_name = str(constraint.sqltext).strip()
    for operator, text in replacements:
        constraint_name = constraint_name.replace(operator, text)

    constraint_name = re.sub('[\W\s]+', '_', constraint_name)
    if len(constraint_name) > 32:
        constraint_name = uuid.uuid5(uuid.NAMESPACE_OID, str(constraint_name)).hex
    return constraint_name


# SQLAlchemy doesn't expose its default constructor as a nicely importable
# function, so we grab it from the function defaults.
if six.PY2:
    _spec_args, _spec_varargs, _spec_kwargs, _spec_defaults = inspect.getargspec(declarative.declarative_base)
else:
    _declarative_spec = inspect.getfullargspec(declarative.declarative_base)
    _spec_args, _spec_defaults = _declarative_spec.args, _declarative_spec.defaults
declarative_base_constructor = dict(zip(reversed(_spec_args), reversed(_spec_defaults)))['constructor']


def declarative_base(*orig_args, **orig_kwargs):
    """
    Replacement for SQLAlchemy's declarative_base, which adds these features:
    1) This is a decorator.
    2) This allows your base class to set a constructor.
    3) This provides a default constructor which automatically sets defaults
       instead of waiting to do that until the object is committed.
    4) Automatically setting __tablename__ to snake-case.
    5) Automatic integration with the SessionManager class.
    """
    orig_args = list(orig_args)

    def _decorate_base_class(klass):

        class Mixed(klass, CrudMixin):
            def __init__(self, *args, **kwargs):
                """
                Variant on SQLAlchemy model __init__ which sets default values on
                initialization instead of immediately before the model is saved.
                """
                if '_model' in kwargs:
                    assert kwargs.pop('_model') == self.__class__.__name__
                declarative_base_constructor(self, *args, **kwargs)
                for attr, col in self.__table__.columns.items():
                    if attr not in kwargs and col.default:
                        self.__dict__.setdefault(attr, col.default.execute())

        orig_kwargs['cls'] = Mixed
        if 'name' not in orig_kwargs:
            orig_kwargs['name'] = klass.__name__
        if 'constructor' not in orig_kwargs:
            orig_kwargs['constructor'] = klass.__init__ if '__init__' in klass.__dict__ else Mixed.__init__

        Mixed = declarative.declarative_base(*orig_args, **orig_kwargs)
        Mixed.BaseClass = _SessionInitializer._base_classes[klass.__module__] = Mixed
        Mixed.__tablename__ = declarative.declared_attr(lambda cls: _camelcase_to_underscore(cls.__name__))
        return Mixed

    is_class_decorator = not orig_kwargs and \
            len(orig_args) == 1 and \
            inspect.isclass(orig_args[0]) and \
            not isinstance(orig_args[0], sqlalchemy.engine.Connectable)

    if is_class_decorator:
        return _decorate_base_class(orig_args.pop())
    else:
        return _decorate_base_class


class _SessionInitializer(type):
    _base_classes = {}

    def __new__(cls, name, bases, attrs):
        SessionClass = type.__new__(cls, name, bases, attrs)
        if hasattr(SessionClass, 'engine'):
            if not hasattr(SessionClass, 'BaseClass'):
                for module, bc in _SessionInitializer._base_classes.items():
                    if module == SessionClass.__module__:
                        SessionClass.BaseClass = bc
                        break
                else:
                    raise AssertionError('no BaseClass specified and @declarative_base was never invoked in {}'.format(SessionClass.__module__))
            if not hasattr(SessionClass, 'session_factory'):
                SessionClass.session_factory = sessionmaker(bind=SessionClass.engine, autoflush=False, autocommit=False,
                                                            query_cls=SessionClass.QuerySubclass)
            SessionClass.initialize_db()
            SessionClass.crud = make_crud_service(SessionClass)
        return SessionClass


@six.add_metaclass(_SessionInitializer)
class SessionManager(object):
    class SessionMixin(object):
        pass

    class QuerySubclass(Query):
        pass

    def __init__(self):
        self.session = self.session_factory()
        for name, val in self.SessionMixin.__dict__.items():
            if not name.startswith('__'):
                assert not hasattr(self.session, name) and hasattr(val, '__call__')
                setattr(self.session, name, types.MethodType(val, self.session))

    def __enter__(self):
        return self.session

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            if exc_type is None:
                self.session.commit()
        finally:
            self.session.close()

    def __del__(self):
        if self.session.transaction._connections:
            log.error('SessionManager went out of scope without underlying connection being closed; did you forget to use it as a context manager?')
            self.session.close()

    @classmethod
    def initialize_db(cls, drop=False, create=True):
        configure_mappers()
        cls.BaseClass.metadata.bind = cls.engine
        if drop:
            cls.BaseClass.metadata.drop_all(cls.engine, checkfirst=True)
        if create:
            cls.BaseClass.metadata.create_all(cls.engine, checkfirst=True)

    @classmethod
    def all_models(cls):
        return cls.BaseClass.__subclasses__()   # TODO: subclasses of subclasses; this needs to be recursive or something

    @classmethod
    def resolve_model(cls, name):
        if inspect.isclass(name) and issubclass(name, cls.BaseClass):
            return name

        subclasses = {ModelClass.__name__: ModelClass for ModelClass in cls.all_models()}
        permutations = [name, _underscore_to_camelcase(name), _underscore_to_camelcase(name, cap_segment=0)]
        for name in permutations:
            if name in subclasses:
                return subclasses[name]

            if name.lower().endswith('s'):
                singular = name.rstrip('sS')
                if singular in subclasses:
                    return subclasses[singular]

            if name.lower().endswith('ies'):
                singular = name[:-3] + 'y'
                if singular in subclasses:
                    return subclasses[singular]

        for name in permutations:
            if name in cls.BaseClass.metadata.tables:
                return cls.BaseClass.metadata.tables[name]

        raise ValueError('Unrecognized model: {}'.format(name))

if six.PY2:
    __all__ = [s.encode('ascii') for s in __all__]

from sideboard.lib.sa._crud import CrudMixin, make_crud_service, crudable, CrudException, crud_validation, text_length_validation, regex_validation
