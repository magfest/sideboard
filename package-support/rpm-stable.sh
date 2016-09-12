#!/bin/bash -ex

# Fact: packaging is the worst thing about Python.
# For reasons we haven't entirely figured out yet, even though we're upgrading,
# the distribute egg must be removed before we can install build dependencies,
# and then it must be restored before running fabric - bleh.

echo "Begin Build"

if [ "$TAGNAME" = "" ] ;then
  echo "Error: must set TAGNAME to build stable RPM"
  exit 1
fi

git checkout $TAGNAME
export RELVERSION=`echo $TAGNAME | awk -F- '{print $2}'`
export distribute_egg=`ls distribute*.egg`

source ./env/bin/activate

mv $distribute_egg $distribute_egg.backup
pip install --upgrade setuptools
pip install fabric
pip install ship_it==0.2.0
mv $distribute_egg.backup $distribute_egg

fab fpm_stable:$RELVERSION


