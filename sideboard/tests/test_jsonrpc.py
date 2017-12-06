from __future__ import unicode_literals
import json

import pytest
import cherrypy
from mock import Mock

from sideboard.lib import services
from sideboard.tests import service_patcher
from sideboard.jsonrpc import _make_jsonrpc_handler


@pytest.fixture
def precall():
    return Mock()


@pytest.fixture
def raw_jsonrpc(service_patcher, precall, monkeypatch):
    service_patcher('test', {'get_message': lambda name: 'Hello {}!'.format(name)})

    def caller(parsed):
        cherrypy.request.json = parsed
        result = _make_jsonrpc_handler(services.get_services(), precall=precall)(self=None)
        return result
    return caller


@pytest.fixture
def jsonrpc(raw_jsonrpc):
    def caller(method, *args, **kwargs):
        return raw_jsonrpc({
            'method': method,
            'params': kwargs or list(args)
        })
    return caller


def test_precall(jsonrpc, precall):
    jsonrpc('test.get_message', 'World')
    assert precall.called


def test_valid_args(jsonrpc):
    assert jsonrpc('test.get_message', 'World')['result'] == 'Hello World!'


def test_valid_kwargs(jsonrpc):
    assert jsonrpc('test.get_message', name='World')['result'] == 'Hello World!'


def test_non_object(raw_jsonrpc):
    response = raw_jsonrpc('not actually json')
    assert 'invalid json input' in response['error']['message']


def test_no_method(raw_jsonrpc):
    assert '"method" field required' in raw_jsonrpc({})['error']['message']


def test_invalid_method(jsonrpc):
    assert 'invalid method' in jsonrpc('')['error']['message']
    assert 'invalid method' in jsonrpc('no_module')['error']['message']
    assert 'invalid method' in jsonrpc('too.many.modules')['error']['message']


def test_missing_module(jsonrpc):
    assert 'no module' in jsonrpc('invalid.module')['error']['message']


def test_missing_function(jsonrpc):
    assert 'no function' in jsonrpc('test.does_not_exist')['error']['message']


def test_invalid_params(raw_jsonrpc):
    assert 'invalid parameter list' in raw_jsonrpc({
        'method': 'test.get_message',
        'params': 'not a list or dict'
    })['error']['message']


def test_exception(jsonrpc):
    assert 'unexpected error' in jsonrpc('test.get_message')['error']['message']
