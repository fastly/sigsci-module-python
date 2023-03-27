#!/usr/bin/env python

from setuptools import setup
import sys

# Fetch the major Python version number
pkgdir = {"": "python%s" % sys.version_info[0]}

setup(
    name='sigscimodule',
    version='1.4.1',
    description='Fastly Python Module',
    package_dir=pkgdir,
    packages=['sigscimodule'],
)
