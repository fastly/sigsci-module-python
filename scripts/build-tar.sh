#!/bin/sh
set -ex

# Copy selected bits into a tarball
#
#

VERSION=$(cat VERSION)
BASE="sigscimodule-$VERSION"
TARBALL="${BASE}.tar.gz"
DIR="$BASE"

# remove and recreate target directory
rm -rf "$DIR"
mkdir -p "${DIR}/python3/sigscimodule"
mkdir -p "${DIR}/python2/sigscimodule"

# remove junk just to be safe
rm -rf python3/sigscimodule/__pycache__
rm -rf python2/sigscimodule/__pycache__
rm -f python3/sigscimodule/*.pyc
rm -f python2/sigscimodule/*.pyc

# copy base
cp -f VERSION "$DIR"

# copy module files
cp -f python2/sigscimodule/*.py "$DIR/python2/sigscimodule/"
cp -f python3/sigscimodule/*.py "$DIR/python3/sigscimodule/"

# wrap it up
tar -czvf "${TARBALL}" "$BASE"
zip -r "${BASE}.zip" "$BASE"
mkdir -p "./artifacts/sigsci-module-python/src/"
mv -f "${TARBALL}" "./artifacts/sigsci-module-python/src/"
mv -f "${BASE}.zip" "./artifacts/sigsci-module-python/src/"

