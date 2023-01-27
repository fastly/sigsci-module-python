#!/bin/sh -ex
rm -rf *.pyc python[23]/sigscimodule/*.pyc __pycache__ python[23]/sigscimodule/__pycache__
rm -rf sigscimodule-* bin build *.rpm *.deb *.apk python[23]/*.egg-info *.egg-info
rm -rf artifacts
rm -rf build build-tar
find . -name '*.log' | xargs rm -rf
