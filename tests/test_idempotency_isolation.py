"""幂等键必须按租户、操作类型和目标方案隔离。

幂等键由客户端通过 Idempotency-Key 请求头提供，不能让一个租户的键命中另一个租户的记录。
"""

from pathlib import Path
import tempfile
import unittest

from backend.store import Store

OTHER_TENANT = "tenant-b"
OTHER_PROPOSAL = "PROP-B-001"


class IdempotencyIsolationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.store = Store(self.tmp.name)
        self.store.seed_demo()
        self._add_pending_proposal(OTHER_PROPOSAL, OTHER_TENANT)

    def tearDown(self):
        self.store.close()
        Path(self.tmp.name).unlink(missing_ok=True)

    def _add_pending_proposal(self, proposal_id, tenant_id):
        self.store.conn.execute(
            "INSERT INTO proposals(id, tenant_id, risk_id, current_version, status, snapshot_id, fact_version, created_at) VALUES(?,?,?,?,?,?,?,?)",
            (proposal_id, tenant_id, 1, 1, "pending_approval", "snapshot-demo-v1", 1, "2026-10-03T00:00:00"),
        )
        self.store.conn.execute(
            "INSERT INTO proposal_versions(id, proposal_id, version, payload_json, status, invalid_reason, created_at) VALUES(?,?,?,?,?,?,?)",
            ("PV-" + proposal_id, proposal_id, 1, "{}", "pending_approval", None, "2026-10-03T00:00:00"),
        )
        self.store.conn.commit()

    def test_same_key_in_other_tenant_does_not_return_foreign_approval(self):
        mine = self.store.approve("PROP-AC10-001", tenant_id="demo", idem="shared-key")
        theirs = self.store.approve(OTHER_PROPOSAL, tenant_id=OTHER_TENANT, idem="shared-key")
        self.assertEqual(mine["tenant_id"], "demo")
        self.assertEqual(theirs["tenant_id"], OTHER_TENANT)
        self.assertEqual(theirs["proposal_id"], OTHER_PROPOSAL)

    def test_same_key_in_other_tenant_does_not_return_foreign_execution_task(self):
        self.store.approve("PROP-AC10-001", tenant_id="demo", idem="a-1")
        self.store.approve(OTHER_PROPOSAL, tenant_id=OTHER_TENANT, idem="b-1")
        mine = self.store.execute("PROP-AC10-001", tenant_id="demo", idem="shared-key")
        theirs = self.store.execute(OTHER_PROPOSAL, tenant_id=OTHER_TENANT, idem="shared-key")
        self.assertEqual(mine["tenant_id"], "demo")
        self.assertEqual(theirs["tenant_id"], OTHER_TENANT)
        self.assertEqual(theirs["proposal_id"], OTHER_PROPOSAL)

    def test_same_key_for_different_proposal_in_same_tenant_is_not_confused(self):
        self._add_pending_proposal("PROP-DEMO-002", "demo")
        first = self.store.approve("PROP-AC10-001", tenant_id="demo", idem="reused-key")
        second = self.store.approve("PROP-DEMO-002", tenant_id="demo", idem="reused-key")
        self.assertEqual(first["proposal_id"], "PROP-AC10-001")
        self.assertEqual(second["proposal_id"], "PROP-DEMO-002")

    def test_same_key_same_proposal_is_still_idempotent(self):
        first = self.store.approve("PROP-AC10-001", tenant_id="demo", idem="retry-key")
        again = self.store.approve("PROP-AC10-001", tenant_id="demo", idem="retry-key")
        self.assertEqual(first["id"], again["id"])

    def test_other_tenant_cannot_pass_through_foreign_proposal(self):
        with self.assertRaises(ValueError):
            self.store.approve("PROP-AC10-001", tenant_id=OTHER_TENANT, idem="any-key")

    def test_scoped_key_encoding_has_no_field_boundary_ambiguity(self):
        # tenant 与客户端键都来自请求头，可以含分隔符；不同字段组合不能拼出同一个键。
        one = Store._scoped_idem("x", "approve", "P", "approve|P2|k2")
        two = Store._scoped_idem("x|approve|P", "approve", "P2", "k2")
        self.assertNotEqual(one, two)


if __name__ == "__main__":
    unittest.main()
