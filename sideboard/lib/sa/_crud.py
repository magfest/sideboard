"""
The crud module defines a number of functions for finding SQLAlchemy model objects via a query parameter and displaying a desired portion of the resulting object graph via a data specification parameter, optionally limiting the total number returned, potentially with an offset to support paging


QUERY PARAMETER
---------------
The format of the query parameter needs to support logical operators and a certain amount of introspection into which model objects are involved in a give query. For this writeup, a "query" is any set of search parameters that will result in a known SQL search string capable of returning the desired model objects. Python syntax will be used to represent the expected format of the method parameters, with allowances for representing infinite nesting/lists as appropriate. Unless explicitly stated, pluralized forms like "queries" can be read as "query or queries" due to the support of one or more queries in all cases

The comprehensive form of the query parameter is as follows:

query = [{
    '_model': <model_name>,
    '_data': <data_specification>,
    '_label': <query_label>,
    # Either provide <logical_operator> OR the items after <logical_operator>
    <logical_operator>: [<query>[, <query>]*],
    # used IF AND ONLY IF <logical_operator> is not provided
    'comparison': <comparison_function>
    'field': <model_field_name>,
    'value': <model_field_value>
}]+

meaning an array of one or more dictionaries (a dictionary is equivalent to an array of length 1) of queries, one for each type of SQLAlchemy model object expected to be returned

where:
- '<model_name>' - the string corresponding to the SQLAlchemy model class name which extends your @sideboard.lib.sa.declarative_base
- '<query_label>' - the optional string that signifies the purpose of this query and is only used as a convenience for the consumer of the crud method. This primarily supports counts, but can used in client code to help cue the display of those results, defaults to the contents of _model
- '<logical_operator>' - the key is one of the following logical operators (with the value being one of more queries in a list):
-- and ("intersection")
-- or ("union")
--- meaning that the results of the provided queries will be the corresponding intersection/union of all the results of an individual query. Imagining a Venn Diagram is useful in this instance.
- <query> - is a dictionary identical the dictionary taken in by the query parameter EXCEPT that _model is not included
- <comparison> - a comparison operator function used to find the objects that would return "True" for the provided comparison for the value in the model_field_name. Some examples are:
-- 'lt' - is the field less than value?
-- 'gt' - is the field greater than value?
-- 'eq' - is the field equal to value? (default)
-- 'ne' - is the field not equal value?
-- 'le' - is the field less than or equal to value?
-- 'ge' - is the field greater than or equal to value?
-- 'isnull' - does the field have a null value? (does not use the query's value parameter)
-- 'isnotnull' - does the field have a non null value? (does not use the query's value parameter)
-- 'in' - does the field appear in the given value? (value should be an array)
-- 'contains' - does the field contain this value? (would allow other characters before or after the value)
-- 'like' - same as contains, but case sensitive
-- 'ilike' - same as contains, case insensitive
-- 'startswith' - does the field start with value?
-- 'istartswith' - case insensitive startswith
-- 'endswith' - does the field end with value?
-- 'iendswith' - case insensitive endswith

- <model_field_name> - the name of the field for the provided _model at the top level. Supports dot notation, e.g.:
-- making a comparison based off all of a Team's players' names would use an 'field' of 'player.name'
- <model_field_value> - the value that the field comparison will be made against, e.g. a value of 'text' and a comparison of 'eq' will return all matching models with fields equal to 'text'.
- <data_specification> - specifying what parts of the results get returned, the following section covers the format the data specification parameter


DATA SPECIFICATION
------------------
Where the query parameter is only used to search existing objects in the database, the data specification parameter has two separate meanings: in the 'read' function as the _data key in the query dictionary: what information is returned in the results, in the 'update' and 'create' functions, what model type will be created/updated with what values. This is encompassed in one format, so there is some amount of redundancy depending on what actions you're performing.

The comprehensive form of the data specification parameter is as follows:

data = [{
    '_model': <model_name>,
    # a non-foreign key field
    '<model_field_name>': True (or the value of the field if the data parameter is used to create or update objects)
    # a foreign key field is a special case and additional forms are supported)
    '<foreign_key_model_field_name>': True (all readable fields of the reference model object will be read. Has no meaning if the data parameter is used to create of update objects)
    '<foreign_key_model_field_name>': {<same form as the data parameter, e.g., supports recursion}
}] +

meaning an array of one or more dictionaries (a dictionary is equivalent to an array of length 1) of data specification, one for each type of LDAP model object expected to be returned. As a special case for the 'read' method, one dictionary is interpreted as being the intended data spec for each item in the query parameter array. In the 'update' array, the length of the query and data parameters must match and the nth member of both the query and data array are read together as a matched set. In the 'create' method, each member of the data array will create a new object of the type specified in _model.

a supported short form of a data specification is, instead of a dictionary of key names with values, a list of key names that should be read:

['<model_field_name_1',
 '<model_field_name_2',
 '<model_field_name_3']

is equivalent to:

{'<model_field_name_1': True,
 '<model_field_name_2': True,
 '<model_field_name_3': True}

As you can see, that this short form would not be appropriate for create or updates function calls, as there's no way to specify the desired values. Additionally there's no way to specify a sub-object graph for a followed foreign key.


RESULTS FOR crud.count
----------------------
The crud.count method accepts a query parameter (format examined above) and returns a count of each of the supplied queries (typically, this is a count of each supplied model type), however the results also include a _label key, that can be used to differentiate between two different types of results within the same model type (e.g. enabled accounts vs disabled accounts)

e.g.:

return [{
    _model : 'Team',
    _label: 'Team',
    count : 12
}, {
    _model : 'Player',
    _label : 'Players on a Team',
    count : 144
}, {
    _model : 'Manager',
    _label : 'Managers of a Team',
    count : 12
}, {
    _model : 'LeagueEmployee',
    _label : 'Everyone employed by the league (e.g. Players, Managers)',
    count : 156
}]


RESULTS FOR crud.read
---------------------
The crud.read method accepts both a query and data specification parameter (format examined above), and two parameters for fine-tuning which specific results are returned (examined in the upcoming "Fine-Tuning Read Results" section. The read method returns the total number of objects matching the query (separate from any sort of limits) and a list of the specific objects requested (subject to those limits) e.g.

return {
    total: 20 # count of ALL matching objects
    # although only 5 results were returned as a result of the specified fine-tuning parameters
    results: [<result>, <result>, <result>, <result>, <result>]
}

To prevent the client from always being forced to deal with entire query result, there are three parameters in place for the crud.read method to simplify only receiving the information that's desired. At a high level:

- 'Limit' takes a positive integer 'L' and when provided, the crud.read method will return at most L results, defaults to no limit
- 'Ordering' takes a list of ordering specification dictionaries for sorting by specific fields and in a specified direction (ascending or descending), defaults to no reordering after being returned from the database
- 'Offset' takes a positive integer 'F' and when provided, the crud.read method will return at most L results, after skipping the first (based on the ordering specification) F results.

Used with the crud.read method to only return only a subset of information, allowing the client to only receive the amount of information it's interested in. Useful in conjunction with the offset and ordering parameter to finely-tune the information received.

The comprehensive form of the ordering parameter is as follows:

ordering = [{
    'dir': <'asc'/'desc'> # either in ascending (default) or descending order
    'fields': [['<model_object_name>.]<model_field_name>']+
}] +

A single string in 'fields' is equivalent to a list with the string as the only element. If no model_object name is provided, the model_field_name is interpreted as the catch-all key for all model objects. If model_field_name isn't present on a model, or no catch-all is specified, 'id' will be used

The list of dictionaries are interpreted as being ordered in decreasing priority. An example:

The 'offset' parameter is used with the crud.read method to only return only a subset of information, allowing the client to only receive the amount of information it's interested in. Useful in conjunction with the limit and ordering parameter to finely-tune the information received.

Using the 4 records in the ordering example (including the ordering specification):
- a limit of 1 with an offset of 0 (the default if unspecified) would return only the John Depp Human.
- a limit of 0 (unlimited, which is the default if unspecified) and an offset of 0 would be identical to the table in the ordering-only example
- a limit of 0 and an offset of 1 would return everything except for the first result, so in this case, the last 3 results
- a limit of 2 and an offset of 1 would return the 2nd and 3rd results, so in this case, the middle 2 results
"""
from __future__ import unicode_literals
import functools
import re
import sys
import json
import uuid
import inspect
import collections
from copy import deepcopy
from collections import Mapping, defaultdict
from datetime import datetime, date, time
from itertools import chain
from functools import wraps

from sqlalchemy import orm
from sqlalchemy.orm.mapper import Mapper
from sqlalchemy import union, select, func
from sqlalchemy.orm.util import class_mapper
from sqlalchemy.schema import UniqueConstraint
from sqlalchemy.sql import text, ClauseElement
from sqlalchemy.orm.attributes import InstrumentedAttribute
from sqlalchemy.orm.exc import NoResultFound, MultipleResultsFound
from sqlalchemy.orm.properties import ColumnProperty, RelationshipProperty
from sqlalchemy.types import Boolean, Text, Integer, String, UnicodeText, DateTime
from sqlalchemy.sql.expression import alias, cast, label, bindparam, and_, or_, asc, desc, literal, text, union, join

from sideboard.lib import log, notify, listify, threadlocal, serializer, is_listy


class CrudException(Exception):
    pass


def listify_with_count(x, count=None):
    x = listify(x)
    if count and len(x) < count:
        x.extend([None for i in range(count - len(x))])
    return x


def mappify(value):
    if isinstance(value, basestring):
        return {value: True}
    elif isinstance(value, collections.Mapping):
        return value
    elif isinstance(value, collections.Iterable):
        return {v: True for v in value}
    else:
        raise TypeError('unknown datatype: {}', value)


def generate_date_series(startDate=None, endDate=None, interval='1 month', granularity='day'):
    if granularity:
        granularity = '1 %s'%granularity
    else:
        granularity = '1 day'
    
    generate_series = None
    if startDate:
        if endDate:
            # If the startDate and the endDate are defined then we use those
            generate_series = func.generate_series(startDate, endDate, granularity)
        elif interval:
            # If the startDate and the interval are defined then we use those
            generate_series = func.generate_series(startDate, 
                text("DATE :start_date_param_1 + INTERVAL :interval_param_1",
                     bindparams=[
                         bindparam("start_date_param_1",startDate), 
                         bindparam("interval_param_1",interval)]),
                granularity)
        else:
            # If ONLY the startDate is defined then we just use that
            generate_series = func.generate_series(startDate, datetime.utcnow(), granularity)
    elif endDate:
        if interval:
            # If the endDate and the interval are defined then we use those
            generate_series = func.generate_series(
                 text("DATE :current_date_param_1 - INTERVAL :interval_param_1",
                     bindparams=[
                         bindparam("current_date_param_1",endDate), 
                         bindparam("interval_param_1",interval)]),
                 endDate, granularity)
        else:
            # If ONLY the endDate is defined then we just use that
            generate_series = func.generate_series(
                 text("DATE :current_date_param_1 - INTERVAL :interval_param_1",
                     bindparams=[
                         bindparam("current_date_param_1",endDate), 
                         bindparam("interval_param_1","1 month")]),
                 endDate, granularity)
    elif interval:
        # If ONLY the interval is defined then we default to the current date
        # minus the interval
        generate_series = func.generate_series(
             text("DATE :current_date_param_1 - INTERVAL :interval_param_1",
                 bindparams=[
                     bindparam("current_date_param_1",datetime.utcnow()), 
                     bindparam("interval_param_1",interval)]),
             datetime.utcnow(), granularity)
    else:
        # If NOTHING is defined then we return the query unmodified
        generate_series = func.generate_series(
             text("DATE :current_date_param_1 - INTERVAL :interval_param_1",
                 bindparams=[
                     bindparam("current_date_param_1",datetime.utcnow()), 
                     bindparam("interval_param_1","1 month")]),
             datetime.utcnow(), granularity)
        
    return generate_series


def normalize_date_query(query, dateLabel, reportLabel, startDate=None, endDate=None, interval='1 month', granularity='day'):
    series = generate_date_series(startDate, endDate, interval, granularity)
    seriesQuery = select([
        series.label(dateLabel),
        literal(0).label(reportLabel)
    ])
    
    query = union(query, seriesQuery).alias()
    query = select([
        text(dateLabel), 
        func.max(text(reportLabel)).label(reportLabel)
    ], from_obj=query).group_by(dateLabel).order_by(dateLabel)
    
    return query


def normalize_object_graph(graph):
    """
    Returns a normalized object graph given a variety of different inputs.
    
    If graph is a string, we assume it is a single property of an object,
    and return a dict with just that property set to True.
    
    If graph is a dict, we assume it is already a normalized graph.
    
    If graph is iterable (and not a string), we assume that it's simple a
    list of properties, and we return a dict with those properties set to 
    True.
    
    NOTE: This function is NOT recursive. It is intended to be repeatedly
    called from an external library as it traverses the object graph. We do
    this for performance reasons in case the caller decides not to traverse 
    the entire graph.
    
    >>> normalize_object_graph('prop')
    {u'prop': True}
    
    >>> normalize_object_graph(['prop_one', 'prop_two'])
    {'prop_two': True, 'prop_one': True}
    
    >>> normalize_object_graph({'prop_one':'test_one', 'prop_two':'test_two'})
    {u'prop_two': u'test_two', u'prop_one': u'test_one'}
    """
    if isinstance(graph, basestring):
        return {graph:True}
    elif isinstance(graph, dict):
        return graph
    elif isinstance(graph, collections.Iterable):
        return dict([(str(i), True) for i in graph])
    else:
        return None


def collect_ancestor_classes(cls, terminal_cls=None, module=None):
    """
    Collects all the classes in the inheritance hierarchy of the given class, 
    including the class itself.
     
    If module is an object or list, we only return classes that are in one 
    of the given module/modules.This will exclude base classes that come 
    from external libraries.
    
    If terminal_cls is encountered in the hierarchy, we stop ascending 
    the tree.
    """
    if terminal_cls is None:
        terminal_cls = []
    elif not isinstance(terminal_cls, (list, set, tuple)):
        terminal_cls = [terminal_cls]
    
    if module is not None:
        if not isinstance(module, (list, set, tuple)):
            module = [module]
        module_strings = []
        for m in module:
            if isinstance(m, basestring):
                module_strings.append(m)
            else:
                module_strings.append(m.__name__)
        module = module_strings
    
    ancestors = []
    if (module is None or cls.__module__ in module) and cls not in terminal_cls:
        ancestors.append(cls)
        for base in cls.__bases__:
            ancestors.extend(collect_ancestor_classes(base, terminal_cls, module))
    
    return ancestors


def collect_ancestor_attributes(cls, terminal_cls=None, module=None):
    """
    Collects all the attribute names of every class in the inheritance
    hierarchy of the given class, including the class itself.
    """
    classes = collect_ancestor_classes(cls, terminal_cls, module)
    attr_names = []
    for cls in classes:
        for attr_name in cls.__dict__.keys():
            attr_names.append(attr_name)
    return list(set(attr_names))


def constrain_date_query(query, column, startDate=None, endDate=None, interval='1 month'):
    if startDate:
        if endDate:
            # If the startDate and the endDate are defined then we use those
            query = query.where(and_(column >= startDate, column <= endDate))
            return query
        elif interval:
            # If the startDate and the interval are defined then we use those
            query = query.where(and_(
                column >= startDate, 
                column <= text("DATE :start_date_param_1 + INTERVAL :interval_param_1",
                     bindparams=[
                         bindparam("start_date_param_1",startDate), 
                         bindparam("interval_param_1",interval)])))
            return query
        else:
            # If ONLY the startDate is defined then we just use that
            query = query.where(column >= startDate)
            return query
    elif endDate:
        if interval:
            # If the endDate and the interval are defined then we use those
            query = query.where(and_(
                column <= endDate, 
                column >= text("DATE :end_date_param_1 - INTERVAL :interval_param_1",
                     bindparams=[
                         bindparam("end_date_param_1",endDate), 
                         bindparam("interval_param_1",interval)])))
            return query
        else:
            # If ONLY the endDate is defined then we just use that
            query = query.where(column <= endDate)
            return query
    elif interval:
        # If ONLY the interval is defined then we default to the current date
        # minus the interval
        query = query.where(and_(
            column >= text("DATE :current_date_param_1 - INTERVAL :interval_param_1",
                 bindparams=[
                     bindparam("current_date_param_1",datetime.utcnow()), 
                     bindparam("interval_param_1",interval)])))
        return query
    else:
        # If NOTHING is defined then we return the query unmodified
        return query
    

def extract_sort_field(model, value):
    field = None
    fields = listify(value)
    for f in fields:
        if isinstance(f, basestring):
            parts = f.split('.')
            if len(parts) == 1 and field is None:
                if not model or (model and hasattr(model, parts[0])):
                    field = parts[0]
            elif len(parts) > 1 and model and parts[0] == model.__name__:
                field = parts[1]
        else:
            field = f
    
    if field and isinstance(field, basestring) and model:
        attr = getattr(model, field)
        if (not (isinstance(attr, InstrumentedAttribute) and isinstance(attr.property, ColumnProperty)) and 
            not isinstance(attr, ClauseElement)):
            raise ValueError('SQLAlchemy model classes may only be sorted '
                             'by columns that exist in the database. '
                             'Provided: {}.{}'.format(model.__name__, field))
    return field or 'id'


def normalize_sort(model, sort):
    if sort and isinstance(sort, basestring) and (sort.lstrip()[0] == '[' or sort.lstrip()[0] == '{'):
        sort = json.loads(sort)
    
    if isinstance(sort, basestring):
        return [{'field':extract_sort_field(model, sort), 'dir':'asc'}]
    elif is_listy(sort):
        sorters = []
        for s in sort:
            sorters.extend(normalize_sort(model, s)) 
        return sorters
    elif isinstance(sort, dict):
        field = sort.get('property', sort.get('fields', sort.get('field', [])))
        direction = sort.get('direction', sort.get('dir', 'asc')).lower()
        return [{
            'field':extract_sort_field(model, field), 
            'dir':direction
        }]
    else:
        return [{'field':'id', 'dir':'asc'}]


def normalize_data(data, count=1):
    """
    A singular data can be a string, a list of strings, or a dict:
    'attr'
    ['attr1', 'attr2']
    {'attr1':True, 'attr2':True}
    
    A plural data must be specified as a list of lists or a list of dicts:
    [['attr1', 'attr2'], ['attr1', 'attr2']]
    [{'attr1':True, 'attr2':True}, {'attr1':True, 'attr2':True}]
    
    Note that if data is specified as a list of strings, it is 
    considered to be singular. Only a list of lists or a list of 
    dicts is considered plural.
    
    Returns the plural form of data as the comprehensive form of a list of
    dictionaries mapping <keyname> to True, extended to count length. If a
    singular data is given, the result will be padded by repeating
    that value. If a plural data is given, it will be padded with
    None, for example:
    >>> normalize_data('attr', 1)
    [{'attr': True}]
    >>> normalize_data('attr', 3)
    [{'attr': True}, {'attr': True}, {'attr': True}]
    >>> normalize_data(['attr1', 'attr2'], 1)
    [{'attr2': True, 'attr1': True}]
    >>> normalize_data(['attr1', 'attr2'], 3)
    [{'attr2': True, 'attr1': True}, {'attr2': True, 'attr1': True}, {'attr2': True, 'attr1': True}]
    >>> normalize_data({'attr1':True, 'attr2':True}, 1)
    [{'attr2': True, 'attr1': True}]
    >>> normalize_data({'attr1':True, 'attr2':True}, 3)
    [{'attr2': True, 'attr1': True}, {'attr2': True, 'attr1': True}, {'attr2': True, 'attr1': True}]
    >>> normalize_data([['attr1', 'attr2'], ['attr1', 'attr2']], 1)
    [{'attr2': True, 'attr1': True}, {'attr2': True, 'attr1': True}]
    >>> normalize_data([['attr1', 'attr2'], ['attr1', 'attr2']], 4)
    [{'attr2': True, 'attr1': True}, {'attr2': True, 'attr1': True}, None, None]
    >>> normalize_data([{'attr1':True, 'attr2':True}, {'attr1':True, 'attr2':True}], 1)
    [{'attr2': True, 'attr1': True}, {'attr2': True, 'attr1': True}]
    >>> normalize_data([{'attr1':True, 'attr2':True}, {'attr1':True, 'attr2':True}], 4)
    [{'attr2': True, 'attr1': True}, {'attr2': True, 'attr1': True}, None, None]
    >>> normalize_data([{'attr1':True, 'attr2':True}, ['attr1', 'attr2']], 4)
    [{'attr2': True, 'attr1': True}, {'attr2': True, 'attr1': True}, None, None]
    """
    if not data:
        return listify_with_count(None, count)
    else:
        if isinstance(data, basestring):
            data = [{data:True}]
        elif isinstance(data, collections.Mapping):
            data = [data]
        elif isinstance(data, collections.Iterable):
            if any(isinstance(element, basestring) for element in data):
                # this is the singular list of strings case, so wrap it and
                # go from there
                data = [data]
            #is this a list of strings?
            data = [mappify(v) for v in data]
        else:
            raise TypeError('unknown datatype: {}', data)
        
        if len(data) < count:
            if len(data) == 1:
                data.extend([deepcopy(data[0]) for i in range(count - len(data))])
            else:
                data.extend([None for i in range(count - len(data))])
        return data


def normalize_query(query, top_level=True, supermodel=None):
    """
    Normalizes a variety of query formats to a known standard query format.
    
    The comprehensive form of the query parameter is as follows:
    {code:python}
    query = [{
        '_model': <model_name>,
        '_label': Optional identifier
        # Either provide <logical_operator> OR the items after <logical_operator>
        <logical_operator>: [<query>[, <query>]*],
        # used IF AND ONLY IF <logical_operator> is not provided
        'comparison': <comparison_function>
        'field': <model_field_name>,
        'value': <model_field_value>
    }]+
    {code}
    """
    if query is None:
        raise ValueError('None passed for query parameter')
    
    query = listify(deepcopy(query))
    
    queries = []
    for q in query:
        if isinstance(q, basestring):
            queries.append({'_model':q, '_label':q})
        elif isinstance(q, dict):
            if 'distinct' in q:
                if isinstance(q['distinct'], basestring):
                    q['distinct'] = [q['distinct']]
            if 'groupby' in q:
                if isinstance(q['groupby'], basestring):
                    q['groupby'] = [q['groupby']]
            if 'and' in q or 'or' in q:
                op = 'or'
                if 'and' in q:
                    op = 'and'
                if not isinstance(q[op], (list, set, tuple)):
                    raise ValueError('Clause must be of type list, set, or tuple not {}, given {}'.format(type(q[op]), q[op]))
                q[op] = normalize_query(q[op], False, q.get('_model', supermodel))
                if len(q[op]) == 1:
                    q = q[op][0]
                elif not '_model' in q:
                    # Pull the _model up from the sub clauses. Technically the
                    # query format requires the _model be declared in the 
                    # clause, but we are going to be liberal in what we accept.
                    model = supermodel
                    for clause in q[op]:
                        if '_model' in clause:
                            model = clause['_model']
                            break
                    if model is None:
                        raise ValueError('Clause objects must have a "_model" attribute')
                    q['_model'] = model
            
            if '_model' in q:
                queries.append(q)
            elif supermodel is not None:
                q['_model'] = supermodel
                queries.append(q)
            else:
                raise ValueError('Query objects must have a "_model" attribute')
        else:
            raise ValueError('Query objects must be either a dict or string')
    return queries


def collect_fields(d):
    if 'field' in d:
        return {d['field']}
    elif 'and' in d or 'or' in d:
        attrs = set()
        for comp in ['and', 'or']:
            for subquery in d.get(comp, []):
                attrs.update(collect_fields(subquery))
        return attrs
    elif 'comparison' in d or 'value' in d:
        return {'id'}
    else:
        return d.keys()


def get_queries(x):
    queries = []
    if isinstance(x, (list, tuple)):
        for e in x:
            queries.extend(get_queries(e))
    elif isinstance(x, dict):
        queries.append(x)
        for e in x.values():
            queries.extend(get_queries(e))
    return [d for d in queries if isinstance(d.get("_model"), basestring)]


def crud_exceptions(fn):
    """A decorator designed to catch exceptions from the crud api methods."""
    @wraps(fn)
    def wrapped(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except:
            a = [x for x in (args or [])]
            kw = {k : v for k, v in (kwargs or {}).iteritems()}
            log.error('Error calling {}.{} {!r} {!r}'.format(fn.__module__, fn.__name__, a, kw), exc_info=True)
            exc_class, exc, tb = sys.exc_info()
            raise CrudException, CrudException(str(exc)), tb
    return wrapped


def make_crud_service(Session):

    class Crud(object):
        @staticmethod
        def crud_subscribes(func):
            func = crud_exceptions(func)
            class subscriber(object):
                @property
                def subscribes(self):
                    message = threadlocal.get('message')
                    return Crud._get_models(message.get('params')) if message else []

                def __call__(self, *args, **kwargs):
                    return func(*args, **kwargs)

            return wraps(func)(subscriber())

        @staticmethod
        def crud_notifies(func, **settings):
            func = crud_exceptions(func)
            delay = settings.pop('delay', 0)

            class notifier(object):
                def __call__(self, *args, **kwargs):
                    try:
                        return func(*args, **kwargs)
                    finally:
                        models = Crud._get_models(args, kwargs)
                        notify(models, trigger=func.__name__, delay=delay)

            return wraps(func)(notifier())

        @classmethod
        def _collect_models(cls, query):
            models = set()
            for d in listify(query):
                try:
                    model = Session.resolve_model(d['_model'])
                except:
                    log.debug('unable to resolve model {} in query {}', d.get('_model'), d)
                else:
                    models.add(model)
                    for attr_name in collect_fields(d):
                        curr_model = model
                        for prop_name in attr_name.split('.'):
                            if hasattr(curr_model, prop_name):
                                prop = getattr(curr_model, prop_name)
                                if isinstance(prop, InstrumentedAttribute) and hasattr(prop.property, 'mapper'):
                                    curr_model = prop.property.mapper.class_
                                    models.update([curr_model])
                                    if prop_name in d:
                                        subquery = deepcopy(d[prop_name])
                                        if isinstance(subquery, (list, set, tuple)) and not filter(lambda x: isinstance(x, dict), subquery):
                                            subquery = {i: True for i in subquery}
                                        elif isinstance(subquery, basestring):
                                            subquery = {subquery: True}
                                        if isinstance(subquery, dict):
                                            subquery['_model'] = curr_model.__name__
                                        models.update(cls._collect_models(subquery))
                            else:
                                break
            return models

        @classmethod
        def _get_models(cls, *args, **kwargs):
            return {model.__name__ for model in cls._collect_models(get_queries([args, kwargs]))}

        @classmethod
        def _sort_query(cls, query, model, sort):
            sort = normalize_sort(model, sort)
            for sorter in sort:
                dir = {'asc':asc, 'desc':desc}[sorter['dir']]
                field = sorter['field']
                if model:
                    field = getattr(model, field)
                    if issubclass(type(field.__clause_element__().type), String):
                        field = func.lower(field)
                query = query.order_by(dir(field))
            return query

        @classmethod
        def _limit_query(cls, query, limit, offset):
            if offset is not None:
                query = query.offset(offset)
            if limit is not None and limit != 0:
                query = query.limit(limit)
            return query

        # this only works in postgresql
        @classmethod
        def _distinct_query(cls, query, filters):
            distinct_clause = filters.get('distinct', None)
            if distinct_clause:
                if isinstance(distinct_clause, bool):
                    query = query.distinct()
                else:
                    model = Session.resolve_model(filters.get('_model'))
                    columns = [getattr(model, field) for field in distinct_clause]
                    query = query.distinct(*columns)
            return query

        @classmethod
        def _groupby_query(cls, query, filters):
            groupby_clause = filters.get('groupby', None)
            if groupby_clause:
                model = Session.resolve_model(filters.get('_model'))
                columns = [getattr(model, field) for field in groupby_clause]
                query = query.group_by(*columns)
            return query

        @classmethod
        def _filter_query(cls, query, model, filters=None, limit=None, offset=None, sort=None):
            if filters:
                query = cls._distinct_query(query, filters)
                query = cls._groupby_query(query, filters)
                filters = cls._resolve_filters(filters, model)
                if filters is not None:
                    query = query.filter(filters)
            if sort:
                query = cls._sort_query(query, model, sort)
            query = cls._limit_query(query, limit, offset)
            return query

        @classmethod
        def _resolve_comparison(cls, comparison, column, value):
            if isinstance(value, dict):
                model_class = Session.resolve_model(value.get('_model'))
                field = value.get('select', 'id')
                value = select([getattr(model_class, field)], cls._resolve_filters(value))

            return {
                'eq': lambda field, val : field == val,
                'ne': lambda field, val : field != val,
                'lt': lambda field, val : field < val,
                'le': lambda field, val : field <= val,
                'gt': lambda field, val : field > val,
                'ge': lambda field, val : field >= val,
                'in': lambda field, val : field.in_(val),
                'notin':lambda field, val : ~field.in_(val),
                'isnull' : lambda field, val : field == None,
                'isnotnull' : lambda field, val : field != None,
                'contains': lambda field, val : field.like('%'+val+'%'),
                'icontains': lambda field, val : field.ilike('%'+val+'%'),
                'like': lambda field, val : field.like('%'+val+'%'),
                'ilike': lambda field, val : field.ilike('%'+val+'%'),
                'startswith': lambda field, val : field.startswith(val),
                'endswith': lambda field, val : field.endswith(val),
                'istartswith': lambda field, val : field.ilike(val+'%'),
                'iendswith': lambda field, val : field.ilike('%'+val)
            }[comparison](column, value)

        @classmethod
        def _resolve_filters(cls, filters, model=None):
            model = Session.resolve_model(filters.get('_model', model))
            table = class_mapper(model).mapped_table
            and_clauses = filters.get('and', None)
            or_clauses = filters.get('or', None)
            if and_clauses:
                return and_(*[cls._resolve_filters(c, model) for c in and_clauses])
            elif or_clauses:
                return or_(*[cls._resolve_filters(c, model) for c in or_clauses])
            elif 'field' in filters or 'value' in filters or 'comparison' in filters:
                field = filters.get('field', 'id').split('.')
                value = filters.get('value')
                comparison = filters.get('comparison', 'eq')

                if len(field) == 1:
                    column = getattr(model, field[0])
                    return cls._resolve_comparison(comparison, column, value)
                elif len(field) == 2:
                    property = field[0]
                    field = field[1]
                    related_table = class_mapper(model).get_property(property)
                    related_model = related_table.argument
                    if isinstance(related_model, Mapper):
                        related_model = related_model.class_
                    elif callable(related_model):
                        related_model = related_model()
                    related_field = getattr(related_model, field)

                    clause = cls._resolve_comparison(comparison, related_field, value)
                    if getattr(related_table, 'primaryjoin', None) is not None:
                        clause = and_(
                            clause,
                            related_table.primaryjoin)
                    if getattr(related_table, 'secondaryjoin', None) is not None:
                        clause = and_(
                            clause,
                            related_table.secondaryjoin)
                    return clause
                else:
                    property = field[0]
                    join_property = field[1]
                    field = field[2]

                    join_table = class_mapper(model).get_property(property)
                    join_model = join_table.argument

                    if isinstance(join_model, Mapper):
                        join_model = join_model.class_
                    elif callable(join_model):
                        join_model = join_model()

                    related_table = class_mapper(join_model).get_property(join_property)
                    related_model = related_table.argument
                    if isinstance(related_model, Mapper):
                        related_model = related_model.class_
                    elif callable(related_model):
                        related_model = related_model()
                    related_field = getattr(related_model, field)

                    clause = cls._resolve_comparison(comparison, related_field, value)
                    if getattr(join_table, 'primaryjoin', None) is not None:
                        clause = and_(
                            clause,
                            join_table.primaryjoin)
                    if getattr(join_table, 'secondaryjoin', None) is not None:
                        clause = and_(
                            clause,
                            join_table.secondaryjoin)

                    if getattr(related_table, 'primaryjoin', None) is not None:
                        clause = and_(
                            clause,
                            related_table.primaryjoin)
                    if getattr(related_table, 'secondaryjoin', None) is not None:
                        clause = and_(
                            clause,
                            related_table.secondaryjoin)

                    return clause
            else:
                return None

        def get_time_format_string(self):
            """
            returns the python formatting string that is used to communicate datetime
            objects to and from a subscription via the crud API
            """
            return serializer._datetime_format

        @crud_subscribes.__func__
        def count(query):
            """
            Count the model objects matching the supplied query parameters

            @param query: Specifies the model types to count. May be a string, a list
            of strings, or a list of dicts with a "_model" key specified.
            @return: The count of each of the supplied model types, in a list of 
            dicts, like so:
            [{
                '_model' : 'Player',
                '_label' : 'Player on a Team',
                'count' : 12
            }]
            @rtype: [c{dict}]
            """
            filters = normalize_query(query)
            results = []
            with Session() as session:
                for filter in filters:
                    model = Session.resolve_model(filter['_model'])
                    result = {'_model' : filter['_model'], 
                              '_label' : filter.get('_label', filter['_model'])}
                    if getattr(model, '_crud_perms', {}).get('read', True):
                        if filter.get('groupby', False):
                            columns = []
                            for attr in filter['groupby']:
                                columns.append(getattr(model, attr))

                            rows = Crud._filter_query(session.query(func.count(columns[0]), *columns), model, filter).all()
                            result['count'] = []
                            for row in rows:
                                count = {'count' : row[0]}
                                index = 1
                                for attr in filter['groupby']:
                                    count[attr] = row[index]
                                    index += 1
                                result['count'].append(count)
                        else:
                            result['count'] = Crud._filter_query(session.query(model), model, filter).count()
                    results.append(result)
            return results

        @crud_subscribes.__func__
        def read(query, data=None, order=None, limit=None, offset=0):
            """
            Get the model objects matching the supplied query parameters,
            optionally setting which part of the objects are in the returned dictionary
            using the supplied data parameter

            @param query: one or more queries (as c{dict} or [c{dict}]), corresponding
                to the format of the query parameter described in the module-level
                docstrings. This query parameter will be normalized
            @param data: one or more data specification (as c{dict} or [c{dict}]),
                corresponding to the format of the data specification parameter
                described in the module-level docstrings. The length of the data
                parameter should either be 1 which will be the spec for each query
                specified, OR of length N, where N is the number of queries after
                normalization. If not provided the _data parameter will be expected
                in each query
            @param limit: The limit parameter, when provided with positive integer "L"
                at most "L" results will be returned. Defaults to no limit
            @param offset: The offset parameter, when provided with positive integer
                "F", at most "L" results will be returned after skipping the first "F"
                results (first based on ordering)
            @return: one or more data specification dictionaries with models that
                match the provided queries including all readable fields without
                following foreign keys (the default if no data parameter is included),
                OR the key/values specified by the data specification parameter. The
                number of items returned and the order in which they appear are
                controlled by the limit, offset and order parameters. Represented as:
                return {
                    total: <int> # count of ALL matching objects, separate from <limit>
                    results: [c{dict}, c{dict}, ... , c{dict}] # subject to <limit>
                }
            """
            with Session() as session:
                filters = normalize_query(query)
                data = normalize_data(data, len(filters))
                if len(filters) == 1:
                    filter = filters[0]
                    model = Session.resolve_model(filter['_model'])
                    total = 0
                    results = []
                    if getattr(model, '_crud_perms', {}).get('read', True):
                        total = Crud._filter_query(session.query(model), model, filter).count()
                        results = Crud._filter_query(session.query(model), model, filter, limit, offset, order).all()

                    return {'total':total, 'results':[r.crud_read(data[0]) for r in results]}

                elif len(filters) > 1:
                    queries = []
                    count_queries = []
                    queried_models = []
                    sort_field_types = {}
                    for filter_index, filter in enumerate(filters):
                        model = Session.resolve_model(filter['_model'])
                        if getattr(model, '_crud_perms', {}).get('read', True):
                            queried_models.append(model)
                            query_fields = [model.id, cast(literal(model.__name__), Text).label("_table_name"), cast(literal(filter_index), Integer)]
                            for sort_index, sort in enumerate(normalize_sort(model, order)):
                                sort_field = getattr(model, sort['field'])
                                sort_field_types[sort_index] = type(sort_field.__clause_element__().type)
                                query_fields.append(sort_field.label('anon_sort_{}'.format(sort_index)))
                            queries.append(Crud._filter_query(session.query(*query_fields), model, filter))
                            count_queries.append(Crud._filter_query(session.query(model.id), model, filter))

                    total = count_queries[0].union(*(count_queries[1:])).count()
                    query = queries[0].union(*(queries[1:]))
                    normalized_sort_fields = normalize_sort(None, order)
                    for sort_index, sort in enumerate(normalized_sort_fields):
                        dir = {'asc':asc, 'desc':desc}[sort['dir']]
                        sort_field = 'anon_sort_{}'.format(sort_index)
                        if issubclass(sort_field_types[sort_index], String):
                            sort_field = 'lower({})'.format(sort_field)
                        query = query.order_by(dir(sort_field))
                    if normalized_sort_fields:
                        query = query.order_by("_table_name")
                    rows = Crud._limit_query(query, limit, offset).all()

                    result_table = {}
                    result_order = {}
                    query_index_table = {}
                    for i, row in enumerate(rows):
                        id = str(row[0])
                        model = Session.resolve_model(row[1])
                        query_index = row[2]
                        result_table.setdefault(model, []).append(id)
                        result_order[id] = i
                        query_index_table[id] = query_index

                    for model, ids in result_table.iteritems():
                        result_table[model] = session.query(model).filter(model.id.in_(ids)).all()

                    ordered_results = len(result_order) * [None]
                    for model, instances in result_table.iteritems():
                        for instance in instances:
                            ordered_results[result_order[instance.id]] = instance
                    results = [r for r in ordered_results if r is not None]

                    return {'total':total, 'results':[r.crud_read(data[query_index_table[r.id]]) for r in results]}
                else:
                    return {'total':0, 'results':[]}

        @crud_notifies.__func__
        def create(data):
            """
            Create a model object using the provided data specifications.

            @param data: one or more data specification (as c{dict} or [c{dict}]),
                corresponding to the format of the data specification parameter
                described in the module-level docstrings. A new object will be created
                for each data specification dictionary provided.
            @return: True if the objects were successfully created
            """
            data = normalize_data(data)
            if any('_model' not in attrs for attrs in data):
                raise CrudException('_model is required to create a new item')

            created = []
            with Session() as session:
                for attrs in data:
                    model = Session.resolve_model(attrs['_model'])
                    instance = model()
                    session.add(instance)
                    instance.crud_create(**attrs)
                    session.flush()  # any items that were created should now be queryable
                    created.append(instance.crud_read())
            return created

        @crud_notifies.__func__
        def update(query, data):
            """
            Get the model objects matching the supplied query parameters,
            setting the fields of the resulting objects to the values specified in
            the data specification parameter

            @param query: one of more queries (as c{dict} or [c{dict}]), corresponding
                to the format of the query parameter described in the module-level
                docstrings. This query parameter will be normalized
            @param data: one or more data specification (as c{dict} or [c{dict}]),
                corresponding to the format of the data specification parameter
                described in the module-level docstrings. The length of the data
                parameter should be N, where N is the number of queries after
                normalization
            @return: True if the objects were successfully updated
            """
            filters = normalize_query(query)
            data = normalize_data(data, len(filters))
            with Session() as session:
                for filter, attrs in zip(filters, data):
                    model = Session.resolve_model(filter['_model'])
                    for instance in Crud._filter_query(session.query(model), model, filter):
                        instance.crud_update(**attrs)
                        # any items that were created should now be queryable
                        session.flush()
            return True

        @crud_notifies.__func__
        def delete(query):
            """
            Delete the model objects matching the supplied query parameters

            @param id: one of more queries (as c{dict} or [c{dict}]), corresponding
                to the format of the query parameter described in the module-level
                docstrings. This query parameter will be normalized
            @return: True if the objects were successfully updated
            """
            deleted = 0
            filters = normalize_query(query)
            with Session() as session:
                for filter in filters:
                    model = Session.resolve_model(filter['_model'])
                    if getattr(model, '_crud_perms', {}).get('can_delete', False):
                        to_delete = Crud._filter_query(session.query(model), model, filter)
                        count = to_delete.count()
                        assert count in [0, 1], "each query passed to crud.delete must return at most 1 item"
                        if count == 1:
                            # don't log if there wasn't actually a deletion
                            item_to_delete = to_delete.one()
                            session.delete(item_to_delete)
                            deleted += count
            return deleted

    return Crud()


class memoized(object):
    """
    Decorator. Caches a function's return value each time it is called.
    If called later with the same arguments, the cached value is returned 
    (not reevaluated).

    from http://wiki.python.org/moin/PythonDecoratorLibrary#Memoize
    """
    def __init__(self, func):
        self.func = func
        self.cache = {}
        
    def __call__(self, *args):
        try:
            return self.cache[args]
        except KeyError:
            value = self.func(*args)
            self.cache[args] = value
            return value
        except TypeError:
            # uncachable -- for instance, passing a list as an argument.
            # Better to not cache than to blow up entirely.
            return self.func(*args)
    def __repr__(self):
        """Return the function's docstring."""
        return self.func.__doc__
    def __get__(self, obj, objtype):
        """Support instance methods."""
        return functools.partial(self.__call__, obj)


class CrudMixin(object):
    extra_defaults = []
    type_casts = {uuid.UUID: str}
    type_map = {}
    type_map_defaults = {
        int: 'int',
        str: 'string',
        unicode: 'string',
        float: 'float',
        datetime: 'date',
        date: 'date',
        time: 'date',
        bool: 'boolean',
        uuid.UUID: 'string',
        String: 'string',
        UnicodeText: 'string',
        Text: 'string',
        DateTime: 'date',
        Integer: 'int',
        Boolean: 'boolean',
    }

    # override what attribute names will show in the repr (defaults to primary keys and unique constraints)
    _repr_attr_names = ()
    # in addition to any default attributes, also show these in the repr
    _additional_repr_attr_names = ()

    @classmethod
    def _get_unique_constraint_column_names(cls):
        """
        Utility function for getting and then caching the column names
        associated with all the unique constraints for a given model object.
        This assists in fetching an existing object using the value of unique
        constraints in addition to the primary key of id.
        """
        if not hasattr(cls, '_unique_constraint_attributes'):
            cls._unique_constraint_attributes = [[column.name for column in constraint.columns]
                                                    for constraint in cls.__table__.constraints
                                                    if isinstance(constraint, UniqueConstraint)]
        return cls._unique_constraint_attributes

    @classmethod
    def _get_primary_key_names(cls):
        if not hasattr(cls, '_pk_names'):
            cls._pk_names = [column.name for column in cls.__table__.primary_key.columns]
        return cls._pk_names

    @classmethod
    def _create_or_fetch(cls, session, value, **backref_mapping):
        """
        Fetch an existing or create a new instance of this class. Fetching uses
        the values from the value positional argument (the id if available, or
        if any keys that correspond to unique constraints are present). In both
        cases the instance will still need to be updated using whatever new
        values you want.

        @param cls: The class object we're going to fetch or create a new one of
        @param session: the session object
        @param value: the dictionary value to fetch with
        @param backref_mapping: the backref key name and value of the "parent"
            object of the object you're fetching or about to create. If the
            backref value of a fetched instance is not the same as the value
            of what's passed in, we will instead create a new instance. This is
            because we want to prevent "stealing" an existing object in a
            one-to-one relationship unless an id is explicitly passed
        @return: a previously existing or new (and added to the session) model
            instance
        """
        assert len(backref_mapping) <= 1, 'only one backref key is allowed at this time: {}'.format(backref_mapping)
        if backref_mapping:
            backref_name = backref_mapping.keys()[0]
            parent_id = backref_mapping[backref_name]
        else:
            backref_name, parent_id = None, None

        id = None
        if isinstance(value, Mapping):
            id = value.get('id', None)
        elif isinstance(value, basestring):
            id = value

        instance = None
        if id is not None:
            try:
                instance = session.query(cls).filter(cls.id==id).first()
            except:
                log.error('Unable to fetch instance based on id value {!r}', value, exc_info=True)
                raise TypeError('Invalid instance ID type for relation: {0.__name__} (value: {1})'.format(cls, value))
        elif isinstance(value, Mapping):
            # if there's no id, check to see if we're provided a dictionary
            # that includes all of the columns associated with a UniqueConstraint.
            for column_names in cls._get_unique_constraint_column_names():
                if all((name in value and value[name]) for name in column_names):
                    # all those column names are provided,
                    # use that to query by chaining together all the necessary
                    # filters to construct that query
                    q = session.query(cls)
                    filter_kwargs = {name: value[name] for name in column_names}
                    try:
                        instance = q.filter_by(**filter_kwargs).one()
                    except NoResultFound:
                        continue
                    except MultipleResultsFound:
                        log.error('multiple results found for {} unique constraint: {}', cls.__name__, column_names)
                        raise
                    else:
                        break
                else:
                    log.debug('unable to search using unique constraints: {} with {}', column_names, value)

        if instance and id is None and backref_mapping and getattr(instance, backref_name, None) != parent_id:
            log.warning('attempting to change the owner of {} without an explicitly passed id; a new {} instance will be used instead', instance, cls.__name__)
            instance = None

        if not instance:
            log.debug('creating new: {} with id {}', cls.__name__, id)
            if id is None:
                instance = cls()
            else:
                instance = cls(id=id)
            session.add(instance)
        return instance

    @property
    def _type_casts_for_to_dict(self):
        if not hasattr(self, '_to_dict_type_cast_mapping'):
            self._to_dict_type_cast_mapping = defaultdict(lambda: lambda x: x, dict(CrudMixin.type_casts, **self.type_casts))
        return self._to_dict_type_cast_mapping

    def to_dict(self, attrs=None, validator=lambda self, name: True):
        obj = {}
        attrs = normalize_object_graph(attrs)

        # it's still possible for the client to blacklist this, but by default
        # we're going to include them
        if attrs is None or attrs.get('_model', True):
            obj['_model'] = self.__class__.__name__
        if attrs is None or attrs.get('id', True):
            obj['id'] = self.id

        def cast_type(value):
            # ensure that certain types are cast appropriately for daily usage
            # e.g. we want the result of HashedPasswords to be the string
            # representation instead of the object
            return self._type_casts_for_to_dict[value.__class__](value)

        if attrs is None:
            for name in collect_ancestor_attributes(self.__class__, terminal_cls=self.BaseClass):
                if not validator(self, name):
                    continue
                if not name.startswith('_') or name in self.extra_defaults:
                    attr = getattr(self.__class__, name)
                    if isinstance(attr, InstrumentedAttribute):
                        if isinstance(attr.property, ColumnProperty):
                            obj[name] = cast_type(getattr(self, name))
                    elif not isinstance(attr, (property, ClauseElement)) and not callable(attr):
                        obj[name] = cast_type(getattr(self, name))
        else:
            for name in self.extra_defaults + list(attrs.keys()):
                # if we're not supposed to get the attribute according to the validator,
                # OR the client intentionally blacklisted it, skipped this value
                if not validator(self, name) or not attrs.get(name, True):
                    continue
                attr = getattr(self, name, None)
                if isinstance(attr, self.BaseClass):
                    obj[name] = attr.to_dict(attrs[name], validator)
                elif isinstance(attr, (list, set, tuple, frozenset)):
                    obj[name] = []
                    for item in attr:
                        if isinstance(item, self.BaseClass):
                            obj[name].append(item.to_dict(attrs[name], validator))
                        else:
                            obj[name].append(item)
                elif callable(attr):
                    obj[name] = cast_type(attr())
                else:
                    obj[name] = cast_type(attr)

        return obj
    
    def from_dict(self, attrs, validator=lambda self, name, val: True):
        relations = []
        # merge_relations modifies the dictionaries that are passed to it in
        # order to support updates in deeply-nested object graphs. To ensure
        # that we don't have dirty state between applying updates to different
        # model objects, we need a fresh copy
        attrs = deepcopy(attrs)
        for name,value in attrs.iteritems():
            if not name.startswith('_') and validator(self, name, value):
                attr = getattr(self.__class__, name)
                if isinstance(attr, InstrumentedAttribute) and isinstance(attr.property, RelationshipProperty):
                    relations.append((name, value))
                else:
                    setattr(self, name, value)
        
        def required(kv):
            cols = list(getattr(self.__class__, kv[0]).property.local_columns)
            return len(cols) != 1 or cols[0].primary_key or cols[0].nullable
        relations.sort(key = required)

        for name,value in relations:
            self._merge_relations(name, value, validator)

        return self

    @classmethod
    @memoized
    def _get_one_to_many_foreign_key_attr_name_if_applicable(cls, name):
        attr = getattr(cls, name, None)
        if attr is None:
            return None

        remote_side = getattr(attr.property, 'remote_side', None)
        if remote_side is None:
            return None

        if len(remote_side) != 1:
            # there's a lookup table involved here, and we're not going to handle that
            return None
        [remote_column] = remote_side

        if not getattr(remote_column, 'foreign_keys', set()):
            # tags don't actually have foreign keys set, but they need to be treated as the same
            if name == 'tags':
                log.debug('special-case handling for tags, returning: {}', remote_column.name)
                return remote_column.name
            else:
                # the implication here could be that we're the many side of a
                # many to one or many to many. That hasn't been born out in testing
                # but we'll log it just in case
                return None
        else:
            # return "our" attribute name for the remote model object
            return remote_column.name

    def _merge_relations(self, name, value, validator=lambda self, name, val: True):
        attr = getattr(self.__class__, name)
        if (not isinstance(attr, InstrumentedAttribute) or 
            not isinstance(attr.property, RelationshipProperty)):
            return

        session = orm.Session.object_session(self)
        assert session, "cannot call _merge_relations on objects not attached to a session"

        property = attr.property
        relation_cls = property.mapper.class_

        # e.g., if this a Team with many Players, and we're handling the attribute name
        # "players," we want to set the team_id on all dictionary representations of those players.
        backref_id_name = self._get_one_to_many_foreign_key_attr_name_if_applicable(name)
        original_value = getattr(self, name)

        if is_listy(original_value):
            new_insts = []
            if value is None:
                value = []

            if isinstance(value, basestring):
                value = [value]

            for i in value:
                if backref_id_name is not None and isinstance(i, dict) and not i.get(backref_id_name):
                    i[backref_id_name] = self.id
                relation_inst = relation_cls._create_or_fetch(session, i, **{backref_id_name:self.id} if backref_id_name else {})
                if isinstance(i, dict):
                    relation_inst.from_dict(i, _crud_write_validator if relation_inst._sa_instance_state.identity else _crud_create_validator)
                new_insts.append(relation_inst)

            relation = original_value
            remove_insts = [stale_inst for stale_inst in relation if stale_inst not in new_insts]

            for stale_inst in remove_insts:
                relation.remove(stale_inst)
                if property.cascade.delete_orphan:
                    session.delete(stale_inst)

            for new_inst in new_insts:
                if new_inst.id is None or new_inst not in relation:
                    relation.append(new_inst)

        elif isinstance(value, (collections.Mapping, basestring)):
            if backref_id_name is not None and not value.get(backref_id_name):
                # if this is a dictionary, it's possible we're going to be
                # creating a new thing, if so, we'll add a backref to the
                # "parent" if one isn't already set
                value[backref_id_name] = self.id

            relation_inst = relation_cls._create_or_fetch(session, value)
            stale_inst = original_value
            if stale_inst is None or stale_inst.id != relation_inst.id:
                if stale_inst is not None and property.cascade.delete_orphan:
                    session.delete(stale_inst)

            if isinstance(value, collections.Mapping):
                relation_inst.from_dict(value, validator)
                session.flush([relation_inst])    # we want this this to be queryable for other things

            setattr(self, name, relation_inst)

        elif value is None:
            # the first branch handles the case of setting a many-to-one value
            # to None. So this is for the one-to-one-mapping case
            # Setting a relation to None is nullifying the relationship, which
            # has potential side effects in the case of cascades, etc.
            setattr(self, name, value)
            stale_inst = original_value
            if stale_inst is not None and property.cascade.delete_orphan:
                session.delete(stale_inst)

        else:
            raise TypeError('merging relations on {1} not support for values '
                            'of type: {0.__class__.__name__} '
                            '(value: {0})'.format(value, name))

    def __setattr__(self, name, value):
        if name in getattr(self, '_validators', {}):
            for val_dict in self._validators[name]:
                if not val_dict['model_validator'](self, value):
                    raise ValueError('validation failed for {.__class__.__name__}'
                                     '.{} with value {!r}: {}'.format(self, name, value,
                                                                      val_dict.get('validator_message')))
        object.__setattr__(self, name, value)

    def crud_read(self, attrs=None):
        return self.to_dict(attrs, validator=_crud_read_validator)

    def crud_create(self, **kwargs):
        return self.from_dict(kwargs, validator=_crud_create_validator)

    def crud_update(self, **kwargs):
        return self.from_dict(kwargs, validator=_crud_write_validator)

    def __repr__(self):
        """
        useful string representation for logging. Reprs do NOT return unicode,
        since python decodes it using the default encoding:
        http://bugs.python.org/issue5876
        """
        # if no repr attr names have been set, default to the set of all
        # unique constraints. This is unordered normally, so we'll order and
        # use it here
        if not self._repr_attr_names:
            # this flattens the unique constraint list
            _unique_attrs = chain.from_iterable(self._get_unique_constraint_column_names())
            _primary_keys = self._get_primary_key_names()

            attr_names = tuple(sorted(set(chain(_unique_attrs,
                                                _primary_keys,
                                                self._additional_repr_attr_names))))
        else:
            attr_names = self._repr_attr_names

        if not attr_names and hasattr(self, 'id'):
            # there should be SOMETHING, so use id as a fallback
            attr_names = ('id',)

        if attr_names:
            _kwarg_list = ' '.join('%s=%s' % (name, repr(getattr(self, name, 'undefined')))
                                   for name in attr_names)
            kwargs_output = ' %s' % _kwarg_list
        else:
            kwargs_output = ''

        # specifically using the string interpolation operator and the repr of
        # getattr so as to avoid any "hilarious" encode errors for non-ascii
        # characters
        return ('<%s%s>' % (self.__class__.__name__, kwargs_output)).encode('utf-8')


def _crud_read_validator(self, name):
    _crud_perms = getattr(self, '_crud_perms', None)
    if _crud_perms is not None and not _crud_perms.get('read', True):
        raise ValueError('Attempt to read non-readable model {}'.format(self.__class__.__name__))
    elif name in self.extra_defaults:
        return True
    elif _crud_perms is None:
        return not name.startswith('_')
    else:
        return name in _crud_perms.get('read', {})


def _crud_write_validator(self, name, value=None):
    _crud_perms = getattr(self, '_crud_perms', None)
    if getattr(self, name, None) == value:
        return True
    elif not _crud_perms or not _crud_perms.get('update', False):
        raise ValueError('Attempt to update non-updateable model {}'.format(self.__class__.__name__))
    elif name not in _crud_perms.get('update', {}):
        raise ValueError('Attempt to update non-updateable attribute {}.{}'.format(self.__class__.__name__, name))
    else:
        return name in _crud_perms.get("update", {})


def _crud_create_validator(self, name, value=None):
    _crud_perms = getattr(self, '_crud_perms', {})
    if not _crud_perms or not _crud_perms.get('can_create', False):
        raise ValueError('Attempt to create non-createable model {}'.format(self.__class__.__name__))
    else:
        return name in _crud_perms.get("create", {})


def _isdata(obj):
    """
    Stolen from inspect.classify_class_attrs function, basically is the
    provided object just something that we're providing at the class level.
    If True, it will be assumed that this obj does not have a meaningful
    __doc__ attribute and it should be provided via the data_spec
    initialization argument
    """
    # Classify the object.
    if isinstance(obj, staticmethod):
        return False
    elif isinstance(obj, classmethod):
        return False
    elif isinstance(obj, property):
        return False
    elif inspect.ismethod(obj) or inspect.ismethoddescriptor(obj):
        return False
    else:
        return True


class crudable(object):
    """
    Convenience decorator for specifying what methods of a model object
    instance can be interacted with via the CRUD API

    Intended to be used in the sa module for SQLAlchemy model classes i.e.:
    @crudable(
        create=True,
        read=['__something'],
        no_read=['password'],
        update=[],
        no_update=[],
        delete=True,
        data_spec={
            attr={
                read=True,
                update=True,
                desc="description"
                defaultValue=<some default>
                validators={
                    '<validator_name>', <validator value>
                }
        })
    class MyModelObject(Base):
        ...


    and the resulting object will have a class attribute of "crud_spec" holding
    a dictionary of:

    {create: True/False,
     read: {<attribute name>, <attribute name>},
     update: {<attribute name>, <attribute name>},
     delete: True/False,
     data_spec: {
        manually_specified_attr: {
            desc: "description",
            type: "<type>"
            read: True/False # only needed if attribute is unspecified
            update": True/False
        }

        attr_with_manual_description: {
            desc: "description",
            type: "<type>"
        }
    }
    
    @cvar never_read: a tuple of attribute names that default to being 
        not readable
    @cvar never_update: a tuple of attribute names that default to being 
        not updatable
    @cvar always_create: a tuple of attribute names that default to being
        always creatable
    @cvar default_labels: a dict of attribute name and desired label pairs,
        to simplify setting the same label for each and every instance of an
        attribute name
    """
    
    never_read = ('metadata',)
    never_update = ('id',)
    always_create = ('id',)
    default_labels = {'addr': 'Address'}    # TODO: allow plugins to define this; Sideboard core is not the place to encode addr/Address
    
    def __init__(self, can_create=True,
                 create=None, no_create=None,
                 read=None, no_read=None,
                 update=None, no_update=None,
                 can_delete=True,
                 data_spec=None):
        """
        @param can_create: if True (default), the decorated class can be
            created
        @type can_create: C{bool}
        @param create: if provided, interpreted as the attribute names that can
            be specified when the object is created in addition to the items are
            updateable. If not provided (default) all attributes that can be
            updated plus id are allowed to be passed to the create method
        @param no_create: if provided, interpreted as the attribute names that
            will not be allowed to be passed to create, taking precedence over
            anything specified in the create parameter. If not provided
            (default) everything allowed by the create parameter will be
            acceptable.
        @param read: if provided, interpreted as the attribute names that can
            be read, and ONLY these names can be read. If not provided
            (default) all attributes not starting with an underscore
            (e.g. __str__, or _hidden) will be readable
        @type read: C{collections.Iterable}
        @param no_read: if provided, interpreted as the attribute names that
            can't be read, taking precedence over anything specified in the
            read parameter. If not provided (default) everything allowed by
            the read parameter will be readable
        @type no_read: C{collections.Iterable}
        @param update: if provided, interpreted as the attribute names that can
            be updated, in addition to the list of items are readable. If None
            (default) default to the list of readable attributes. Pass an empty
            iterable to use the default behavior listed under the read
            docstring if there were attributes passed to read that you don't
            want update to default to
        @type update: C{collections.Iterable}
        @param no_update: if provided, interpreted as the attribute names that
            can't be updated, taking precedence over anything specified in the
            update parameter. If None (default) default to the list of
            non-readable attributes. Pass an empty iterable to use the default
            behavior listed under the no_read docstring if there were
            attributes passed to no_read that you don't want no_update to
            default to
        @type no_update: C{collections.Iterable}
        @param can_delete: if True (default), the decorated class can be
            deleted
        @type can_delete: C{bool}
        @param data_spec: any additional information that should be added to
            the L{model.get_crud_definition}. See that function for
            complete documentation, but key items are:
            "desc" - Human-readable description, will default to docstrings if
                available, else not be present in the final spec
            "label" - a Human-readable short label to help remember the purpose
                of a particular field, without going into detail. If not
                specifically provided, it will not be present in the spec
            "type" - the human-readable "type" for an attribute meaning that a
                conversion to this type will be performed on the server. If
                possible this will be determined automatically using
                isinstance(), otherwise "auto" will be set:
                auto (default) - no type conversion
                string - C{str}
                boolean - C{bool}
                int - C{int}
                float - C{float}
            "defaultValue" - the value that is considered the default, either
                because a model instance will use this default value if
                unspecified, or a client should present this option as the
                default for a user
            "validators" - a c{dict} mapping a validator name (e.g. "max") and
                the value to be used in validation (e.g. 1000, for a max value
                of 1000). This is intended to support client side validation
        """
        
        self.can_create = can_create
        self.can_delete = can_delete
        if no_update is not None and create is None:
            create = deepcopy(no_update)
        self.read = read or []
        self.no_read = no_read or []
        self.update = update or []
        self.no_update = no_update or [x for x in self.no_read if x not in self.update]
        self.create = create or []
        self.no_create = no_create or [x for x in self.no_update if x not in self.create]
        
        self.no_read.extend(self.never_read)
        self.no_update.extend(self.never_update)
        
        self.data_spec = data_spec or {}
    
    def __call__(self, cls):
        class ClassProperty(property):
            def __get__(self, cls, owner):
                return self.fget.__get__(None, owner)()
        
        def _get_crud_perms(cls):
            if getattr(cls, '_cached_crud_perms', False):
                return cls._cached_crud_perms
            
            crud_perms = {
                'can_create' : self.can_create,
                'can_delete' : self.can_delete,
                'read' : [],
                'update' : [],
                'create' : []
            }
            
            read = self.read
            for name in collect_ancestor_attributes(cls):
                if not name.startswith('_'):
                    attr = getattr(cls, name)
                    if (isinstance(attr, (InstrumentedAttribute, property, ClauseElement)) or
                        isinstance(attr, (int, float, bool, basestring, datetime, date, time, uuid.UUID))):
                        read.append(name)
            read = list(set(read))
            for name in read:
                if not self.no_read or name not in self.no_read:
                    crud_perms['read'].append(name)
            
            update = self.update + deepcopy(crud_perms['read'])
            update = list(set(update))
            for name in update:
                if not self.no_update or name not in self.no_update:
                    if name in cls.__table__.columns:
                        crud_perms['update'].append(name)
                    else:
                        attr = getattr(cls, name)
                        if isinstance(attr, property) and getattr(attr, 'fset', False):
                            crud_perms['update'].append(name)
                        elif (isinstance(attr, InstrumentedAttribute) and 
                              isinstance(attr.property, RelationshipProperty) and
                              attr.property.viewonly != True):
                            crud_perms['update'].append(name)
            
            create = self.create + deepcopy(crud_perms['update'])
            for name in self.always_create:
                create.append(name)
                if name in self.no_create:
                    self.no_create.remove(name)
            create = list(set(create))
            for name in create:
                if not self.no_create or name not in self.no_create:
                    crud_perms['create'].append(name)
            
            cls._cached_crud_perms = crud_perms
            return cls._cached_crud_perms
        
        def _get_crud_spec(cls):
            if getattr(cls, '_cached_crud_spec', False):
                return cls._cached_crud_spec
            
            crud_perms = cls._crud_perms
            
            field_names = list(set(crud_perms['read']) | set(crud_perms['update']) | 
                               set(crud_perms['create']) | set(self.data_spec.keys()))
            fields = {}
            for name in field_names:
                # json is implicitly unicode, and since this will eventually
                # be serialized as json, it's convenient to have it in that
                # form early

                # if using different validation decorators or in the data spec 
                # causes multiple spec 
                # kwargs to be specified, we're going to error here for 
                # duplicate keys in dictionaries. Since we don't want to allow
                # two different expected values for maxLength being sent in a
                # crud spec for example
                field_validator_kwargs = {
                    spec_key_name: spec_value
                    # collect each spec_kwarg for all validators of an attribute
                    for crud_validator_dict in getattr(cls, '_validators', {}).get(name, [])
                    for spec_key_name, spec_value in crud_validator_dict.get('spec_kwargs', {}).iteritems()
                }
                
                if field_validator_kwargs:
                    self.data_spec.setdefault(name, {})
                    # manually specified crud validator keyword arguments 
                    # overwrite the decorator-supplied keyword arguments
                    field_validator_kwargs.update(self.data_spec[name].get('validators', {}))
                    self.data_spec[name]['validators'] = field_validator_kwargs

                name = unicode(name)
                field = deepcopy(self.data_spec.get(name, {}))
                field['name'] = name
                try:
                    attr = getattr(cls, name)
                except AttributeError:
                    # if the object doesn't have the attribute, AND it's in the field
                    # list, that means we're assuming it was manually specified in the
                    # data_spec argument
                    fields[name] = field
                    continue
                
                field['read'] = name in crud_perms['read']
                field['update'] = name in crud_perms['update']
                field['create'] = name in crud_perms['create']
                
                if field['read'] or field['update'] or field['create']:
                    fields[name] = field
                elif name in fields:
                    del fields[name]
                    continue
                
                if 'desc' not in field and not _isdata(attr):
                    # no des specified, and there's a relevant docstring, so use it
        
                    # if there's 2 consecutive newlines, assume that there's a
                    # separator in the docstring and that the top part only
                    # is the description, if there's not, use the whole thing.
                    # Either way, replace newlines with spaces since docstrings often
                    # break the same sentence over new lines due to space
                    doc = inspect.getdoc(attr)
                    if doc:
                        doc = doc.partition('\n\n')[0].replace('\n', ' ').strip()
                        field['desc'] = doc
            
                if 'type' not in field:
                    if isinstance(attr, InstrumentedAttribute) and isinstance(attr.property, ColumnProperty):
                        field['type'] = cls._type_map.get(type(attr.property.columns[0].type), 'auto')
                        field_default = getattr(attr.property.columns[0], 'default', None)
                        # only put the default here if it exists, and it's not an automatic thing like "time.utcnow()"
                        if field_default is not None and field['type'] != 'auto' and not isinstance(field_default.arg, (collections.Callable, property)):
                            field['defaultValue'] = field_default.arg
                    elif hasattr(attr, "default"):
                        field['defaultValue'] = attr.default
                    else:
                        field['type'] = cls._type_map.get(type(attr), 'auto')
                        # only set a default if this isn't a property or some other kind of "constructed attribute"
                        if field['type'] != 'auto' and not isinstance(attr, (collections.Callable, property)):
                            field['defaultValue'] = attr
                if isinstance(attr, InstrumentedAttribute) and isinstance(attr.property, RelationshipProperty):
                    field['_model'] = attr.property.mapper.class_.__name__
            
            crud_spec = {'fields': fields}
            cls._cached_crud_spec = crud_spec
            return cls._cached_crud_spec

        def _type_map(cls):
            return dict(cls.type_map_defaults, **cls.type_map)

        cls._type_map = ClassProperty(classmethod(_type_map))
        cls._crud_spec = ClassProperty(classmethod(_get_crud_spec))
        cls._crud_perms = ClassProperty(classmethod(_get_crud_perms))
        return cls


class crud_validation(object):
    """
    Base class for adding validators to a model, supporting adding to the crud
    spec, or to the save action
    """
    def __init__(self, attribute_name, model_validator, validator_message, **spec_kwargs):
        """
        @param attribute_name: the name of the attribute to set this validator
            for
        @param model_validator: the c{collections.Callable) that will accept
            the value of the attribute and return False or None if invalid,
            True if the value is valid. This is used on setting the attribute
            name with the python instance
        @param validator_message: message to print if the model validation fails
        @param spec_kwargs: the key/value pairs that should be added to the
            the crud spec for this attribute name. This generally supports
            making the same sorts of validations in a client (e.g. javascript)
        """
        self.attribute_name = attribute_name
        self.model_validator = model_validator
        self.validator_message = validator_message
        self.spec_kwargs = spec_kwargs

    def __call__(self, cls):
        if not hasattr(cls, '_validators'):
            cls._validators = {}
        else:
            # in case we subclass something with a _validators attribute
            cls._validators = deepcopy(cls._validators)
        
        cls._validators.setdefault(self.attribute_name, []).append({
            'model_validator': self.model_validator,
            'validator_message': self.validator_message,
            'spec_kwargs': self.spec_kwargs
        })
        return cls


class text_length_validation(crud_validation):
    def __init__(self, attribute_name, min_length=None, max_length=None,
                 min_text='The minimum length of this field is {0}.',
                 max_text='The maximum length of this field is {0}.',
                 allow_none=True):

        def model_validator(instance, text):
            if not text:
                return allow_none
            text_length = len(unicode(text))
            return all([min_length is None or text_length >= min_length,
                        max_length is None or text_length <= max_length])

        kwargs = {}
        if not min_length is None:
            kwargs['minLength'] = min_length
            if not max_text is None:
                kwargs['minLengthText'] = min_text
        if not max_length is None:
            kwargs['maxLength'] = max_length
            if not max_text is None:
                kwargs['maxLengthText'] = max_text

        message = 'Length of value should be between {} and {} (inclusive; None means no min/max).'.format(min_length, max_length)
        crud_validation.__init__(self, attribute_name, model_validator, message, **kwargs)


class regex_validation(crud_validation):
    def __init__(self, attribute_name, regex, message):

        def regex_validator(instance, text):
            # if the field isn't nullable, that will trigger an error later at the sqla level,
            # but since None can't be passed to a re.search we want to pass this validation check
            if text is None:
                return True

            # we don't want to actually send across the match object if it did match,
            # so leverage the fact that failing searches or matches return None types
            return re.search(regex, text) is not None

        crud_validation.__init__(self, attribute_name, regex_validator, message,
                                       regexText=message, regexString=regex)
