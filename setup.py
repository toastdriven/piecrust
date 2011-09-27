#!/usr/bin/env python
# -*- coding: utf-8 -*-
try:
    from setuptools import setup
except ImportError:
    from ez_setup import use_setuptools
    use_setuptools()
    from setuptools import setup

setup(
    name='piecrust',
    version='1.0.0-beta',
    description='A flexible & capable REST API layer for Python.',
    author='Daniel Lindsley',
    author_email='daniel@toastdriven.com',
    url='http://github.com/toastdriven/piecrust/',
    long_description=open('README.rst', 'r').read(),
    packages=[
        'piecrust',
        'piecrust.utils',
    ],
    requires=[
        'mimeparse',
        'python_dateutil(>=1.5, < 2.0)',
    ],
    install_requires=[
        'mimeparse',
        'python_dateutil >= 1.5, < 2.0',
    ],
    classifiers=[
        'Development Status :: 4 - Beta',
        'Environment :: Web Environment',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: BSD License',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Topic :: Utilities'
    ],
)
