import os
import platform
import sys
import os.path
from setuptools import setup, find_packages

pkg_name = 'sideboard'
__here__ = os.path.abspath(os.path.dirname(__file__))

# http://stackoverflow.com/a/16084844/171094
with open(os.path.join(__here__, pkg_name, '_version.py')) as version:
    exec(version.read())
# __version__ is now defined
req_data = open(os.path.join(__here__, 'requirements.txt')).readlines()
raw_requires = [r.strip() for r in req_data if r.strip() != '']

# Ugly hack to reconcile pip requirements.txt and setup.py install_requires
os_name = os.name
sys_platform = sys.platform
platform_release = platform.release()
implementation_name = sys.implementation.name
platform_machine = platform.machine()
platform_python_implementation = platform.python_implementation()
requires = []
for s in reversed(raw_requires):
    if ';' in s:
        req, env_marker = s.split(';')
        if eval(env_marker):
            requires.append(s)
    else:
        requires.append(s)

# testing dependencies
req_data = open(os.path.join(__here__, 'test_requirements.txt')).read()
tests_require = [r.strip() for r in req_data.split() if r.strip() != '']
tests_require = list(reversed(tests_require))

# temporary workaround for a Python 2 CherryPy bug, for which we opened a pull request:
# https://bitbucket.org/cherrypy/cherrypy/pull-request/85/1285-python-2-now-accepts-both-bytestrings/
if sys.version_info[0] == 2:
    requires = ['CherryPy==3.2.2' if 'cherrypy' in r.lower() else r for r in requires]

if __name__ == '__main__':
    setup_requires = {'setup_requires': ['distribute']} if sys.version_info[0] == 2 else {}
    setup(
        name=pkg_name,
        version=__version__,
        description='Sideboard plugin container.',
        license='BSD',
        scripts=[],
        install_requires=requires,
        tests_require=tests_require,
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
        },
        **setup_requires
    )
