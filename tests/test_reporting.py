"""Behavior and security checks for the local reporting boundary."""

import copy
import csv
import json
import math
import tempfile
import unittest
from pathlib import Path

from stockbot.reporting import render_alert, write_reports


def company(symbol="GOOD", score=80, status="ranked", **changes):
    result = {
        "symbol": symbol,
        "name": f"Société {symbol}",
        "country": "US",
        "sector": "Technology",
        "phase": {"id": 4, "name": "Expansion", "reason": "Croissance et rentabilité observées.", "profit_metric": "Résultat opérationnel"},
        "metrics": {"revenue": 1200000, "revenue_growth_pct": 12.5},
        "score": score,
        "coverage_pct": 90,
        "status": status,
        "strengths": ["Marge positive"],
        "risks": ["Valorisation élevée"],
        "checks": [{"label": "Marge", "value": 12, "passed": True, "points": 10, "max_points": 10}],
        "financial_date": "2025-12-31",
        "source_url": "https://example.org/financials?symbol=GOOD&year=2025",
        "retrieved_at": "2026-10-06T16:00:00Z",
        "valuation": {"pe_ratio": 30},
    }
    result.update(changes)
    return result


class ReportingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.summary = {"generated_at": "2026-10-06T16:00:00Z", "mode": "live", "universe_total": 100, "attempted_count": 3, "remaining_count": 97}

    def reports(self, results, summary=None):
        paths = write_reports(results, self.summary if summary is None else summary, self.directory)
        document = Path(paths["html"]).read_text(encoding="utf-8")
        return paths, document

    def test_only_eligible_finite_scores_are_ranked_and_sorted(self):
        results = [
            company("LOW", 50), company("HIGH", 90),
            company("SPEC", 99, "specialist_review"),
            company("STALE", 95, "stale_data"),
            company("EMPTY", None), company("INFINITY", math.inf),
            company("ZERO", 0), company("BOOL", True),
        ]
        paths, document = self.reports(results)
        ranking = document.split('id="ranking"', 1)[1].split("</table>", 1)[0]
        self.assertLess(ranking.index(">HIGH</a>"), ranking.index(">LOW</a>"))
        self.assertLess(ranking.index(">LOW</a>"), ranking.index(">ZERO</a>"))
        for symbol in ("SPEC", "STALE", "EMPTY", "INFINITY", "BOOL"):
            self.assertNotIn(f">{symbol}</a>", ranking)
            self.assertIn(f">{symbol}</a>", document)
        payload = json.loads(Path(paths["json"]).read_text(encoding="utf-8"))
        self.assertEqual([item["symbol"] for item in payload["results"][:3]], ["HIGH", "LOW", "ZERO"])

    def test_missing_values_do_not_crash_or_invent_a_ranking(self):
        _, document = self.reports([{}, {"symbol": "NO-DATA", "status": "insufficient_data"}], {})
        self.assertIn("Non fourni", document)
        self.assertIn("Aucune société ne dispose actuellement", document)
        self.assertIn("Données insuffisantes ou non classées", document)
        self.assertNotIn('id="ranking"', document)
        self.assertIn("Aucune mesure fournie", document)

    def test_phase_families_have_separate_rankings_and_alert_sections(self):
        data = [company("MATURE", 70, ranking_bucket="profitable_growth"),
                company("EARLY", 99, ranking_bucket="early_stage"),
                company("TRANSITION", 95, ranking_bucket="transition")]
        paths, document = self.reports(data)
        first = document.split('id="ranking"', 1)[1].split("</table>", 1)[0]
        self.assertIn(">MATURE</a>", first)
        self.assertNotIn(">EARLY</a>", first)
        self.assertNotIn(">TRANSITION</a>", first)
        self.assertEqual(document.count('class="rank-table"'), 3)
        self.assertIn("ne constituent pas un classement commun", document)
        alert = render_alert(data, dict(self.summary, top_n=3))
        for symbol in ("MATURE", "EARLY", "TRANSITION"):
            self.assertIn(f"1. {symbol}", alert)
        with Path(paths["csv"]).open(encoding="utf-8-sig", newline="") as handle:
            self.assertIn("ranking_bucket", csv.DictReader(handle).fieldnames)

    def test_metric_units_match_engine_fractions_deltas_and_multiples(self):
        _, document = self.reports([company(metrics={
            "revenue_cagr": 0.125, "operating_margin_change": 0.025,
            "cash_runway_years": 1.5, "net_debt_to_fcf": 2.3,
        })])
        self.assertIn("12,5 %", document)
        self.assertIn("2,5 points de %", document)
        self.assertIn("1,5 ans", document)
        self.assertIn("2,3 ×", document)

    def test_demo_scope_and_score_caveats_are_explicit(self):
        summary = dict(self.summary, mode="demo")
        _, document = self.reports([company("AAPL")], summary)
        self.assertIn("TEST TECHNIQUE — univers limité à Apple, Amazon et Tesla ; aucune sélection mondiale", document)
        self.assertIn("Il ne représente ni une probabilité de gain", document)
        self.assertIn("Elle ne mesure pas les chances de réussite", document)
        self.assertIn("2025-12-31", document)
        self.assertIn("Données récupérées le", document)

    def test_untrusted_content_is_escaped_in_every_html_surface(self):
        attack = '<img src=x onerror="alert(1)">'
        item = company(
            symbol=attack, name=attack, country=attack, sector=attack,
            financial_date=attack, retrieved_at=attack,
            phase={"name": attack, "reason": attack, "profit_metric": attack},
            strengths=[attack], risks=[attack],
            checks=[{"label": attack, "value": attack, "passed": None, "points": None, "max_points": 10}],
            metrics={attack: attack}, valuation={attack: attack},
            source_url='javascript:alert("XSS")',
        )
        summary = dict(self.summary, generated_at=attack, run_id=attack, notes=[attack], errors=[{"symbol": attack, "error": attack}])
        _, document = self.reports([item], summary)
        self.assertNotIn("<img", document)
        self.assertNotIn('href="javascript:', document)
        self.assertIn("&lt;img src=x onerror=&quot;alert(1)&quot;&gt;", document)
        self.assertEqual(document.count("<script>"), 1)
        self.assertIn("Lien HTTPS indisponible", document)

    def test_only_valid_https_source_links_are_clickable(self):
        urls = ["javascript:alert(1)", "data:text/html,bad", "http://example.org", "//example.org",
                "https://user:pass@example.org", "https://example.org:99999", "https://exa\nmple.org", "https://example.org\\evil"]
        for url in urls:
            with self.subTest(url=url):
                _, document = self.reports([company(source_url=url)])
                self.assertNotIn("Consulter la source ↗", document)
        _, document = self.reports([company(source_url="https://example.org/a?x=1&y=2")])
        self.assertIn('href="https://example.org/a?x=1&amp;y=2"', document)
        self.assertIn('rel="noopener noreferrer"', document)

    def test_csv_guards_formula_cells_and_preserves_plain_data(self):
        item = company("=SUM(1,2)", name=" \t+cmd", country="@payload", sector="-payload", strengths=["=HYPERLINK(\"bad\")"])
        paths, _ = self.reports([item])
        with Path(paths["csv"]).open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 1)
        for field in ("symbol", "name", "country", "sector", "strengths"):
            self.assertTrue(rows[0][field].startswith("'"), field)
        self.assertEqual(rows[0]["financial_date"], "2025-12-31")
        self.assertEqual(rows[0]["score"], "80")
        self.assertEqual(json.loads(rows[0]["metrics_json"])["revenue_growth_pct"], 12.5)

    def test_json_is_strict_and_nonfinite_values_are_null(self):
        item = company(metrics={"nan": math.nan, "nested": [math.inf, -math.inf]})
        summary = dict(self.summary, units_used=math.inf)
        paths, document = self.reports([item], summary)
        raw = Path(paths["json"]).read_text(encoding="utf-8")
        payload = json.loads(raw, parse_constant=lambda value: self.fail(f"Nonstandard JSON: {value}"))
        self.assertIsNone(payload["summary"]["units_used"])
        self.assertEqual(payload["results"][0]["metrics"], {"nan": None, "nested": [None, None]})
        self.assertNotIn(">inf<", document)
        self.assertNotIn(">nan<", document)

    def test_output_is_deterministic_inputs_unmodified_and_paths_absolute(self):
        data = [company("B", 50), company("A", 50)]
        original_data = copy.deepcopy(data)
        original_summary = copy.deepcopy(self.summary)
        paths, first_document = self.reports(data)
        first_bytes = {key: Path(path).read_bytes() for key, path in paths.items()}
        paths_again, second_document = self.reports(data)
        self.assertEqual(first_document, second_document)
        self.assertEqual(first_bytes, {key: Path(path).read_bytes() for key, path in paths_again.items()})
        self.assertTrue(all(Path(path).is_absolute() for path in paths.values()))
        self.assertEqual(set(paths), {"html", "csv", "json"})
        self.assertEqual(data, original_data)
        self.assertEqual(self.summary, original_summary)

    def test_alert_is_bounded_and_excludes_ineligible_companies(self):
        data = [company("TOP", 80), company("SPECIAL", 99, "specialist_review")]
        summary = dict(self.summary, mode="demo", top_n=10)
        alert = render_alert(data, summary)
        self.assertIn("TEST TECHNIQUE", alert)
        self.assertIn("TOP", alert)
        self.assertNotIn("SPECIAL", alert)
        self.assertIn("Score heuristique ≠ probabilité", alert)
        self.assertIn("2025-12-31", alert)
        very_long = [company(str(index), name="x" * 5000) for index in range(50)]
        alert = render_alert(very_long, dict(summary, generated_at="x" * 5000))
        self.assertLessEqual(len(alert), 3500)


if __name__ == "__main__":
    unittest.main()
