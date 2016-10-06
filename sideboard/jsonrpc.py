from __future__ import unicode_literals
import json
import traceback

import cherrypy
from cherrypy.lib.jsontools import json_decode

from sideboard.lib import log, config, serializer


ERR_INVALID_RPC = -32600
ERR_MISSING_FUNC = -32601
ERR_INVALID_PARAMS = -32602
ERR_FUNC_EXCEPTION = -32603
ERR_INVALID_JSON = -32700


# TODO: this is ugly, it relies on the undocumented implementation of json_out so we should probably write our own force_json_out
def json_handler(*args, **kwargs):
    value = cherrypy.serving.request._json_inner_handler(*args, **kwargs)
    return json.dumps(value, cls=serializer).encode('utf-8')


def force_json_in():
    """A version of jsontools.json_in that forces all requests to be interpreted as JSON."""
    request = cherrypy.serving.request
    if not request.headers.get('Content-Length', ''):
        raise cherrypy.HTTPError(411)

    if cherrypy.request.method in ('POST', 'PUT'):
        body = request.body.fp.read()
        try:
            cherrypy.serving.request.json = json_decode(body.decode('utf-8'))
        except ValueError:
            raise cherrypy.HTTPError(400, 'Invalid JSON document')

cherrypy.tools.force_json_in = cherrypy.Tool('before_request_body', force_json_in, priority=30)


def _make_jsonrpc_handler(services, debug=config['debug'],
                         precall=lambda body: None,
                         errback=lambda err, message: log.error(message, exc_info=True)):
    @cherrypy.expose
    @cherrypy.tools.force_json_in()
    @cherrypy.tools.json_out(handler=json_handler)
    def jsonrpc_handler(self):
        id = None

        def error(code, message):
            body = {'jsonrpc': '2.0', 'id': id, 'error': {'code': code, 'message': message}}
            log.warn('returning error message: {!r}', body)
            return body

        body = cherrypy.request.json
        if not isinstance(body, dict):
            return error(ERR_INVALID_JSON, 'invalid json input {!r}'.format(cherrypy.request.body))

        log.debug('jsonrpc request body: {!r}', body)

        id, params = body.get('id'), body.get('params', [])
        if 'method' not in body:
            return error(ERR_INVALID_RPC, '"method" field required for jsonrpc request')

        method = body['method']
        if method.count('.') != 1:
            return error(ERR_MISSING_FUNC, 'invalid method ' + method)

        module, function = method.split('.')
        if module not in services:
            return error(ERR_MISSING_FUNC, 'no module ' + module)

        service = services[module]
        if not hasattr(service, function):
            return error(ERR_MISSING_FUNC, 'no function ' + method)

        if not isinstance(params, (list, dict)):
            return error(ERR_INVALID_PARAMS, 'invalid parameter list: {!r}'.format(params))

        args, kwargs = (params, {}) if isinstance(params, list) else ([], params)

        precall(body)
        try:
            response = {'jsonrpc': '2.0', 'id': id,
                        'result': getattr(service, function)(*args, **kwargs)}
            log.debug('returning success message: {!r}', response)
            return response
        except Exception as e:
            errback(e, 'unexpected jsonrpc error calling ' + method)
            message = 'unexpected error'
            if debug:
                message += ': ' + traceback.format_exc()
            return error(ERR_FUNC_EXCEPTION, message)

    return jsonrpc_handler
