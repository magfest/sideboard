from __future__ import unicode_literals
import uuid
import shutil
from datetime import datetime

import pytest

import sqlalchemy
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.pool import NullPool
from sqlalchemy.orm import relationship
from sqlalchemy.types import Boolean, Integer, UnicodeText
from sqlalchemy.schema import Column, CheckConstraint, ForeignKey, MetaData, Table, UniqueConstraint
from sqlalchemy.sql import case

from sideboard.lib import log, listify
from sideboard.tests import patch_session
from sideboard.lib.sa._crud import normalize_query, collect_ancestor_classes
from sideboard.lib.sa import check_constraint_naming_convention, crudable, declarative_base, \
    regex_validation, text_length_validation, CrudException, JSON, SessionManager, UUID


@declarative_base
class Base(object):
    id = Column(UUID(), primary_key=True, default=uuid.uuid4)


@crudable(update=['tags', 'employees'])
@text_length_validation('name', 1, 100)
class User(Base):
    name = Column(UnicodeText(), nullable=False, unique=True)
    tags = relationship('Tag', cascade='all,delete,delete-orphan', backref='user', passive_deletes=True)
    employees = relationship('Account', cascade='all,delete,delete-orphan', passive_deletes=True)


@crudable()
class Boss(Base):
    name = Column(UnicodeText(), nullable=False, unique=True)


@crudable(no_update=['username'])
@regex_validation('username', r'[0-9a-zA-z]+', 'Usernames may only contain alphanumeric characters')
class Account(Base):
    user_id = Column(UUID(), ForeignKey('user.id', ondelete='RESTRICT'), nullable=False)
    user = relationship(User, overlaps="employees")
    username = Column(UnicodeText(), nullable=False, unique=True)
    password = Column(UnicodeText(), nullable=False)

    boss_id = Column(UUID(), ForeignKey('boss.id', ondelete='SET NULL'), nullable=True)
    boss = relationship(Boss, backref='employees')


@crudable(no_update=['name', 'user_id'])
class Tag(Base):
    __table_args__ = (UniqueConstraint('user_id', 'name'),)

    name = Column(UnicodeText(), nullable=False)
    user_id = Column(UUID(), ForeignKey('user.id', ondelete='CASCADE'), nullable=False)


@text_length_validation('mixed_in_attr', 1, 10)
class CrudableMixin(object):
    """Test that validation decorators on Mixins work as expected"""
    mixed_in_attr = Column(UnicodeText(), default='default string')
    extra_data = Column(JSON(), default={}, server_default='{}')


@crudable(
    data_spec={
        'date_attr': {
            'date_format': 'Y-M-d',
            'desc': 'this is a manual desc'
        },
        'overridden_desc': {
            'desc': 'this is an overridden desc',
            'validators': {
                'maxLength': 2
            },
        },
        'manual_attr': {
            'desc': 'this is a manually-specified attribute',
            'name': 'manual_attr',
            'create': True,
            'read': True,
            'type': 'auto',
            'update': True,
            'validators': {
                'maxLength': 2
            }
        }
    }
)
@text_length_validation('string_model_attr', 2, 100)
@regex_validation('string_model_attr', r'^[A-Za-z0-9\.\_\-]+$', 'test thing')
@text_length_validation('overridden_desc', 1, 100)
@text_length_validation('nonexistant_field', 1, 100)
class CrudableClass(CrudableMixin, Base):
    """Testbed class for getting the crud definition for a class that be crudable"""

    string_attr = 'str'
    int_attr = 1
    bool_attr = True
    float_attr = 1.0
    date_attr = datetime(2011, 1, 1, 0, 0, 0)
    string_model_attr = Column(UnicodeText(), default='default string')
    int_model_attr = Column(Integer())
    bool_model_attr = Column(Boolean())

    @property
    def settable_property(self):
        """this is the docstring"""
        return None

    @settable_property.setter
    def settable_property(self, thing):
        pass

    @hybrid_property
    def string_and_int_hybrid_property(self):
        """this is the docstring"""
        return '{} {}'.format(self.string_model_attr, self.int_model_attr)

    @string_and_int_hybrid_property.expression
    def string_and_int_hybrid_property(cls):
        return case(
            (cls.string_model_attr == None, ''),
            (cls.int_model_attr == None, '')
        , else_=(cls.string_model_attr + ' ' + cls.int_model_attr))

    @property
    def unsettable_property(self):
        """
        this is an epydoc-decorated docstring

        @return: None
        """
        return None

    def method(self):
        pass

    @property
    def overridden_desc(self):
        """docstring but not desc"""
        return None


@crudable()
class BasicClassMixedIn(CrudableMixin, Base):
    pass


class Session(SessionManager):
    engine = sqlalchemy.create_engine('sqlite:////tmp/test_sa.db', poolclass=NullPool)

    class SessionMixin(object):
        def user(self, name):
            return self.query(User).filter_by(name=name).one()

        def account(self, username):
            return self.query(Account).filter_by(username=username).one()


def create(model, **params):
    with Session() as session:
        model = Session.resolve_model(model)
        item = model(**params)
        session.add(item)
        session.commit()
        return item.to_dict()


def query_from(obj, attr='id'):
    return {
        '_model': obj['_model'],
        'field': attr,
        'value': obj[attr]
    }


@pytest.fixture(scope='module')
def init_db(request):
    class db:
        pass
    patch_session(Session, request)
    db.turner = create('User', name='Turner')
    db.hooch = create('User', name='Hooch')
    create('Tag', user_id=db.turner['id'], name='Male')
    create('Tag', user_id=db.hooch['id'], name='Male')
    db.ninja = create('Tag', user_id=db.turner['id'], name='Ninja')
    db.pirate = create('Tag', user_id=db.hooch['id'], name='Pirate')
    db.boss = create('Boss', name='Howard Hyde')
    db.turner_account = create('Account', username='turner_account', password='password', user_id=db.turner['id'], boss_id=db.boss['id'])
    db.hooch_account = create('Account', username='hooch_account', password='password', user_id=db.hooch['id'])
    return db


@pytest.fixture(autouse=True)
def db(request, init_db):
    shutil.copy('/tmp/sideboard.db', '/tmp/sideboard.db.backup')
    request.addfinalizer(lambda: shutil.move('/tmp/sideboard.db.backup', '/tmp/sideboard.db'))
    return init_db


class TestNamingConventions(object):

    @pytest.mark.parametrize('sqltext,expected', [
        ('failed_logins >= 3', 'failed_logins_ge_3'),
        ('failed_logins > 3', 'failed_logins_gt_3'),
        ('   failed_logins   =   3   ', 'failed_logins_eq_3'),
        ('0123456789012345678901234567890123', '1e4008bc148c5486a3c92b2377fa1c45')
    ])
    def test_check_constraint_naming_convention(self, sqltext, expected):
        check_constraint = CheckConstraint(sqltext)
        table = Table('account', MetaData())
        result = check_constraint_naming_convention(check_constraint, table)
        assert result == expected


class TestDeclarativeBaseConstructor(object):
    def test_default_init(self):
        assert User().id  # default is applied at initialization instead of on save

    def test_overriden_init(self):
        @declarative_base
        class WithOverriddenInit(object):
            id = Column(UUID(), primary_key=True, default=uuid.uuid4)

            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)

        class Foo(WithOverriddenInit):
            bar = Column(Boolean())

        assert Foo().id is None

    @pytest.mark.filterwarnings("ignore:Unmanaged access of declarative attribute")
    def test_declarative_base_without_parameters(self):

        @declarative_base
        class BaseTest:
            pass

        assert BaseTest.__tablename__ == 'base_test'

    @pytest.mark.filterwarnings("ignore:Unmanaged access of declarative attribute")
    def test_declarative_base_with_parameters(self):

        @declarative_base(name=str('NameOverride'))
        class BaseTest:
            pass

        assert BaseTest.__tablename__ == 'name_override'


class TestCrudCount(object):
    def assert_counts(self, query, **expected):
        actual = {count['_label']: count['count'] for count in Session.crud.count(query)}
        assert len(expected) == len(actual)
        for label, count in expected.items():
            assert count == actual[label]

    def test_subquery(self):
        results = Session.crud.count({
            '_model': 'Tag',
            'groupby': ['name'],
            'field': 'user_id',
            'comparison': 'in',
            'value': {
                '_model': 'User',
                'select': 'id',
                'field': 'name',
                'value': 'Turner'
            }
        })
        expected = {
            'Male': 1,
            'Ninja': 1
        }
        for result in results[0]['count']:
            assert result['count'] == expected[result['name']]

    def test_compound_subquery(self):
        query = {
            '_model': 'Tag',
            'groupby': ['name'],
            'field': 'user_id',
            'comparison': 'in',
            'value': {
                '_model': 'User',
                'select': 'id',
                'or': [{
                    'field': 'name',
                    'value': 'Turner'
                }, {
                    'field': 'name',
                    'value': 'Hooch'
                }]
            }
        }
        results = Session.crud.count(query)
        expected = {
            'Ninja': 1,
            'Pirate': 1,
            'Male': 2
        }
        for result in results[0]['count']:
            assert result['count'] == expected[result['name']]

    def test_distinct(self):
        pytest.skip('Query.distinct(*columns) is postgresql-only')
        results = Session.crud.count({'_model': 'Tag'})
        assert results[0]['count'] == 4

        results = Session.crud.count({
            '_model': 'Tag',
            'distinct': ['name']
        })
        results[0]['count'] == 3

    def test_groupby(self):
        results = Session.crud.count({
            '_model': 'Tag',
            'groupby': ['name']
        })
        expected = {
            'Male': 2,
            'Ninja': 1,
            'Pirate': 1
        }
        for result in results[0]['count']:
            result['count'] == expected.get(result['name'], 0)

    def test_single_basic_query_string(self):
        self.assert_counts('User', User=2)

    def test_single_basic_query_dict(self):
        self.assert_counts({'_model': 'User'}, User=2)

    def test_multi_basic_query_string(self):
        self.assert_counts(['User', 'Tag'], User=2, Tag=4)

    def test_multi_basic_query_dict(self):
        self.assert_counts([{'_model': 'User'}, {'_model': 'Tag'}], User=2, Tag=4)

    def test_single_complex_query(self):
        self.assert_counts({'_label': 'HoochCount', '_model': 'User', 'field': 'name', 'value': 'Hooch'}, HoochCount=1)

    def test_multi_complex_query(self):
        self.assert_counts([{'_label': 'HoochCount', '_model': 'User', 'field': 'name', 'value': 'Hooch'},
                            {'_label': 'MaleCount', '_model': 'Tag', 'field': 'name', 'value': 'Male'}],
                           HoochCount=1, MaleCount=2)

    def test_multi_complex_query_with_same_models(self):
        hooch_query = {
            '_model': 'User',
            '_label': 'HoochCount',
            'or': [{
                '_model': 'User',
                'field': 'name',
                'value': 'Hooch'
            }, {
                '_model': 'User',
                'field': 'name',
                'value': 'Hoochert'
            }]
        }
        turner_query = {
            '_model': 'User',
            '_label': 'TurnerCount',
            'field': 'name',
            'value': 'Turner'
        }
        all_query = {'_model': 'User'}

        self.assert_counts([hooch_query, turner_query, all_query], User=2, HoochCount=1, TurnerCount=1)


class TestCrudRead(object):
    def extract(self, models, *fields):
        return [{f: m[f] for f in fields if f in m} for m in listify(models)]

    def assert_read_result(self, expected, query, data=None):
        expected = listify(expected)
        actual = Session.crud.read(query, data)
        assert len(expected) == actual['total']
        assert sorted(expected, key=lambda m: m.get('id', m.get('_model'))) \
            == sorted(actual['results'], key=lambda m: m.get('id', m.get('_model')))

    def test_to_dict_default_attrs(self):
        expected = [
            'bool_attr',
            'bool_model_attr',
            'date_attr',
            'extra_data',
            'float_attr',
            'id',
            'int_attr',
            'int_model_attr',
            'mixed_in_attr',
            'string_attr',
            'string_model_attr']
        actual = CrudableClass.to_dict_default_attrs
        assert sorted(expected) == sorted(actual)

    def test_subquery(self):
        results = Session.crud.read({
            '_model': 'Tag',
            'field': 'user_id',
            'comparison': 'in',
            'value': {
                '_model': 'User',
                'select': 'id',
                'field': 'name',
                'value': 'Turner'
            }
        })
        assert results['total'] == 2
        assert len(results['results']) == 2
        for tag in results['results']:
            assert tag['name'] in ['Ninja', 'Male']

    def test_compound_subquery(self):
        results = Session.crud.read({
            '_model': 'Tag',
            'field': 'user_id',
            'comparison': 'in',
            'value': {
                '_model': 'User',
                'select': 'id',
                'or': [{
                    'field': 'name',
                    'value': 'Turner'
                }, {
                    'field': 'name',
                    'value': 'Hooch'
                }]
            }
        })
        assert results['total'] == 4
        assert len(results['results']) == 4
        for tag in results['results']:
            assert tag['name'] in ['Pirate', 'Ninja', 'Male']

    def test_distinct(self):
        pytest.skip('Query.distinct(*columns) is postgresql-only')
        results = Session.crud.read({
            '_model': 'Tag',
            'distinct': ['name']
        })
        assert results['total'] == 3
        assert len(results['results']) == 3

        results = Session.crud.read({
            '_model': 'Tag',
            'distinct': True
        })
        assert results['total'] == 4
        assert len(results['results']) == 4

        results = Session.crud.read({
            '_model': 'Tag',
            'distinct': ['name', 'id']
        })
        assert results['total'] == 4
        assert len(results['results']) == 4

    def test_omit_keys_that_are_returned_by_default(self):
        results = Session.crud.read({'_model': 'Account'}, {
            '_model': False,
            'id': False,
            'username': True,
            'password': False,
            'user': {
                '_model': False,
                'id': False,
                'name': True
            }
        })
        for account in results['results']:
            assert '_model' not in account
            assert 'id' not in account
            assert 'password' not in account
            assert '_model' not in account['user']
            assert 'id' not in account['user']
            assert 'username' in account
            assert 'name' in account['user']

    def test_basic_read(self, db):
        self.assert_read_result(db.turner, query_from(db.turner, 'id'))
        self.assert_read_result(db.turner, query_from(db.turner, 'name'))

    def test_read_with_basic_data_spec(self, db):
        result = {
            '_model': 'Account',
            'id': db.turner_account['id'],
            'username': 'turner_account'
        }
        self.assert_read_result(result, query_from(db.turner_account, 'username'), {'username': True})
        self.assert_read_result(result, [query_from(db.turner_account, 'username')], {'username': True})
        self.assert_read_result(result, query_from(db.turner_account, 'username'), [{'username': True}])
        self.assert_read_result(result, [query_from(db.turner_account, 'username')], [{'username': True}])
        self.assert_read_result(result, query_from(db.turner_account, 'username'), ['username'])
        self.assert_read_result(result, [query_from(db.turner_account, 'username')], ['username'])
        self.assert_read_result(result, query_from(db.turner_account, 'username'), 'username')
        self.assert_read_result(result, [query_from(db.turner_account, 'username')], 'username')

    def test_handle_read_with_data_spec_requesting_unreadable_attribute(self, db):
        result = {
            '_model': 'Account',
            'id': db.turner_account['id']
        }
        self.assert_read_result(result, query_from(db.turner_account, 'username'), {'does_not_exist': True})
        self.assert_read_result(result, [query_from(db.turner_account, 'username')], {'does_not_exist': True})
        self.assert_read_result(result, query_from(db.turner_account, 'username'), [{'does_not_exist': True}])
        self.assert_read_result(result, [query_from(db.turner_account, 'username')], [{'does_not_exist': True}])
        self.assert_read_result(result, query_from(db.turner_account, 'username'), ['does_not_exist'])
        self.assert_read_result(result, [query_from(db.turner_account, 'username')], ['does_not_exist'])
        self.assert_read_result(result, query_from(db.turner_account, 'username'), 'does_not_exist')
        self.assert_read_result(result, [query_from(db.turner_account, 'username')], 'does_not_exist')

    def test_read_with_multiple_queries(self, db):
        self.assert_read_result([db.turner_account, db.hooch_account], [query_from(db.turner_account), query_from(db.hooch_account)])

    def test_read_with_multiple_queries_and_one_data_spec(self, db):
        expected = self.extract([db.turner_account, db.hooch_account], '_model', 'id', 'username')
        self.assert_read_result(expected, [query_from(db.turner_account), query_from(db.hooch_account)], {'username': True})
        self.assert_read_result(expected, [query_from(db.turner_account), query_from(db.hooch_account)], [{'username': True}])
        self.assert_read_result(expected, [query_from(db.turner_account), query_from(db.hooch_account)], ['username'])
        self.assert_read_result(expected, [query_from(db.turner_account), query_from(db.hooch_account)], 'username')

    def test_read_with_ored_query_and_one_data_spec(self, db):
        expected = self.extract([db.turner_account, db.hooch_account], '_model', 'id', 'username')
        query = {
            '_model': 'Account',
            'or': [{
                'field': 'username',
                'value': 'turner_account'
            }, {
                'field': 'username',
                'value': 'hooch_account'
            }]
        }
        self.assert_read_result(expected, query, {'username': True})
        self.assert_read_result(expected, query, [{'username': True}])
        self.assert_read_result(expected, query, ['username'])
        self.assert_read_result(expected, query, 'username')
        self.assert_read_result(expected, [query], {'username': True})
        self.assert_read_result(expected, [query], [{'username': True}])
        self.assert_read_result(expected, [query], 'username')
        self.assert_read_result(expected, [query], ['username'])

    def test_read_with_two_models(self, db):
        query = [query_from(db.turner), query_from(db.hooch_account)]
        self.assert_read_result([db.turner, db.hooch_account], query)

    def test_read_with_two_models_and_one_data_spec(self, db):
        query = [query_from(db.turner), query_from(db.pirate)]
        expected = self.extract([db.turner, db.pirate], '_model', 'id', 'name')
        self.assert_read_result(expected, query, {'name': True})
        self.assert_read_result(expected, query, [{'name': True}])
        self.assert_read_result(expected, query, ['name'])
        self.assert_read_result(expected, query, 'name')

    def test_read_with_two_models_and_two_data_specs(self, db):
        query = [query_from(db.turner_account), query_from(db.pirate)]
        expected = self.extract(db.turner_account, '_model', 'id', 'username') + self.extract(db.pirate, '_model', 'id', 'user_id')
        self.assert_read_result(expected, query, [['username'], ['user_id']])
        self.assert_read_result(expected, query, [{'username': True}, ['user_id']])
        self.assert_read_result(expected, query, [['username'], {'user_id': True}])
        self.assert_read_result(expected, query, [{'username': True}, {'user_id': True}])

    def test_handle_bad_query(self):
        pytest.raises(CrudException, Session.crud.read, {'field': 'last_name'})

    def test_handle_illegal_read(self, db):
        results = Session.crud.read(query_from(db.turner), {'__repr__': True})
        assert '__repr__' not in results['results'][0]

    def test_handle_read_on_nonexistant_attribute(self, db):
        results = Session.crud.read(query_from(db.turner), {'does_not_exist': True})
        assert 'does_not_exist' not in results['results'][0]


class TestCrudUpdate(object):
    def test_single_update(self):
        Session.crud.update({'_model': 'Account', 'field': 'username', 'value': 'turner_account'}, {'password': 'changing'})
        with Session() as session:
            assert 'password' == session.account('hooch_account').password
            assert 'changing' == session.account('turner_account').password

    def test_multiple_updates(self):
        Session.crud.update({'_model': 'Account'}, {'password': 'foobar'})
        with Session() as session:
            for account in session.query(Account).all():
                assert account.password == 'foobar'

    def test_nested_json(self):
        Session.crud.update({'_model': 'Account', 'username': 'turner_account'}, {
            'password': 'barbaz',
            'user': {'name': 'Turner the Awesome'}
        })
        with Session() as session:
            assert 'barbaz' == session.account('turner_account').password
            assert 'Turner the Awesome' == session.account('turner_account').user.name

    def test_handle_bad_relation_type(self, db):
        pytest.raises(CrudException, Session.crud.update, query_from(db.turner), {'employees': 'not a dict or sequence of dicts'})

    def test_create_foreign_relation_with_one_spec(self):
        Session.crud.update({'_model': 'Account'}, {'user': {'name': 'New User'}})
        with Session() as session:
            assert 3 == len(session.query(User).all())
            assert 'New User' == session.account('turner_account').user.name
            assert 'New User' == session.account('hooch_account').user.name

    def test_create_foreign_relation_with_multiple_specs(self, db):
        Session.crud.update([query_from(db.turner_account), query_from(db.hooch_account)], 2 * [{'user': {'name': 'New User'}}])
        with Session() as session:
            assert 3 == len(session.query(User).all())
            assert 'New User' == session.account('turner_account').user.name
            assert 'New User' == session.account('hooch_account').user.name

    def test_adding_and_removing_tag(self, db):
        Session.crud.update(query_from(db.turner), {'tags': []})
        with Session() as session:
            assert not session.user('Turner').tags
            assert 2 == session.query(Tag).count()

        Session.crud.update(query_from(db.turner), {'tags': [{'name': 'New'}]})
        with Session() as session:
            assert 3 == session.query(Tag).count()
            [new] = session.user('Turner').tags
            assert 'New' == new.name

    def test_removing_tags_with_none(self, db):
        Session.crud.update(query_from(db.turner), {'tags': None})
        with Session() as session:
            assert not session.user('Turner').tags
            assert 2 == session.query(Tag).count()

    def test_editing_account_from_user(self, db):
        Session.crud.update(query_from(db.turner), {
            'employees': [{
                'username': 'turner_account',
                'password': 'newpass'
            }]
        })
        with Session() as session:
            assert 2 == session.query(Account).count()
            assert 'newpass' == session.account('turner_account').password

    def test_unset_nullable_foreign_relation(self, db):
        Session.crud.update(query_from(db.turner_account), {'boss': None})
        with Session() as session:
            assert 1 == session.query(Boss).count()
            assert session.account('turner_account').boss is None

    def test_unset_nullable_foreign_relation_from_parent_with_none(self, db):
        Session.crud.update(query_from(db.boss), {'employees': None})
        with Session() as session:
            assert 1 == session.query(Boss).count()
            assert session.account('turner_account').boss is None

    def test_unset_nullable_foreign_relation_from_parent_with_empty_list(self, db):
        Session.crud.update(query_from(db.boss), {'employees': []})
        with Session() as session:
            assert 1 == session.query(Boss).count()
            assert session.account('turner_account').boss is None

    def test_update_nonexistent_attribute(self, db):
        pytest.raises(Exception, Session.crud.update, query_from(db.turner), {'does_not_exist': 'foo'})

    def test_update_nonupdatable_attribute(self, db):
        pytest.raises(Exception, Session.crud.update, query_from(db.turner_account), {'username': 'foo'})


class TestCrudDelete(object):
    def test_delete_cascades_to_tags(self, db):
        Session.crud.delete(query_from(db.turner_account))
        Session.crud.delete(query_from(db.turner))
        with Session() as session:
            assert 1 == session.query(Account).count()
            assert 2 == session.query(Tag).count()

    def test_delete_by_id(self, db):
        Session.crud.delete({'_model': 'Account', 'field': 'id', 'value': db.turner_account['id']})
        with Session() as session:
            assert 1 == session.query(Account).count()
            pytest.raises(Exception, session.account, 'turner_account')

    def test_multiple_deletes_by_id(self):
        Session.crud.delete([
            {'_model': 'Account', 'field': 'username', 'value': 'turner_account'},
            {'_model': 'Tag', 'field': 'name', 'value': 'Pirate'}
        ])
        with Session() as session:
            assert 3 == session.query(Tag).count()
            assert 1 == session.query(Account).count()
            pytest.raises(Exception, session.account, 'turner_account')

    def test_empty_delete(self):
        assert 0 == Session.crud.delete([])

    def test_delete_without_results(self):
        assert 0 == Session.crud.delete({'_model': 'Account', 'field': 'username', 'value': 'does_not_exist'})

    def test_non_single_delete(self):
        pytest.raises(CrudException, Session.crud.delete, {'_model': 'Account'})
        pytest.raises(CrudException, Session.crud.delete, {'_model': 'Tag', 'field': 'name', 'value': 'Male'})


class TestCrudCreate(object):
    def test_basic_create(self, db):
        Session.crud.create({
            '_model': 'Tag',
            'name': 'New',
            'user_id': db.turner['id']
        })
        with Session() as session:
            assert {'New', 'Ninja', 'Male'} == {tag.name for tag in session.user('Turner').tags}

    def test_deeply_nested_create(self):
        Session.crud.create({
            '_model': 'Account',
            'username': 'new',
            'password': 'createdpass',
            'user': {
                'name': 'New',
                'tags': [{'name': 'Recent'}, {'name': 'Male'}]
            }
        })
        with Session() as session:
            new = session.account('new')
            assert 'new' == new.username
            assert 'New' == new.user.name
            assert {'Recent', 'Male'} == {tag.name for tag in new.user.tags}

    def test_duplicate_create(self):
        pytest.raises(CrudException, Session.crud.create, {'_model': 'User', 'name': 'Turner'})

    def test_create_two_objects(self):
        Session.crud.create([{
            '_model': 'Boss',
            'name': 'NewCo'
        }, {
            '_model': 'User',
            'name': 'New Guy'
        }])
        with Session() as session:
            assert 3 == session.query(User).count()
            assert 2 == session.query(Boss).count()

    def test_handle_bad_spec_no_model(self):
        pytest.raises(CrudException, Session.crud.create, {'name': 'Turner'})

    def test_setting_null_on_unnullable_attributes(self):
        pytest.raises(CrudException, Session.crud.create, {'_model': 'User', 'name': None})

    def test_set_foreign_key_relations_using_string_id(self, db):
        Session.crud.create({
            '_model': 'Account',
            'user_id': db.turner['id'],
            'username': 'turner_account_other_users',
            'password': 'password'
        })
        with Session() as session:
            assert 2 == len(session.user('Turner').employees)


class TestCrudValidations(object):
    def test_length(self):
        pytest.raises(CrudException, Session.crud.update, {'_model': 'User'}, {'name': ''})
        pytest.raises(CrudException, Session.crud.update, {'_model': 'User'}, {'name': 'x' * 101})

    def test_regex(self):
        pytest.raises(CrudException, Session.crud.update, {'_model': 'Account'}, {'username': '!@#'})


class TestNormalizeQuery(object):
    def test_one_string(self):
        results = normalize_query('Human')
        assert results == [{'_model': 'Human', '_label': 'Human'}]

    def test_one_string_in_a_list(self):
        results = normalize_query(['Human'])
        assert results == [{'_model': 'Human', '_label': 'Human'}]

    def test_two_strings(self):
        results = normalize_query(['Human', 'Proxy'])
        assert results == [{'_model': 'Human', '_label': 'Human'}, {'_model': 'Proxy', '_label': 'Proxy'}]
        results = normalize_query(['Proxy', 'Human'])
        assert results == [{'_model': 'Proxy', '_label': 'Proxy'}, {'_model': 'Human', '_label': 'Human'}]

    def test_one_dict(self):
        results = normalize_query({'_model': 'Human'})
        assert results == [{'_model': 'Human'}]

    def test_one_dict_in_a_list(self):
        results = normalize_query([{'_model': 'Human'}])
        assert results == [{'_model': 'Human'}]

    def test_two_dicts(self):
        results = normalize_query([{'_model': 'Human'}, {'_model': 'Proxy'}])
        assert results == [{'_model': 'Human'}, {'_model': 'Proxy'}]
        results = normalize_query([{'_model': 'Proxy'}, {'_model': 'Human'}])
        assert results == [{'_model': 'Proxy'}, {'_model': 'Human'}]

    def test_or_clause(self):
        results = normalize_query([{'_model': 'Human', 'or': [{'_model': 'Human', 'field': 'nickname', 'value': 'Johnny'}, {'_model': 'Human', 'field': 'nickname', 'value': 'Winny'}]}, {'_model': 'Proxy'}])
        assert results == [{'_model': 'Human', 'or': [{'_model': 'Human', 'field': 'nickname', 'value': 'Johnny'}, {'_model': 'Human', 'field': 'nickname', 'value': 'Winny'}]}, {'_model': 'Proxy'}]

    def test_and_clause_push_down_supermodel(self):
        results = normalize_query([{'_model': 'Human', 'or': [{'field': 'nickname', 'value': 'Johnny'}, {'field': 'nickname', 'value': 'Winny'}]}, {'_model': 'Proxy'}])
        assert results == [{'_model': 'Human', 'or': [{'_model': 'Human', 'field': 'nickname', 'value': 'Johnny'}, {'_model': 'Human', 'field': 'nickname', 'value': 'Winny'}]}, {'_model': 'Proxy'}]

    def test_or_clause_no_model(self):
        results = normalize_query([{'or': [{'_model': 'Human'}, {'_model': 'Human', 'field': 'nickname', 'value': 'Johnny'}]}, {'_model': 'Proxy'}])
        assert results == [{'_model': 'Human', 'or': [{'_model': 'Human'}, {'_model': 'Human', 'field': 'nickname', 'value': 'Johnny'}]}, {'_model': 'Proxy'}]

    def test_and_clause(self):
        results = normalize_query([{'_model': 'Human', 'and': [{'_model': 'Human', 'field': 'nickname', 'value': 'Johnny'}, {'_model': 'Human', 'field': 'nickname', 'value': 'Winny'}]}, {'_model': 'Proxy'}])
        assert results == [{'_model': 'Human', 'and': [{'_model': 'Human', 'field': 'nickname', 'value': 'Johnny'}, {'_model': 'Human', 'field': 'nickname', 'value': 'Winny'}]}, {'_model': 'Proxy'}]

    def test_and_clause_no_model(self):
        results = normalize_query([{'and': [{'_model': 'Human'}, {'_model': 'Human', 'field': 'nickname', 'value': 'Johnny'}]}, {'_model': 'Proxy'}])
        assert results == [{'_model': 'Human', 'and': [{'_model': 'Human'}, {'_model': 'Human', 'field': 'nickname', 'value': 'Johnny'}]}, {'_model': 'Proxy'}]

    def test_fails_or_clause_list_of_lists(self):
        pytest.raises(ValueError, normalize_query, [{'or': [[], []]}, {'_model': 'Proxy', '_label': 'Proxy'}])

    def test_fails_none(self):
        pytest.raises(ValueError, normalize_query, None)

    def test_fails_list_of_lists(self):
        pytest.raises(ValueError, normalize_query, [[], []])

    def test_fails_one_empty_dict(self):
        pytest.raises(ValueError, normalize_query, {})

    def test_fails_one_dict_no_model(self):
        pytest.raises(ValueError, normalize_query, {'field': 'nickname', 'value': 'Johnny'})

    def test_fails_one_empty_dict_in_a_list(self):
        pytest.raises(ValueError, normalize_query, [{}])

    def test_fails_one_dict_no_model_in_a_list(self):
        pytest.raises(ValueError, normalize_query, [{'field': 'nickname', 'value': 'Johnny'}])

    def test_fails_two_dicts_one_without_model(self):
        pytest.raises(ValueError, normalize_query, [{'_model': 'Proxy'}, {'field': 'nickname', 'value': 'Johnny'}])

    def test_fails_and_clause_no_model(self):
        pytest.raises(ValueError, normalize_query, [{'and': [{'field': 'nickname', 'value': 'Johnny'}, {'field': 'nickname', 'value': 'Winny'}]}, {'_model': 'Proxy'}])

    def test_fails_or_clause_no_model(self):
        pytest.raises(ValueError, normalize_query, [{'or': [{'field': 'nickname', 'value': 'Johnny'}, {'field': 'nickname', 'value': 'Winny'}]}, {'_model': 'Proxy'}])

    def test_fails_and_clause_list_of_lists(self):
        pytest.raises(ValueError, normalize_query, [{'and': [[], []]}, {'_model': 'Proxy'}])

    def test_fails_and_clause_with_model_list_of_lists(self):
        pytest.raises(ValueError, normalize_query, [{'_model': 'Human', 'and': [[], []]}, {'_model': 'Proxy'}])

    def test_fails_or_clause_with_model_list_of_lists(self):
        pytest.raises(ValueError, normalize_query, [{'_model': 'Human', 'or': [[], []]}, {'_model': 'Proxy'}])


class TestCollectModels(object):
    def assert_models(self, *args):
        expected_models = set(args[:-1])
        actual_models = Session.crud._collect_models(args[-1])
        assert expected_models == actual_models

    def test_single(self):
        self.assert_models(User, {'_model': 'User'})

    def test_multiple(self):
        self.assert_models(User, Account, [{'_model': 'User'}, {'_model': 'Account'}])

    def test_foreign_key(self):
        self.assert_models(Account, User, {'_model': 'Account', 'field': 'user.name'})

    def test_nested_keys(self):
        self.assert_models(Account, User, Tag, {'_model': 'Account', 'field': 'user.name.tags'})


class TestCrudableClass(object):
    expected_crud_spec = {
        'fields': {
            'id': {
                'name': 'id',
                'type': 'auto',
                'create': True,
                'read': True,
                'update': False,
            },
            'string_attr': {
                'name': 'string_attr',
                'type': 'string',
                'create': False,
                'read': True,
                'update': False,
                'defaultValue': 'str',
            },
            'int_attr': {
                'name': 'int_attr',
                'type': 'int',
                'create': False,
                'read': True,
                'update': False,
                'defaultValue': 1,
            },
            'extra_data': {
                'create': True,
                'name': 'extra_data',
                'read': True,
                'type': 'auto',
                'update': True
            },
            'bool_attr': {
                'name': 'bool_attr',
                'type': 'boolean',
                'create': False,
                'read': True,
                'update': False,
                'defaultValue': True,
            },
            'float_attr': {
                'name': 'float_attr',
                'type': 'float',
                'create': False,
                'read': True,
                'update': False,
                'defaultValue': 1.0,
            },
            'date_attr': {
                'name': 'date_attr',
                'type': 'date',
                'create': False,
                'read': True,
                'update': False,
                'desc': 'this is a manual desc',
                'defaultValue': datetime(2011, 1, 1, 0, 0),
                'date_format': 'Y-M-d',
            },
            'string_model_attr': {
                'name': 'string_model_attr',
                'type': 'string',
                'create': True,
                'read': True,
                'update': True,
                'defaultValue': 'default string',
                'validators': {
                    u'maxLength': 100,
                    u'maxLengthText': u'The maximum length of this field is {0}.',
                    u'minLength': 2,
                    u'minLengthText': u'The minimum length of this field is {0}.',
                    u'regexString': u'^[A-Za-z0-9\\.\\_\\-]+$',
                    u'regexText': u'test thing'}
            },
            'mixed_in_attr': {
                'create': True,
                'defaultValue': 'default string',
                'name': 'mixed_in_attr',
                'read': True,
                'type': 'string',
                'update': True,
                'validators': {
                    'maxLength': 10,
                    'maxLengthText': 'The maximum length of this field is {0}.',
                    'minLength': 1,
                    'minLengthText': 'The minimum length of this field is {0}.'
                }
            },
            'bool_model_attr': {
                'name': 'bool_model_attr',
                'type': 'boolean',
                'create': True,
                'read': True,
                'update': True,
            },
            'int_model_attr': {
                'name': 'int_model_attr',
                'type': 'int',
                'create': True,
                'read': True,
                'update': True,
            },
            'settable_property': {
                'desc': 'this is the docstring',
                'name': 'settable_property',
                'type': 'auto',
                'create': True,
                'read': True,
                'update': True,
            },
            'unsettable_property': {
                'desc': 'this is an epydoc-decorated docstring',
                'name': 'unsettable_property',
                'type': 'auto',
                'create': False,
                'read': True,
                'update': False,
            },
            'manual_attr': {
                'name': 'manual_attr',
                'type': 'auto',
                'create': True,
                'read': True,
                'update': True,
                'desc': 'this is a manually-specified attribute',
                'validators': {
                    'maxLength': 2
                }
            },
            'overridden_desc': {
                'create': False,
                'desc': 'this is an overridden desc',
                'name': 'overridden_desc',
                'read': True,
                'type': 'auto',
                'update': False,
                'validators': {
                    'maxLength': 2,
                    'maxLengthText': 'The maximum length of this field is {0}.',
                    'minLength': 1,
                    'minLengthText': 'The minimum length of this field is {0}.',
                }
            }
        }
    }

    def test_crud_spec(self):
        assert self.expected_crud_spec == CrudableClass._crud_spec

    def test_basic_crud_spec(self):
        expected_basic = {'fields': {k: self.expected_crud_spec['fields'][k]
                                     for k in ('id', 'mixed_in_attr', 'extra_data')}}
        assert expected_basic == BasicClassMixedIn._crud_spec

    def test_handle_no_crud_spec_attribute(self):
        with pytest.raises(AttributeError):
            object._crud_spec


def test_collect_ancestor_classes():
    classes = collect_ancestor_classes(Account)
    for cls in [Account, Base, object]:
        assert cls in classes

    classes = collect_ancestor_classes(Account, object)
    for cls in [Account, Base]:
        assert cls in classes
    for cls in [object]:
        assert cls not in classes

    classes = collect_ancestor_classes(Account, Base)
    for cls in [Account]:
        assert cls in classes
    for cls in [Base, object]:
        assert cls not in classes


def test_get_models():
    def assert_models(xs, models):
        assert set(xs) == Session.crud._get_models(models)

    assert_models([], 0)
    assert_models([], {})
    assert_models([], [])
    assert_models([], '')
    assert_models([], None)
    assert_models([], {'_model': 0})
    assert_models([], {'_model': {}})
    assert_models([], {'_model': []})
    assert_models([], {'_model': None})
    assert_models(['User'], {'_model': 'User'})
    assert_models(['User'], [{'_model': 'User'}])
    assert_models(['User'], ({'_model': 'User'},))
    assert_models(['User'], {'foo': {'_model': 'User'}})
