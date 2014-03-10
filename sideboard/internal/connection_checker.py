from __future__ import unicode_literals, print_function
import ssl
import socket
from urlparse import urlparse
from contextlib import closing

from rpctools.jsonrpc import ServerProxy

from sideboard.lib import config, services, entry_point


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
    
    try:
        sock = socket.create_connection((host, port))
    except Exception as e:
        return status + ['failed to establish a socket connection to {} on port {}: {!s}'.format(host, port, e)]
    else:
        status.append('successfully opened socket connection to {}:{}'.format(host, port))
    
    if any(ssl_params.values()):
        try:
            wrapped = ssl.wrap_socket(sock, **ssl_params)
        except Exception as e:
            return status + ['failed to complete SSL handshake ({}): {!s}'.format(ssl_params, e)]
        else:
            status.append('succeeded at SSL handshake')
    
    status.append('everything seems to work')
    
    return status


def check_all():
    checks = {
        'subscription (jsonrpc)': _check(config['subscription']['jsonrpc_url'],
                                    ca_certs=config['subscription']['subscription_ca'],
                                    keyfile=config['subscription']['subscription_client_key'],
                                    certfile=config['subscription']['subscription_client_cert']),
        'subscription (websockets)': _check(config['subscription']['ws_url'], 
                                       ca_certs=config['subscription']['subscription_ca'],
                                       keyfile=config['subscription']['subscription_client_key'],
                                       certfile=config['subscription']['subscription_client_cert'])
    }
    
    # this whole block of code is terrible
    for name, service in services.get_services().items():
        if service.__class__.__name__ == '_Method':
            proxy = service._send.im_self
            url = '{}://{}/'.format(proxy.type, proxy.host)
            checks[name] = _check(url, ca_certs=proxy.ca_certs, keyfile=proxy.key_file, certfile=proxy.cert_file)
    
    return checks


@entry_point
def check_connections():
    for service, results in sorted(check_all().items()):
        print(service)
        print('-' * len(service))
        print('\n'.join(results) + '\n')
