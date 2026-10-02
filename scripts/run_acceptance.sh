#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
python3 -m py_compile backend/*.py
node --check app.js
python3 -m unittest discover -s tests -v

