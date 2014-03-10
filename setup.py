import os.path
from setuptools import setup, find_packages

pkg_name = 'sideboard'
__here__ = os.path.abspath(os.path.dirname(__file__))
execfile(os.path.join(__here__, pkg_name, '_version.py'))
req_data = open(os.path.join(__here__, 'requirements.txt')).read()
requires = [r.strip() for r in req_data.split() if r.strip() != '']
requires = list(reversed(requires))

if __name__ == '__main__':
    setup(
        name=pkg_name,
        version=__version__,
        description='Sideboard plugin container.',
        license='BSD',
        scripts=[],
        setup_requires=['distribute'],
        install_requires=requires,
        packages=find_packages(),
        include_package_data=True,
        package_data={pkg_name: []},
        zip_safe=False,
        entry_points = {
            'console_scripts': [
                'sep = sideboard.sep:run_plugin_entry_point'
            ]
        }
    )
