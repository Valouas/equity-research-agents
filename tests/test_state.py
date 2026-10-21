import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from stockbot.state import State


class StateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = State(Path(self.tmp.name) / "state.sqlite")

    def tearDown(self):
        self.state.close()
        self.tmp.cleanup()

    def test_failed_symbol_does_not_block_unvisited_symbols(self):
        self.state.upsert_universe([{"symbol": "A.US"}, {"symbol": "B.US"}])
        self.state.fail("A.US", "unavailable")
        self.assertEqual(self.state.queue(1), ["B.US"])

    def test_explicit_list_rotates_when_a_per_run_limit_is_used(self):
        symbols = ["A.US", "B.US", "C.US"]
        self.state.upsert_universe([{"symbol": symbol} for symbol in symbols])
        self.assertEqual(self.state.queue_subset(symbols, 1), ["A.US"])
        self.state.fail("A.US", "unavailable")
        self.assertEqual(self.state.queue_subset(symbols, 1), ["B.US"])

    def test_unknown_priority_does_not_displace_an_active_security(self):
        symbols = [f"A{i}.US" for i in range(5)]
        self.state.upsert_universe([{"symbol": symbol} for symbol in symbols])
        self.assertNotIn("UNKNOWN.US", self.state.queue(5, ["UNKNOWN.US"]))

    def test_isin_dedup_does_not_merge_unknown_identifiers(self):
        self.state.upsert_universe([
            {"symbol": "A.US", "isin": "US1234567890"},
            {"symbol": "A.F", "isin": "US1234567890"},
            {"symbol": "B.US"}, {"symbol": "C.US"},
        ])
        self.assertEqual(self.state.universe_count(), 3)

    def test_report_freshness_uses_retrieval_not_rerun_timestamp(self):
        self.state.upsert_universe([{"symbol": "A.US"}, {"symbol": "B.US"}])
        now = datetime.now(timezone.utc)
        self.state.record("A.US", "run1", {"symbol": "A.US", "retrieved_at": (now - timedelta(days=30)).isoformat()})
        self.state.record("B.US", "run1", {"symbol": "B.US", "retrieved_at": now.isoformat()})
        self.assertEqual([x["symbol"] for x in self.state.latest_results(7)], ["B.US"])

    def test_new_abstention_replaces_previous_rank_in_current_report(self):
        self.state.upsert_universe([{"symbol": "A.US"}])
        now = datetime.now(timezone.utc).isoformat()
        self.state.record("A.US", "run1", {"symbol": "A.US", "retrieved_at": now, "score": 90})
        self.state.record("A.US", "run2", {"symbol": "A.US", "retrieved_at": now, "score": None})
        self.assertIsNone(self.state.latest_results(7)[0]["score"])

    def test_disabling_a_symbol_keeps_its_audit_history(self):
        self.state.upsert_universe([{"symbol": "A.US"}])
        self.state.record("A.US", "run1", {"symbol": "A.US", "retrieved_at": datetime.now(timezone.utc).isoformat()})
        self.state.upsert_universe([{"symbol": "B.US"}], replace_active=True)
        self.assertEqual(self.state.latest_results(7), [])
        self.assertEqual(self.state.db.execute("SELECT COUNT(*) FROM analyses").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
