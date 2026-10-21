"""End-to-end offline entry points, bounded local enrichment, and input safety."""
import contextlib
import copy
import io
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from stockbot.cli import ROOT, load_config, parser, run_scan
from stockbot.inputs import load_companies, sample_companies


AS_OF = date(2026, 10, 6)


class SimulatedClient:
    """A deterministic test double; it performs no model inference."""
    def __init__(self, *args, **kwargs):
        self.model = kwargs.get("model", "test-local")
        self.calls_used = 0

    def chat(self, *, role, prompt, evidence_bundle, schema):
        self.calls_used += 1
        ids = list(evidence_bundle["evidence"])[:1]
        if role == "decision":
            return {"action": "shortlist", "evidence_ids": ids,
                    "reasons": ["Réponse synthétique de test."], "conditions_to_reconsider": []}
        return {"status": "support", "evidence_ids": ids, "reasons": ["Réponse synthétique de test."],
                "missing_data": [], "hypotheses": []}


class InputAndCliTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config(ROOT / "config.json")

    def run_offline(self, arguments, config=None):
        with tempfile.TemporaryDirectory() as directory:
            args = parser().parse_args(arguments + ["--output", directory])
            with contextlib.redirect_stdout(io.StringIO()), patch("stockbot.cli._today", return_value=AS_OF), \
                    patch("stockbot.cli.EODHDProvider", side_effect=AssertionError("Unexpected market-data connection")), \
                    patch("stockbot.llm.request.build_opener", side_effect=AssertionError("Unexpected model connection")), \
                    patch("stockbot.cli.notify_telegram") as notify:
                code = run_scan(config or self.config, args)
            notify.assert_not_called()
            self.assertEqual(code, 0)
            return json.loads((Path(directory) / "results.json").read_text())

    def test_sample_exercises_all_four_decisions_without_any_connection(self):
        data = self.run_offline(["--sample"])
        self.assertEqual({r["research"]["decision"]["action"] for r in data["results"]},
                         {"shortlist", "watch", "avoid", "abstain"})
        for result in data["results"]:
            self.assertEqual(result["research"]["data_kind"], "synthetic")
            self.assertEqual(result["research"]["llm"]["calls"], 0)
            self.assertEqual(result["research"]["execution_mode"], "rules")

    def test_actual_input_snapshot_is_not_redated_when_read(self):
        company = sample_companies(AS_OF)[0]
        company["provider_updated_at"] = "2020-01-01"
        company["is_synthetic"] = False
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            path.write_text(json.dumps({"schema_version": "0.2", "companies": [company]}))
            data = self.run_offline(["--input", str(path)])
            self.assertEqual(json.loads(path.read_text())["companies"][0]["provider_updated_at"], "2020-01-01")
        result = data["results"][0]
        self.assertEqual(result["research"]["data_kind"], "provided")
        self.assertEqual(result["research"]["decision"]["action"], "abstain")
        self.assertGreater(result["snapshot_age_days"], 2000)

    def test_local_model_enrichment_selects_only_the_bounded_best_eligible_dossier(self):
        config = copy.deepcopy(self.config)
        config["agents"].update(backend="ollama", model="test-local", max_llm_companies=1)
        with patch("stockbot.llm.OllamaClient", SimulatedClient):
            data = self.run_offline(["--sample"], config)
        selected = [r for r in data["results"] if r["research"]["llm"]["calls"]]
        self.assertEqual([r["symbol"] for r in selected], ["ALPHA.SYN"])
        self.assertEqual(selected[0]["research"]["llm"]["calls"], 8)
        for result in data["results"]:
            if result["symbol"] != "ALPHA.SYN":
                self.assertEqual(result["research"]["execution_mode"], "rules")
                self.assertEqual(result["research"]["decision"]["llm_status"], "skipped")

    def test_sample_dates_remain_admissible_in_january_and_after_march(self):
        for when in (date(2027, 1, 15), date(2027, 3, 1), date(2028, 2, 29)):
            with self.subTest(when=when):
                for company in sample_companies(when):
                    self.assertTrue(company["is_synthetic"])
                    self.assertLessEqual(date.fromisoformat(company["annual"][0]["filing_date"]), when)
                    self.assertLessEqual((when - date.fromisoformat(company["annual"][0]["date"])).days, 550)

    def test_strict_input_rejects_duplicates_nonfinite_values_and_url_symbols(self):
        cases = ['{"companies":[],"companies":[]}',
                 '{"companies":[{"symbol":"X","annual":[],"valuation":{"trailing_pe":NaN}}]}',
                 '{"companies":[{"symbol":"https://example.test/x","annual":[]}]}']
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            for body in cases:
                path.write_text(body)
                with self.subTest(body=body), self.assertRaises(ValueError):
                    load_companies(path)

    def test_synthetic_container_marks_every_dossier(self):
        company = sample_companies(AS_OF)[0]
        company.pop("is_synthetic")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.json"
            path.write_text(json.dumps({"schema_version": "0.2", "data_kind": "synthetic", "companies": [company]}))
            loaded = load_companies(path)
        self.assertTrue(loaded[0]["is_synthetic"])

    def test_duplicate_security_is_not_counted_twice(self):
        companies = sample_companies(AS_OF)[:2]
        companies[1]["symbol"] = companies[0]["symbol"].lower()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.json"
            path.write_text(json.dumps(companies))
            with self.assertRaises(ValueError):
                load_companies(path)


if __name__ == "__main__":
    unittest.main()
