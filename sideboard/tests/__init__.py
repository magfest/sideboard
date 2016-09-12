from __future__ import unicode_literals
import os

import pytest
import sqlalchemy
from sqlalchemy import event
from sqlalchemy.orm import sessionmaker

from sideboard.lib import config, services


@pytest.fixture
def service_patcher(request):
    class TestService(object):
        def __init__(self, methods): 
            self.__dict__.update(methods)

    def patch(name, service):
        if isinstance(service, dict):
            service = TestService(service)
        orig_service = services.get_services().get(name)
        services.register(service, name)
        request.addfinalizer(lambda: services.get_services().pop(name, None))
        if orig_service:
            request.addfinalizer(lambda: services.get_services().update({name: orig_service}))
    return patch

@pytest.fixture
def config_patcher(request):
    def patch_config(value, *path, **kwargs):
        conf = kwargs.pop('config', config)
        for section in path[:-1]:
            conf = conf[section]
        orig_val = conf[path[-1]]
        request.addfinalizer(lambda: conf.__setitem__(path[-1], orig_val))
        conf[path[-1]] = value
    return patch_config

def patch_session(Session, request):
    orig_engine, orig_factory = Session.engine, Session.session_factory
    request.addfinalizer(lambda: setattr(Session, 'engine', orig_engine))
    request.addfinalizer(lambda: setattr(Session, 'session_factory', orig_factory))

    name = Session.__module__.split('.')[0]
    db_path = '/tmp/{}.db'.format(name)
    Session.engine = sqlalchemy.create_engine('sqlite+pysqlite:///' + db_path)
    event.listen(Session.engine, 'connect', lambda conn, record: conn.execute('pragma foreign_keys=ON'))
    Session.session_factory = sessionmaker(bind=Session.engine, autoflush=False, autocommit=False,
                                           query_cls=Session.QuerySubclass)
    Session.initialize_db(drop=True)
