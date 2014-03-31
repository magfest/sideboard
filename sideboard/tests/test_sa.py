from __future__ import unicode_literals
import uuid
from datetime import datetime
from unittest import skip, TestCase

import sqlalchemy
from sqlalchemy.orm import relationship
from sqlalchemy.types import Boolean, Integer, UnicodeText
from sqlalchemy.schema import Column, ForeignKey, UniqueConstraint

from sideboard.lib import log, listify
from sideboard.tests import SideboardTest, SideboardServerTest
from sideboard.lib.sa._crud import normalize_query, collect_ancestor_classes
from sideboard.lib.sa import SessionManager, UUID, JSON, declarative_base, CrudException, crudable, text_length_validation, regex_validation


@declarative_base
class Base(object):
    id = Column(UUID(), primary_key=True, default=uuid.uuid4)


@crudable(update=['tags','employees'])
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
    user = relationship(User)
    username = Column(UnicodeText(), nullable=False, unique=True)
    password = Column(UnicodeText(), nullable=False)

    boss_id = Column(UUID(), ForeignKey('boss.id', ondelete='SET NULL'))
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
    extra_data = Column(JSON(), default={}, server_default="{}")


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
@regex_validation('string_model_attr', "^[A-Za-z0-9\.\_\-]+$", "test thing")
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
    engine = sqlalchemy.create_engine('sqlite:////tmp/test.db')

    class SessionMixin(object):
        def user(self, name):
            return self.query(User).filter_by(name=name).one()
        
        def account(self, username):
            return self.query(Account).filter_by(username=username).one()


class CrudTests(SideboardTest):
    Session = Session
    
    def create(self, model, **params):
        with Session() as session:
            model = Session.resolve_model(model)
            try:
                item = session.query(model).get(id)
            except:
                item = model(**params)
                session.add(item)
                session.commit()
            
            return item.to_dict()

    def query_from(self, obj, attr='id'):
        return {
            '_model': obj['_model'],
            'field': attr,
            'value': obj[attr]
        }

    def setUp(self):
        super(CrudTests, self).setUp()
        self.turner = self.create('User', name='Turner')
        self.hooch = self.create('User', name='Hooch')
        self.create('Tag', user_id=self.turner['id'], name='Male')
        self.create('Tag', user_id=self.hooch['id'], name='Male')
        self.ninja = self.create('Tag', user_id=self.turner['id'], name='Ninja')
        self.pirate = self.create('Tag', user_id=self.hooch['id'], name='Pirate')
        self.boss = self.create('Boss', name='Howard Hyde')
        self.turner_account = self.create('Account', username='turner_account', password='password', user_id=self.turner['id'], boss_id=self.boss['id'])
        self.hooch_account = self.create('Account', username='hooch_account', password='password', user_id=self.hooch['id'])


class TestCrudCount(CrudTests):
    def assert_counts(self, query, **expected):
        actual = {count['_label']: count['count'] for count in Session.crud.count(query)}
        self.assertEqual(len(expected), len(actual))
        for label,count in expected.items():
            self.assertEqual(count, actual[label])
    
    def test_subquery(self):
        results = Session.crud.count({
            '_model' : 'Tag',
            'groupby' : ['name'],
            'field' : 'user_id',
            'comparison' : 'in',
            'value' : {
                '_model' : 'User',
                'select' : 'id',
                'field' : 'name',
                'value' : 'Turner'
            }
        })
        expected = {
            'Male': 1,
            'Ninja': 1
        }
        for result in results[0]['count']:
            self.assertEqual(result['count'], expected[result['name']])

    def test_compound_subquery(self):
        query = {
            '_model' : 'Tag',
            'groupby' : ['name'],
            'field' : 'user_id',
            'comparison' : 'in',
            'value' : {
                '_model' : 'User',
                'select' : 'id',
                'or' : [{
                    'field' : 'name',
                    'value' : 'Turner'
                }, {
                    'field' : 'name',
                    'value' : 'Hooch'
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
            self.assertEqual(result['count'], expected[result['name']])

    @skip('Query.distinct(*columns) is postgresql-only')
    def test_distinct(self):
        results = Session.crud.count({'_model': 'Tag'})
        self.assertEqual(4, results[0]['count'])
        
        results = Session.crud.count({
            '_model': 'Tag',
            'distinct' : ['name']
        })
        self.assertEqual(3, results[0]['count'])

    def test_groupby(self):
        results = Session.crud.count({
            '_model': 'Tag',
            'groupby' : ['name']
        })
        expected = {
            'Male': 2,
            'Ninja': 1,
            'Pirate': 1
        }
        for result in results[0]['count']:
            self.assertEqual(result['count'], expected.get(result['name'], 0))

    def test_single_basic_query_string(self):
        self.assert_counts('User', User=2)

    def test_single_basic_query_dict(self):
        self.assert_counts({'_model' : 'User'}, User=2)

    def test_multi_basic_query_string(self):
        self.assert_counts(['User', 'Tag'], User=2, Tag=4)

    def test_multi_basic_query_dict(self):
        self.assert_counts([{'_model' : 'User'}, {'_model' : 'Tag'}], User=2, Tag=4)

    def test_single_complex_query(self):
        self.assert_counts({'_label': 'HoochCount', '_model': 'User', 'field': 'name', 'value' : 'Hooch'}, HoochCount=1)

    def test_multi_complex_query(self):
        self.assert_counts([{'_label': 'HoochCount', '_model': 'User', 'field': 'name', 'value' : 'Hooch'},
                            {'_label': 'MaleCount', '_model': 'Tag', 'field': 'name', 'value' : 'Male'}],
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


class TestCrudRead(CrudTests):
    def extract(self, models, *fields):
        return [{f: m[f] for f in fields if f in m} for m in listify(models)]
    
    def assert_read_result(self, expected, query, data=None):
        expected = listify(expected)
        actual = Session.crud.read(query, data)
        self.assertEqual(len(expected), actual['total'])
        self.assertEqual(sorted(expected, key=lambda m: m.get('id', m.get('_model'))),
                         sorted(actual['results'],key=lambda m: m.get('id', m.get('_model'))))
    
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
        self.assertEqual(2, results['total'])
        self.assertEqual(2, len(results['results']))
        for tag in results['results']:
            self.assertTrue(tag['name'] in ['Ninja', 'Male'])

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
        self.assertEqual(4, results['total'])
        self.assertEqual(4, len(results['results']))
        for tag in results['results']:
            self.assertTrue(tag['name'] in ['Pirate', 'Ninja', 'Male'])

    @skip('Query.distinct(*columns) is postgresql-only')
    def test_distinct(self):
        results = Session.crud.read({
            '_model': 'Tag',
            'distinct' : ['name']
        })
        self.assertEqual(3, results['total'])
        self.assertEqual(3, len(results['results']))
        
        results = Session.crud.read({
            '_model': 'Tag',
            'distinct' : True
        })
        self.assertEqual(4, results['total'])
        self.assertEqual(4, len(results['results']))
        
        results = Session.crud.read({
            '_model': 'Tag',
            'distinct' : ['name', 'id']
        })
        self.assertEqual(4, results['total'])
        self.assertEqual(4, len(results['results']))

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
            log.debug('account: {}', account)
            self.assertNotIn('_model', account)
            self.assertNotIn('id', account)
            self.assertNotIn('password', account)
            self.assertNotIn('_model', account['user'])
            self.assertNotIn('id', account['user'])
            
            self.assertIn('username', account)
            self.assertIn('name', account['user'])

    def test_basic_read(self):
        self.assert_read_result(self.turner, self.query_from(self.turner, 'id'))
        self.assert_read_result(self.turner, self.query_from(self.turner, 'name'))

    def test_read_with_basic_data_spec(self):
        turner_account = {
            '_model': 'Account',
            'id': self.turner_account["id"],
            'username': 'turner_account'
        }
        self.assert_read_result(turner_account, self.query_from(self.turner_account, 'username'), {'username': True})
        self.assert_read_result(turner_account, [self.query_from(self.turner_account, 'username')], {'username': True})
        self.assert_read_result(turner_account, self.query_from(self.turner_account, 'username'), [{'username': True}])
        self.assert_read_result(turner_account, [self.query_from(self.turner_account, 'username')], [{'username': True}])
        self.assert_read_result(turner_account, self.query_from(self.turner_account, 'username'), ['username'])
        self.assert_read_result(turner_account, [self.query_from(self.turner_account, 'username')], ['username'])
        self.assert_read_result(turner_account, self.query_from(self.turner_account, 'username'), 'username')
        self.assert_read_result(turner_account, [self.query_from(self.turner_account, 'username')], 'username')

    def test_handle_read_with_data_spec_requesting_unreadable_attribute(self):
        turner_account = {
            '_model': 'Account',
            'id': self.turner_account["id"]
        }
        self.assert_read_result(turner_account, self.query_from(self.turner_account, 'username'), {'does_not_exist': True})
        self.assert_read_result(turner_account, [self.query_from(self.turner_account, 'username')], {'does_not_exist': True})
        self.assert_read_result(turner_account, self.query_from(self.turner_account, 'username'), [{'does_not_exist': True}])
        self.assert_read_result(turner_account, [self.query_from(self.turner_account, 'username')], [{'does_not_exist': True}])
        self.assert_read_result(turner_account, self.query_from(self.turner_account, 'username'), ['does_not_exist'])
        self.assert_read_result(turner_account, [self.query_from(self.turner_account, 'username')], ['does_not_exist'])
        self.assert_read_result(turner_account, self.query_from(self.turner_account, 'username'), 'does_not_exist')
        self.assert_read_result(turner_account, [self.query_from(self.turner_account, 'username')], 'does_not_exist')

    def test_read_with_multiple_queries(self):
        self.assert_read_result([self.turner_account, self.hooch_account], [self.query_from(self.turner_account), self.query_from(self.hooch_account)])

    def test_read_with_multiple_queries_and_one_data_spec(self):
        expected = self.extract([self.turner_account, self.hooch_account], '_model', 'id', 'username')
        self.assert_read_result(expected, [self.query_from(self.turner_account), self.query_from(self.hooch_account)], {'username': True})
        self.assert_read_result(expected, [self.query_from(self.turner_account), self.query_from(self.hooch_account)], [{'username': True}])
        self.assert_read_result(expected, [self.query_from(self.turner_account), self.query_from(self.hooch_account)], ['username'])
        self.assert_read_result(expected, [self.query_from(self.turner_account), self.query_from(self.hooch_account)], 'username')

    def test_read_with_ored_query_and_one_data_spec(self):
        expected = self.extract([self.turner_account, self.hooch_account], '_model', 'id', 'username')
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

    def test_read_with_two_models(self):
        query = [self.query_from(self.turner), self.query_from(self.hooch_account)]
        self.assert_read_result([self.turner, self.hooch_account], query)

    def test_read_with_two_models_and_one_data_spec(self):
        query = [self.query_from(self.turner), self.query_from(self.pirate)]
        expected = self.extract([self.turner, self.pirate], '_model', 'id', 'name')
        self.assert_read_result(expected, query, {'name': True})
        self.assert_read_result(expected, query, [{'name': True}])
        self.assert_read_result(expected, query, ['name'])
        self.assert_read_result(expected, query, 'name')

    def test_read_with_two_models_and_two_data_specs(self):
        query = [self.query_from(self.turner_account), self.query_from(self.pirate)]
        expected = self.extract(self.turner_account, '_model', 'id', 'username') + self.extract(self.pirate, '_model', 'id', 'user_id')
        self.assert_read_result(expected, query, [['username'], ['user_id']])
        self.assert_read_result(expected, query, [{'username': True}, ['user_id']])
        self.assert_read_result(expected, query, [['username'], {'user_id': True}])
        self.assert_read_result(expected, query, [{'username': True}, {'user_id': True}])

    def test_handle_bad_query(self):
        self.assertRaises(CrudException, Session.crud.read, {'field': 'last_name'})

    def test_handle_illegal_read(self):
        results = Session.crud.read(self.query_from(self.turner), {'__repr__': True})
        self.assertNotIn('__repr__', results['results'][0])

    def test_handle_read_on_nonexistant_attribute(self):
        results = Session.crud.read(self.query_from(self.turner), {'does_not_exist': True})
        self.assertNotIn('does_not_exist', results['results'][0])


class TestCrudUpdate(CrudTests):
    def test_single_update(self):
        Session.crud.update({'_model': 'Account', 'field': 'username', 'value': 'turner_account'}, {'password': 'changing'})
        with Session() as session:
            self.assertEqual('password', session.account('hooch_account').password)
            self.assertEqual('changing', session.account('turner_account').password)

    def test_multiple_updates(self):
        Session.crud.update({'_model': 'Account'}, {'password': 'foobar'})
        with Session() as session:
            for account in session.query(Account).all():
                self.assertEqual(account.password, 'foobar')

    def test_nested_json(self):
        Session.crud.update({'_model': 'Account', 'username': 'turner_account'}, {
            'password': 'barbaz',
            'user': {'name': 'Turner the Awesome'}
        })
        with Session() as session:
            self.assertEqual('barbaz', session.account('turner_account').password)
            self.assertEqual('Turner the Awesome', session.account('turner_account').user.name)

    def test_handle_bad_relation_type(self):
        self.assertRaises(CrudException, Session.crud.update, self.query_from(self.turner), {'employees': 'not a dict or sequence of dicts'})

    def test_create_foreign_relation_with_one_spec(self):
        Session.crud.update({'_model': 'Account'}, {'user': {'name': 'New User'}})
        with Session() as session:
            self.assertEqual(3, len(session.query(User).all()))
            self.assertEqual('New User', session.account('turner_account').user.name)
            self.assertEqual('New User', session.account('hooch_account').user.name)
    
    def test_create_foreign_relation_with_multiple_specs(self):
        Session.crud.update([self.query_from(self.turner_account), self.query_from(self.hooch_account)], 2 * [{'user': {'name': 'New User'}}])
        with Session() as session:
            self.assertEqual(3, len(session.query(User).all()))
            self.assertEqual('New User', session.account('turner_account').user.name)
            self.assertEqual('New User', session.account('hooch_account').user.name)

    def test_adding_and_removing_tag(self):
        Session.crud.update(self.query_from(self.turner), {'tags': []})
        with Session() as session:
            self.assertFalse(session.user('Turner').tags)
            self.assertEqual(2, session.query(Tag).count())
        
        Session.crud.update(self.query_from(self.turner), {'tags': [{'name': 'New'}]})
        with Session() as session:
            self.assertEqual(3, session.query(Tag).count())
            [new] = session.user('Turner').tags
            self.assertEqual('New', new.name)
    
    def test_removing_tags_with_none(self):
        Session.crud.update(self.query_from(self.turner), {'tags': None})
        with Session() as session:
            self.assertFalse(session.user('Turner').tags)
            self.assertEqual(2, session.query(Tag).count())

    def test_editing_account_from_user(self):
        Session.crud.update(self.query_from(self.turner), {
            'employees': [{
                'username': 'turner_account',
                'password': 'newpass'
            }]
        })
        with Session() as session:
            self.assertEqual(2, session.query(Account).count())
            self.assertEqual('newpass', session.account('turner_account').password)

    def test_unset_nullable_foreign_relation(self):
        Session.crud.update(self.query_from(self.turner_account), {'boss': None})
        with Session() as session:
            self.assertEqual(1, session.query(Boss).count())
            self.assertIs(None, session.account('turner_account').boss)

    def test_unset_nullable_foreign_relation_from_parent_with_none(self):
        Session.crud.update(self.query_from(self.boss), {'employees': None})
        with Session() as session:
            self.assertEqual(1, session.query(Boss).count())
            self.assertIs(None, session.account('turner_account').boss)

    def test_unset_nullable_foreign_relation_from_parent_with_empty_list(self):
        Session.crud.update(self.query_from(self.boss), {'employees': []})
        with Session() as session:
            self.assertEqual(1, session.query(Boss).count())
            self.assertIs(None, session.account('turner_account').boss)

    def test_update_nonexistent_attribute(self):
        self.assertRaises(Exception, Session.crud.update, self.query_from(self.turner), {'does_not_exist': 'foo'})

    def test_update_nonupdatable_attribute(self):
        self.assertRaises(Exception, Session.crud.update, self.query_from(self.turner_account), {'username': 'foo'})


class TestCrudDelete(CrudTests):
    @skip('sqlite is not compiled with foreign key support on Jenkins; this test works on my machine but not on Jenkins')
    def test_delete_cascades_to_tags(self):
        Session.crud.delete(self.query_from(self.turner_account))
        Session.crud.delete(self.query_from(self.turner))
        with Session() as session:
            self.assertEqual(1, session.query(Account).count())
            self.assertEqual(2, session.query(Tag).count())

    def test_delete_by_id(self):
        Session.crud.delete({'_model': 'Account', 'field': 'id', 'value': self.turner_account['id']})
        with Session() as session:
            self.assertEqual(1, session.query(Account).count())
            self.assertRaises(Exception, session.account, 'turner_account')

    def test_multiple_deletes_by_id(self):
        Session.crud.delete([
            {'_model': 'Account', 'field': 'username', 'value': 'turner_account'},
            {'_model': 'Tag', 'field': 'name', 'value': 'Pirate'}
        ])
        with Session() as session:
            self.assertEqual(3, session.query(Tag).count())
            self.assertEqual(1, session.query(Account).count())
            self.assertRaises(Exception, session.account, 'turner_account')

    def test_empty_delete(self):
        self.assertEqual(0, Session.crud.delete([]))

    def test_delete_without_results(self):
        self.assertEqual(0, Session.crud.delete({'_model': 'Account', 'field': 'username', 'value': 'does_not_exist'}))

    def test_non_single_delete(self):
        self.assertRaises(CrudException, Session.crud.delete, {'_model': 'Account'})
        self.assertRaises(CrudException, Session.crud.delete, {'_model': 'Tag', 'field': 'name', 'value': 'Male'})


class TestCrudCreate(CrudTests):
    def test_basic_create(self):
        Session.crud.create({
            '_model': 'Tag',
            'name': 'New',
            'user_id': self.turner['id']
        })
        with Session() as session:
            self.assertEqual({'New', 'Ninja', 'Male'}, {tag.name for tag in session.user('Turner').tags})

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
            self.assertEqual('new', new.username)
            self.assertEqual('New', new.user.name)
            self.assertEqual({'Recent', 'Male'}, {tag.name for tag in new.user.tags})

    def test_duplicate_create(self):
        self.assertRaises(CrudException, Session.crud.create, {'_model': 'User', 'name': 'Turner'})

    def test_create_two_objects(self):
        Session.crud.create([{
            '_model': 'Boss',
            'name': 'NewCo'
        }, {
            '_model': 'User',
            'name': 'New Guy'
        }])
        with Session() as session:
            self.assertEqual(3, session.query(User).count())
            self.assertEqual(2, session.query(Boss).count())

    def test_handle_bad_spec_no_model(self):
        self.assertRaises(CrudException, Session.crud.create, {'name': 'Turner'})

    def test_setting_null_on_unnullable_attributes(self):
        self.assertRaises(CrudException, Session.crud.create, {'_model': 'User', 'name': None})

    def test_set_foreign_key_relations_using_string_id(self):
        Session.crud.create({
            '_model': 'Account',
            'user_id': self.turner['id'],
            'username': 'turner_account_other_users',
            'password': 'password'
        })
        with Session() as session:
            self.assertEqual(2, len(session.user('Turner').employees))


class TestCrudValidations(CrudTests):
    def test_length(self):
        self.assertRaises(CrudException, Session.crud.update, {'_model': 'User'}, {'name': ''})
        self.assertRaises(CrudException, Session.crud.update, {'_model': 'User'}, {'name': 'x' * 101})
    
    def test_regex(self):
        self.assertRaises(CrudException, Session.crud.update, {'_model': 'Account'}, {'username': '!@#'})


class TestNormalizeQuery(TestCase):
    def test_one_string(self):
        results = normalize_query('Human')
        self.assertEquals(results, [{'_model':'Human', '_label':'Human'}])
    
    def test_one_string_in_a_list(self):
        results = normalize_query(['Human'])
        self.assertEquals(results, [{'_model':'Human', '_label':'Human'}])
    
    def test_two_strings(self):
        results = normalize_query(['Human', 'Proxy'])
        self.assertEquals(results, [{'_model':'Human', '_label':'Human'}, {'_model':'Proxy', '_label':'Proxy'}])
        results = normalize_query(['Proxy', 'Human'])
        self.assertEquals(results, [{'_model':'Proxy', '_label':'Proxy'}, {'_model':'Human', '_label':'Human'}])

    def test_one_dict(self):
        results = normalize_query({'_model':'Human'})
        self.assertEquals(results, [{'_model':'Human'}])
    
    def test_one_dict_in_a_list(self):
        results = normalize_query([{'_model':'Human'}])
        self.assertEquals(results, [{'_model':'Human'}])
    
    def test_two_dicts(self):
        results = normalize_query([{'_model':'Human'}, {'_model':'Proxy'}])
        self.assertEquals(results, [{'_model':'Human'}, {'_model':'Proxy'}])
        results = normalize_query([{'_model':'Proxy'}, {'_model':'Human'}])
        self.assertEquals(results, [{'_model':'Proxy'}, {'_model':'Human'}])

    def test_or_clause(self):
        results = normalize_query([{'_model':'Human', 'or':[{'_model':'Human', 'field':'nickname', 'value':'Johnny'}, {'_model':'Human', 'field':'nickname', 'value':'Winny'}]}, {'_model':'Proxy'}])
        self.assertEquals(results, [{'_model':'Human', 'or':[{'_model':'Human', 'field':'nickname', 'value':'Johnny'}, {'_model':'Human', 'field':'nickname', 'value':'Winny'}]}, {'_model':'Proxy'}])
    
    def test_and_clause_push_down_supermodel(self):
        results = normalize_query([{'_model':'Human', 'or':[{'field':'nickname', 'value':'Johnny'}, {'field':'nickname', 'value':'Winny'}]}, {'_model':'Proxy'}])
        self.assertEquals(results, [{'_model':'Human', 'or':[{'_model':'Human', 'field':'nickname', 'value':'Johnny'}, {'_model':'Human', 'field':'nickname', 'value':'Winny'}]}, {'_model':'Proxy'}])

    def test_or_clause_no_model(self):
        results = normalize_query([{'or':[{'_model':'Human'}, {'_model':'Human', 'field':'nickname', 'value':'Johnny'}]}, {'_model':'Proxy'}])
        self.assertEquals(results, [{'_model':'Human', 'or':[{'_model':'Human'}, {'_model':'Human', 'field':'nickname', 'value':'Johnny'}]}, {'_model':'Proxy'}])

    def test_and_clause(self):
        results = normalize_query([{'_model':'Human', 'and':[{'_model':'Human', 'field':'nickname', 'value':'Johnny'}, {'_model':'Human', 'field':'nickname', 'value':'Winny'}]}, {'_model':'Proxy'}])
        self.assertEquals(results, [{'_model':'Human', 'and':[{'_model':'Human', 'field':'nickname', 'value':'Johnny'}, {'_model':'Human', 'field':'nickname', 'value':'Winny'}]}, {'_model':'Proxy'}])
        
    def test_and_clause_no_model(self):
        results = normalize_query([{'and':[{'_model':'Human'}, {'_model':'Human', 'field':'nickname', 'value':'Johnny'}]}, {'_model':'Proxy'}])
        self.assertEquals(results, [{'_model':'Human', 'and':[{'_model':'Human'}, {'_model':'Human', 'field':'nickname', 'value':'Johnny'}]}, {'_model':'Proxy'}])
    
    def test_fails_or_clause_list_of_lists(self):
        self.assertRaises(ValueError, normalize_query, [{'or':[[], []]}, {'_model':'Proxy', '_label':'Proxy'}])
    
    def test_fails_none(self):
        self.assertRaises(ValueError, normalize_query, None)
    
    def test_fails_list_of_lists(self):
        self.assertRaises(ValueError, normalize_query, [[], []])
    
    def test_fails_one_empty_dict(self):
        self.assertRaises(ValueError, normalize_query, {})
    
    def test_fails_one_dict_no_model(self):
        self.assertRaises(ValueError, normalize_query, {'field':'nickname', 'value':'Johnny'})
    
    def test_fails_one_empty_dict_in_a_list(self):
        self.assertRaises(ValueError, normalize_query, [{}])
    
    def test_fails_one_dict_no_model_in_a_list(self):
        self.assertRaises(ValueError, normalize_query, [{'field':'nickname', 'value':'Johnny'}])
    
    def test_fails_two_dicts_one_without_model(self):
        self.assertRaises(ValueError, normalize_query, [{'_model':'Proxy'}, {'field':'nickname', 'value':'Johnny'}])
    
    def test_fails_and_clause_no_model(self):
        self.assertRaises(ValueError, normalize_query, [{'and':[{'field':'nickname', 'value':'Johnny'}, {'field':'nickname', 'value':'Winny'}]}, {'_model':'Proxy'}])
    
    def test_fails_or_clause_no_model(self):
        self.assertRaises(ValueError, normalize_query, [{'or':[{'field':'nickname', 'value':'Johnny'}, {'field':'nickname', 'value':'Winny'}]}, {'_model':'Proxy'}])
    
    def test_fails_and_clause_list_of_lists(self):
        self.assertRaises(ValueError, normalize_query, [{'and':[[], []]}, {'_model':'Proxy'}])
        
    def test_fails_and_clause_with_model_list_of_lists(self):
        self.assertRaises(ValueError, normalize_query, [{'_model':'Human', 'and':[[], []]}, {'_model':'Proxy'}])
    
    def test_fails_or_clause_with_model_list_of_lists(self):
        self.assertRaises(ValueError, normalize_query, [{'_model':'Human', 'or':[[], []]}, {'_model':'Proxy'}])


class TestCollectModels(SideboardTest):
    Session = Session

    def assert_models(self, *args):
        expected_models = set(args[:-1])
        actual_models = Session.crud._collect_models(args[-1])
        self.assertItemsEqual(expected_models, actual_models)

    def test_single(self):
        self.assert_models(User, {'_model': 'User'})

    def test_multiple(self):
        self.assert_models(User, Account, [{'_model': 'User'}, {'_model': 'Account'}])

    def test_foreign_key(self):
        self.assert_models(Account, User, {'_model': 'Account', 'field': 'user.name'})
    
    def test_nested_keys(self):
        self.assert_models(Account, User, Tag, {'_model': 'Account', 'field': 'user.name.tags'})


class TestWebsocketsCrudSubscriptions(SideboardServerTest):
    Session = Session
    
    def setUp(self):
        SideboardServerTest.setUp(self)
        self.ws.close()
        self.ws = self.open_ws()
        self.client = self._testMethodName

        class MockCrud:
            pass

        mr = self.mr = MockCrud()
        for name in ['create', 'update', 'delete']:
            setattr(mr, name, Session.crud.crud_notifies(self.make_crud_method(name), delay=0.5))
        for name in ['read', 'count']:
            setattr(mr, name, Session.crud.crud_subscribes(self.make_crud_method(name)))
        self.override('crud', mr)

    def make_crud_method(self, name):
        def crud_method(*args, **kwargs):
            log.debug('mocked crud.{}'.format(name))
            assert not getattr(self.mr, name + '_error', False)
            return uuid.uuid4().hex

        crud_method.__name__ = name.encode('utf-8')
        return crud_method

    def models(self, *models):
        return [{'_model': model} for model in models]

    def read(self, *models):
        self.ws._send(method='crud.read', client=self.client, params=self.models(*models))
        self.assert_incoming(trigger='subscribe')

    def update(self, *models, **kwargs):
        client = kwargs.get('client', 'unique_client_' + uuid.uuid4().hex)
        self.ws._send(method='crud.update', client=client, params=self.models(*models))
        self.assert_incoming(client=client)

    def test_get_models(self):
        assertModels = lambda xs, models: self.assertItemsEqual(xs, Session.crud._get_models(models))

        assertModels([], 0)
        assertModels([], {})
        assertModels([], [])
        assertModels([], '')
        assertModels([], None)
        assertModels([], {'_model': 0})
        assertModels([], {'_model': {}})
        assertModels([], {'_model': []})
        assertModels([], {'_model': None})

        assertModels(['User'], {'_model': 'User'})
        assertModels(['User'], [{'_model': 'User'}])
        assertModels(['User'], ({'_model': 'User'},))
        assertModels(['User'], {'foo': {'_model': 'User'}})

    def test_read(self):
        self.read('User')
        self.assert_no_response()

    def test_triggered_read(self):
        self.read('User')
        self.update('User')
        self.assert_incoming(trigger='update')

    def test_unsubscribe(self):
        self.test_triggered_read()
        self.unsubscribe()
        self.update('User')
        self.assert_no_response()

    def test_triggered_error(self):
        self.mr.update_error = True
        with self.open_ws() as other_ws:
            other_ws._send(method='crud.read', client='other_tte', params=self.models('User'))
            self.assert_incoming(other_ws, client='other_tte')
            self.update('User')
            self.ws._send(method='crud.update', client=self.client, params=self.models('User'))
            self.assertIn('error', self.next())
            self.assert_incoming(other_ws, client='other_tte', trigger='update')

    def test_indirect_trigger(self):
        def account(*attrs):
            if len(attrs) == 1:
                return {'_model': 'Account', 'field': attrs[0]}
            else:
                return {'_model': 'Account',
                        'or': [{'field': attr} for attr in attrs]}

        def call(*attrs):
            self.call(method='crud.read', client=self.client, params=account(*attrs))

        def assert_update_triggers(model):
            self.update(model)
            self.assert_incoming()

        call('xxx')
        assert_update_triggers('Account')
        self.unsubscribe()

        call('user.xxx')
        assert_update_triggers('User')
        assert_update_triggers('Account')
        self.unsubscribe()

        call('user.xxx', 'boss.xxx')
        assert_update_triggers('Account')
        assert_update_triggers('User')
        assert_update_triggers('Account')
        self.unsubscribe()

        call('user.tags.xxx')
        assert_update_triggers('Account')
        assert_update_triggers('User')
        assert_update_triggers('Tag')

        self.update('Boss')
        self.assert_no_response()

    def test_trigger_and_callback(self):
        result = self.call(method='crud.read', params=self.models('User'), client='ds_ttac')
        self.assert_no_response()

    def test_multiple_triggers(self):
        self.read('User', 'Boss')
        self.update('User')
        self.assert_incoming()
        self.update('Boss')
        self.assert_incoming()
        self.update('Account')
        self.assert_no_response()

    def test_trigger_changed(self):
        self.read('User')
        self.read('Boss')
        self.update('User')
        self.assert_no_response()
        self.update('Boss')
        self.assert_incoming()
        self.assert_no_response()

    def test_multiple_clients(self):
        self.read('Boss')
        self.ws._send(method='crud.read', client='other_tmc', params=self.models('Boss'))
        self.assert_incoming(client='other_tmc')
        self.update('User')
        self.assert_no_response()
        self.read('Boss')
        self.ws._send(method='crud.update', client='unused_client', params=self.models('Boss'))
        self.next()
        self.assertEqual({self.client, 'other_tmc'},
                         {self.next()['client'], self.next()['client']})

    def test_broadcast_error(self):
        with self.open_ws() as other_ws:
            self.read('User')
            other_ws._send(method='crud.count', client='other_tbe', params=self.models('User'))
            self.assert_incoming(other_ws, client='other_tbe')
            self.mr.count_error = True
            self.update('User', client='other_client_so_everything_will_trigger')
            self.assert_incoming(trigger='update', timeout=5)

    def test_jsonrpc_notifications(self):
        self.read('User')
        self.jsonrpc.crud.delete({'_model': 'User', 'field': 'name', 'value': 'Does Not Exist'})
        self.assert_incoming(trigger='delete')

        self.jsonrpc._prepare_request = lambda data, headers: data.update({'websocket_client': self.client})
        self.jsonrpc.crud.delete({'_model': 'User', 'field': 'name', 'value': 'Does Not Exist'})
        self.assert_no_response()


class TestCrudableClass(TestCase):
    maxDiff = None
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
                'type': "auto",
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
        self.assertEquals(self.expected_crud_spec, CrudableClass._crud_spec)
    
    def test_basic_crud_spec(self):
        expected_basic = {'fields': {k: self.expected_crud_spec['fields'][k] 
                                     for k in ('id', 'mixed_in_attr', 'extra_data')}}
        self.assertEquals(expected_basic, BasicClassMixedIn._crud_spec)

    def test_handle_no_crud_spec_attribute(self):
        with self.assertRaises(AttributeError):
            object._crud_spec


class TestCollectAncestorClasses(TestCase):
    def test_collect_ancestor_classes(self):
        classes = collect_ancestor_classes(Account)
        for cls in [Account, Base, object]:
            self.assertIn(cls, classes)

        classes = collect_ancestor_classes(Account, object)
        for cls in [Account, Base]:
            self.assertIn(cls, classes)
        for cls in [object]:
            self.assertNotIn(cls, classes)

        classes = collect_ancestor_classes(Account, Base)
        for cls in [Account]:
            self.assertIn(cls, classes)
        for cls in [Base, object]:
            self.assertNotIn(cls, classes)
