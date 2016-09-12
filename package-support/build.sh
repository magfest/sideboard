#!/bin/bash -ex

# build the virtual environment
rm -rf *.egg-info
rm -rf *.egg
find . -name "*.pyc" -exec rm -rf {} \;

# this job is going to assume that the plugins are cloned into the
# appropriate place
/usr/bin/paver-2.7 run_all_assertions
/usr/bin/paver-2.7 make_venv
source ./env/bin/activate

py.test sideboard -m 'not functional' --junitxml=results.xml
coverage run --omit="plugins/*" -m py.test sideboard -m 'not functional'
coverage report
coverage html
echo "testing Complete"
