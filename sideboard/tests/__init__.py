from __future__ import unicode_literals
import os
import socket
from contextlib import closing

import pytest
import sqlalchemy
from sqlalchemy import event
from sqlalchemy.orm import sessionmaker

from sideboard.lib import config, services


def get_available_port():
    """
    Returns an unused port in the ephemeral port range.

    Binding to port 0 with socket.SO_REUSEADDR will give us an unused port
    that we can immediately reuse. This is mostly safe, but on heavily used
    systems there is a potential race condition if another process uses
    the same port in the time between requesting an available port and
    actually using it. This is unlikely, and the worst that will happen is
    the tests fail on that particular test run.

    See https://eklitzke.org/binding-on-port-zero

    Ideally we could tell cherrypy to listen on port 0, and then inspect
    it to determine what port it's using, but cherrypy doesn't support that
    yet (other parts of cherrypy will try to use the port defined in
    'cherrypy.server.socket_port' and end up failing on startup).
    """
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


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
