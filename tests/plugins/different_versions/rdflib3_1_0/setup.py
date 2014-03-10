import os.path
from setuptools import setup, find_packages

pkg_name = 'rdflib3_1_0'

if __name__ == '__main__':
    setup(
        name=pkg_name,
        version='0.1',
        description='A Sideboard plugin with a single dependency, for testing.',
        license='COMPANY-PROPRIETARY',
        scripts=[],
        setup_requires=['distribute'],
        install_requires=[],
        packages=find_packages(),
        #dependency_links=['http://pypi.wt.sec/all-packages'],
        include_package_data=True,
        package_data={pkg_name: []},
        zip_safe=False
    )

