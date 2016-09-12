# Must manually create the following files:
#
# ~/.pydistutils.cfg
# [easy_install]
# index_url = http://pypi.services.zz
# 
# ~/.pip/pip.conf
# [global]
# index-url = http://pypi.services.zz

all: build rpm-testing

build:
	package-support/build.sh

rpm: rpm-testing

rpm-testing: 
	package-support/rpm-testing.sh

rpm-stable: 
	package-support/rpm-stable.sh

clean:
	rm -rf htmlcov build env sideboard.egg-info 
	rm -f .coverage results.xml manifest.yaml *.rpm sideboard-bootstrap.py

