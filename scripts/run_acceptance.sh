#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
python3 -m py_compile backend/*.py
node --check app.js
node --test tests/*.mjs
python3 sample-data/generate.py --check
python3 -m unittest discover -s tests -v

