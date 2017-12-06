from __future__ import unicode_literals, print_function
import ssl
import socket
from contextlib import closing

import six
from six.moves.urllib_parse import urlparse

from sideboard.lib import services, entry_point


def _check(url, **ssl_params):
    status = ['checking {}'.format(url)]

    try:
        parsed = urlparse(url)
    except Exception as e:
        return status + ['failed to parse url: {!s}'.format(e)]
    else:
        host = parsed.hostname
        port = parsed.port or (443 if parsed.scheme in ['https', 'wss'] else 80)
        status.append('using hostname {} and port {}'.format(host, port))

    try:
        ip = socket.gethostbyname(host)
    except Exception as e:
        return status + ['failed to resolve host with DNS: {!s}'.format(e)]
    else:
        status.append('successfully resolved host {} to {}'.format(host, ip))

    sock = None
    try:
        sock = socket.create_connection((host, port))
    except Exception as e:
        return status + ['failed to establish a socket connection to {} on port {}: {!s}'.format(host, port, e)]
    else:
        status.append('successfully opened socket connection to {}:{}'.format(host, port))

    # check if any of the non-version SSL options have been set
    if any(val for val in ssl_params.values() if not isinstance(val, int)):
        try:
            wrapped = ssl.wrap_socket(sock, **ssl_params)
        except Exception as e:
            return status + ['failed to complete SSL handshake ({}): {!s}'.format(ssl_params, e)]
        else:
            status.append('succeeded at SSL handshake (without validating server cert)')
        finally:
            if sock:
                sock.close()

        try:
            with closing(socket.create_connection((host, port))) as sock:
                wrapped = ssl.wrap_socket(sock, **dict(ssl_params, cert_reqs=ssl.CERT_REQUIRED))
                status.append('succeeded at validating server cert')
        except Exception as e:
            return status + ['failed to validate server cert ({}): {!s}'.format(ssl_params, e)]

    status.append('everything seems to work')
    return status


def check_all():
    checks = {}
    for name, jservice in services._jsonrpc.items():
        jproxy = jservice._send.im_self if six.PY2 else jservice._send.__self__  # ugly kludge to get the ServerProxy object
        url = '{}://{}/'.format(jproxy.type, jproxy.host)
        checks[name] = _check(url, **jproxy.ssl_opts)
    return checks


@entry_point
def check_connections():
    for service, results in sorted(check_all().items()):
        print(service)
        print('-' * len(service))
        print('\n'.join(results) + '\n')
