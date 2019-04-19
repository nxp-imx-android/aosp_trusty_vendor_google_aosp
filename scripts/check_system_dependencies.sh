#!/bin/bash

set -e
set -u

DEPS=(libpixman-1-dev libstdc++-8-dev)

if dpkg -V ${DEPS[@]}; then
  echo "System dependencies appear to be installed."
else
  echo
  echo "There appear to be missing system dependencies. Please run:"
  echo
  echo "sudo apt-get install ${DEPS[@]}"
  echo
  exit 1
fi
