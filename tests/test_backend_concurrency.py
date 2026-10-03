"""Shared SQLite connection regressions, always using isolated databases."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import threading
import unittest

from backend.store import Store
from scripts.reproduce_backend_concurrency import reproduce


class BackendConcurrencyTests(unittest.TestCase):
    def test_parallel_http_reads_match_serial_payloads(self):
        result = reproduce(workers=9, rounds=50)
        self.assertEqual(result["sequential"]["requests"], 45)
        self.assertEqual(result["concurrent"]["requests"], 150)
        self.assertEqual(result["sequential"]["failed"], 0, result)
        self.assertEqual(result["concurrent"]["failed"], 0, result)
        self.assertEqual(result["error_examples"], [], result)

    def test_concurrent_duplicate_approval_and_execution(self):
        # Reads, inserts and commits must stay in one protected Store operation.
        # A lock only around one()/rows() still lets duplicate writes race.
        with tempfile.TemporaryDirectory() as directory:
            store = Store(str(Path(directory) / "isolated.db"))
            try:
                store.seed_demo()
                for operation in (store.approve, store.execute):
                    barrier = threading.Barrier(9)

                    def run(_):
                        barrier.wait(timeout=10)
                        return operation("PROP-AC10-001", idem="concurrent-key")

                    with ThreadPoolExecutor(max_workers=9) as pool:
                        results = list(pool.map(run, range(9)))
                    self.assertEqual(len({row["id"] for row in results}), 1)
                self.assertEqual(len(store.rows("SELECT * FROM approvals")), 1)
                self.assertEqual(len(store.execution_tasks()), 1)
                self.assertIsNone(store.proposal("PROP-AC10-001", "another-tenant"))
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
