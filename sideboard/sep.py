from __future__ import unicode_literals
from sys import argv

from sideboard.lib import _entry_points
from sideboard.internal.imports import use_plugin_virtualenv


def run_plugin_entry_point():
    if len(argv) < 2:
        print('usage: {} ENTRY_POINT_NAME ...'.format(argv[0]))
        exit(1)
    
    if len(argv) == 2 and argv[1] in ['-h', '--help']:
        print('known entry points:')
        print('\n'.join(sorted(_entry_points)))
        exit(0)
    
    del argv[:1]  # we want the entry point name to be the first argument
    
    ep_name = argv[0]
    if ep_name not in _entry_points:
        print('no entry point exists with name {!r}'.format(ep_name))
        exit(2)
    
    func = _entry_points[ep_name]
    plugin_name = func.__module__.split('.')[0]
    with use_plugin_virtualenv(plugin_name):
        func()


if __name__ == '__main__':
    run_plugin_entry_point()
