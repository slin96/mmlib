#!/bin/bash

# operate in the current dir
cd "$(dirname "$0")"

VENV=./venv

python3 -m venv $VENV
source $VENV/bin/activate
python3 -m pip install --upgrade pip

# install requirements
python3 -m pip install --upgrade setuptools wheel
# TODO use corect requirements
python3 -m pip install -r requirements-tests.txt

python3 setup.py sdist bdist_wheel