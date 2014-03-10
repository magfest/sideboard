from __future__ import unicode_literals
import json

import requests

from sideboard.tests import SideboardServerTest


class JsonrpcTest(SideboardServerTest):
    def get_message(self, name):
        return 'Hello {}!'.format(name)

    def setUp(self):
        SideboardServerTest.setUp(self)
        self.override('testservice', self)

    def send_json(self, body, content_type='application/json'):
        if isinstance(body, dict):
            body['id'] = self._testMethodName
        resp = requests.post(self.jsonrpc_url, data=json.dumps(body),
                             headers={'Content-Type': 'application/json'})
        self.assertTrue(resp.json, resp.text)
        return resp.json()

    def send_jsonrpc(self, method, *args, **kwargs):
        return self.send_json({
            'method': method,
            'params': args or kwargs
        })

    def assertError(self, error, response):
        self.assertEqual(self._testMethodName, response['id'])
        self.assertIn(error, response['error']['message'])

    def test_rpctools(self):
        self.assertEqual('Hello World!',
                         self.jsonrpc.testservice.get_message('World'))

    def test_valid_args(self):
        response = self.send_jsonrpc('testservice.get_message', 'World')
        self.assertEqual('Hello World!', response['result'])

    def test_valid_kwargs(self):
        response = self.send_jsonrpc('testservice.get_message', name='World')
        self.assertEqual('Hello World!', response['result'])

    def test_non_object(self):
        response = self.send_json('not the expected json object')
        self.assertIn('invalid json input', response['error']['message'])

    def test_no_method(self):
        self.assertError('"method" field required', self.send_json({}))

    def test_content_types(self):
        for ct in ('text/html', 'text/plain', 'application/javascript', 'text/javascript', 'image/gif'):
            res = self.send_json(
                {'method': 'testservice.get_message', 'params': ['World']},
                content_type=ct)
            self.assertEqual('Hello World!', res['result'],
                             'Expected success with valid reqeust using Content-Type %s' % ct)

    def test_invalid_method(self):
        self.assertError('invalid method', self.send_jsonrpc(''))
        self.assertError('invalid method', self.send_jsonrpc('no_module'))
        self.assertError('invalid method',
                         self.send_jsonrpc('too.many.nested.modules'))

    def test_missing_module(self):
        self.assertError('no module', self.send_jsonrpc('invalid.module'))

    def test_missing_function(self):
        self.assertError('no function',
                         self.send_jsonrpc('testservice.does_not_exist'))

    def test_invalid_params(self):
        self.assertError('invalid parameter list', self.send_json(
            {'method': 'testservice.get_message',
             'params': 'not a list or dict'}))

    def test_exception(self):
        self.assertError('unexpected error',
                         self.send_jsonrpc('testservice.get_message'))
