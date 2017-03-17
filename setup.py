import sys
import os.path
from setuptools import setup, find_packages

pkg_name = 'sideboard'
__here__ = os.path.abspath(os.path.dirname(__file__))

# http://stackoverflow.com/a/16084844/171094
with open(os.path.join(__here__, pkg_name, '_version.py')) as version:
    exec(version.read())
# __version__ is now defined
req_data = open(os.path.join(__here__, 'requirements.txt')).read()
requires = [r.strip() for r in req_data.split() if r.strip() != '']
requires = list(reversed(requires))

# temporary workaround for a Python 2 CherryPy bug, for which we opened a pull request:
# https://bitbucket.org/cherrypy/cherrypy/pull-request/85/1285-python-2-now-accepts-both-bytestrings/
if sys.version_info[0] == 2:
    requires = ['CherryPy==3.2.2' if 'cherrypy' in r.lower() else r for r in requires]

if __name__ == '__main__':
    setup(
        name=pkg_name,
        version=__version__,
        description='Sideboard plugin container.',
        license='BSD',
        scripts=[],
        install_requires=requires,
        packages=find_packages(),
        include_package_data=True,
        package_data={pkg_name: []},
        zip_safe=False,
        entry_points={
            'console_scripts': [
                'sep = sideboard.sep:run_plugin_entry_point'
            ]
        },
        extras_require={
            'perftrace': ['python-prctl>=1.6.1', 'psutil>=4.3.0']
        }
    )
