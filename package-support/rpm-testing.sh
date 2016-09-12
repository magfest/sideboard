#!/bin/bash -ex

# Fact: packaging is the worst thing about Python.
# For reasons we haven't entirely figured out yet, even though we're upgrading,
# the distribute egg must be removed before we can install build dependencies,
# and then it must be restored before running fabric - bleh.

echo "Begin Build"

export distribute_egg=`ls distribute*.egg`
source env/bin/activate
mv $distribute_egg $distribute_egg.backup
pip install --upgrade setuptools
pip install fabric
pip install ship_it==0.2.0
mv $distribute_egg.backup $distribute_egg
fab fpm_testing

