from __future__ import unicode_literals
import time
import os.path

import yaml
import ship_it


__here__ = os.path.abspath(os.path.dirname(__file__))
MANIFEST_YAML = os.path.join(__here__, 'manifest.yaml')
MANIFEST_TEMPLATE = MANIFEST_YAML + '.template'


def _populate_manifest_and_invoke_fpm(iteration):
    import sideboard
    with open(MANIFEST_TEMPLATE) as f:
        manifest = yaml.load(f)
        manifest[b'version'] = sideboard.__version__
        manifest[b'iteration'] = iteration

    with open(MANIFEST_YAML, 'w') as f:
        yaml.dump(manifest, f)

    ship_it.fpm(MANIFEST_YAML)


def fpm_stable(iteration):
    _populate_manifest_and_invoke_fpm(iteration)


def fpm_testing():
    _populate_manifest_and_invoke_fpm(b'0.{}'.format(int(time.time())))
