"""Import the application against one process-owned temporary database.

Use the canonical tests.backend_fixture import in both module and discovery
runs so the backend's import-time Store never opens the repository database.
"""

import atexit
import importlib
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch


if "backend.api" in sys.modules:
    raise RuntimeError("Import tests.backend_fixture before backend.api to isolate its database")

_temporary = tempfile.TemporaryDirectory(prefix="inventory-backend-tests-")
database = Path(_temporary.name) / "bootstrap.db"
try:
    with patch.dict(os.environ, {"INVENTORY_AGENT_DB": str(database), "INVENTORY_AGENT_MODE": "demo"}):
        api = importlib.import_module("backend.api")
except BaseException:
    _temporary.cleanup()
    raise

# Individual tests may patch api.store. Cleanup only the connection we created.
_initial_store = api.store


@atexit.register
def cleanup():
    try:
        _initial_store.close()
    finally:
        _temporary.cleanup()
