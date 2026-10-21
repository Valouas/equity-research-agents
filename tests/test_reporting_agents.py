"""Transparency, provenance and decision boundaries of the V0.2 reports."""

import copy
import csv
import json
import math
import tempfile
import unittest
from pathlib import Path

from stockbot.reporting import render_alert, write_reports


def research(action="watch", data_kind="provided"):
    agent_ids = ["data_quality", "fundamentals", "growth", "valuation", "risk", "documents", "challenger"]
    return {
        "version": "0.2", "as_of": "2026-10-06", "data_kind": data_kind,
        "backend_requested": "rules", "execution_mode": "rules",
        "evidence": {
            "revenue_2025": {
                "path": "annual[0].revenue", "value": 1500000, "period": "2025-12-31", "unit": "EUR",
                "source_url": "https://example.org/annual?year=2025&lang=fr",
                "published_at": "2026-03-15", "retrieved_at": "2026-10-05T12:00:00Z", "kind": "financial",
            },
        },
        "agents": [{
            "agent_id": agent_id, "role": agent_id, "status": "support",
            "execution_status": "completed", "method": "rules", "evidence_ids": ["revenue_2025"],
            "reasons": ["Progression documentée dans le dossier de test."],
            "hypotheses": ["La croissance se poursuit, hypothèse à vérifier."],
            "missing_data": [], "blockers": [], "error": None,
        } for agent_id in agent_ids],
        "decision": {
            "action": action, "scope": "research_only", "method": "rules",
            "summary": "Poursuivre la recherche après lecture du rapport annuel.",
            "reasons": ["La décision tient compte des limites du dossier."],
            "evidence_ids": ["revenue_2025"], "blockers": [],
            "conditions_to_reconsider": ["Obtenir un rapport annuel complet."],
            "proposed_action": None, "llm_status": "not_requested",
        },
        "gates": [{
            "code": "documents_available", "passed": False, "severity": "cap_watch",
            "reason": "Le document complet manque.", "evidence_ids": ["revenue_2025"],
        }],
        "disagreements": [{"agent_id": "documents", "status": "insufficient", "reasons": ["Une synthèse ne remplace pas le document complet."]}],
        "quality": {"coverage_pct": 88, "level": "partial", "note": "Suivi de la qualité des éléments disponibles."},
        "llm": {"requested": False, "model": None, "calls": 0, "successes": 0, "failures": 0},
        "caveats": ["Dossier de test logiciel sans mesure de performance financière."],
    }


def company(symbol="EXAMPLE", score=80, action="watch"):
    return {
        "symbol": symbol, "name": f"Société de test {symbol}", "country": "FR", "sector": "Industrials",
        "status": "ranked", "score": score, "coverage_pct": 90,
        "ranking_bucket": "profitable_growth",
        "phase": {"id": 4, "name": "Capital Return", "reason": "Dividende ordinaire documenté dans la fixture."},
        "financial_date": "2025-12-31", "retrieved_at": "2026-10-05T12:00:00Z",
        "source_url": "https://example.org/annual", "financial_currency": "EUR",
        "metrics": {"revenue_cagr": 0.1}, "research": research(action),
    }


class MultiagentReportingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.summary = {"mode": "provided", "generated_at": "2026-10-06T12:00:00Z", "top_n": 10, "universe_total": 4}

    def report(self, results, summary=None):
        paths = write_reports(results, self.summary if summary is None else summary, self.directory)
        return paths, Path(paths["html"]).read_text(encoding="utf-8")

    def test_research_decision_precedes_and_does_not_replace_financial_ranking(self):
        results = [company("WATCH", 95, "watch"), company("STUDY", 70, "shortlist"),
                   company("EXCLUDED", 90, "avoid"), company("ABSTAIN", 85, "abstain")]
        paths, document = self.report(results)
        self.assertLess(document.index('id="research-title"'), document.index('id="ranking"'))
        self.assertLess(document.index('id="decision-1"'), document.index("Analyse financière déterministe"))
        for label in ("À étudier en priorité", "À surveiller", "Écartée selon les critères", "Aucune décision"):
            self.assertIn(label, document)
        ranking = document.split('id="ranking"', 1)[1].split("</table>", 1)[0]
        self.assertLess(ranking.index(">WATCH</a>"), ranking.index(">EXCLUDED</a>"))
        self.assertLess(ranking.index(">EXCLUDED</a>"), ranking.index(">ABSTAIN</a>"))
        self.assertLess(ranking.index(">ABSTAIN</a>"), ranking.index(">STUDY</a>"))
        self.assertIn("aucun ordre de bourse", document.lower())
        payload = json.loads(Path(paths["json"]).read_text(encoding="utf-8"))
        self.assertEqual([item["score"] for item in payload["results"]], [95, 90, 85, 70])

    def test_synthetic_and_provided_data_are_not_misrepresented_as_verified_market_data(self):
        item = company()
        item["research"]["data_kind"] = "synthetic"
        _, document = self.report([item])
        self.assertIn("DÉMONSTRATION SYNTHÉTIQUE", document)
        self.assertIn("aucun résultat de marché", document)
        self.assertNotIn("univers limité à Apple", document)
        self.assertIn("7 par règles", document)
        self.assertIn("0 via Ollama", document)
        self.assertNotIn("IA locale exécutée via Ollama", document)
        item["source_url"] = "https://example.invalid/fiction"
        item["research"]["evidence"]["revenue_2025"]["source_url"] = "https://example.invalid/fiction"
        _, document = self.report([item])
        self.assertIn("Référence fictive de démonstration", document)
        self.assertNotIn('href="https://example.invalid/', document)
        item["research"]["data_kind"] = "provided"
        _, document = self.report([item])
        self.assertNotIn("DÉMONSTRATION SYNTHÉTIQUE", document)
        self.assertIn("ne garantit ni vérification ni actualité", document)
        self.assertIn("La qualité et la couverture décrivent les données", document)
        self.assertIn("ne mesurent pas une probabilité de gain", document)
        self.assertIn("les avis ne forment pas un vote", document)

    def test_actual_completed_analyst_records_determine_ollama_counts(self):
        item = company()
        dossier = item["research"]
        dossier.update(backend_requested="ollama", execution_mode="mixed")
        dossier["llm"] = {"requested": True, "model": "test-local", "calls": 4, "successes": 3, "failures": 1}
        for agent in dossier["agents"][:2]:
            agent["method"] = "ollama"
        dossier["agents"][2].update(method="ollama", execution_status="failed", error="Réponse JSON invalide.")
        dossier["agents"][3].update(method="none", execution_status="skipped")
        dossier["decision"].update(method="ollama_constrained", llm_status="completed")
        paths, document = self.report([item])
        self.assertEqual(document.count("IA locale exécutée via Ollama"), 2)
        self.assertIn("2 via Ollama", document)
        self.assertIn("3 par règles", document)
        self.assertIn("Réponse JSON invalide.", document)
        self.assertIn("Analyse non exécutée", document)
        with Path(paths["csv"]).open(encoding="utf-8-sig", newline="") as handle:
            row = next(csv.DictReader(handle))
        self.assertEqual(row["analyst_ollama_completed"], "2")
        self.assertEqual(row["llm_successes"], "3")  # May include the separate decider call.

    def test_ollama_failure_does_not_become_a_successful_ai_analysis(self):
        item = company()
        dossier = item["research"]
        dossier.update(backend_requested="ollama", execution_mode="ollama_failed")
        dossier["llm"] = {"requested": True, "model": "absent", "calls": 1, "successes": 0, "failures": 1}
        dossier["decision"].update(method="rules_after_ai_failure", llm_status="failed")
        dossier["agents"][0].update(method="ollama", execution_status="failed", error="Modèle introuvable.")
        _, document = self.report([item])
        self.assertIn("Décideur déterministe après échec de l’IA", document)
        self.assertIn("0 via Ollama", document)
        self.assertIn("Modèle introuvable.", document)
        self.assertNotIn("IA locale exécutée via Ollama", document)

    def test_missing_reports_and_sources_remain_visibly_missing(self):
        item = company()
        item["research"] = {
            "data_kind": "provided", "agents": [], "evidence": {},
            "decision": {"action": "abstain", "scope": "research_only", "evidence_ids": ["UNKNOWN"]},
        }
        _, document = self.report([item])
        self.assertEqual(document.count("Rapport absent — aucune exécution attestée."), 7)
        self.assertIn("0 / 7 rôles attendus", document)
        self.assertIn("UNKNOWN — référence absente", document)
        self.assertIn("Aucun élément de preuve fourni", document)
        self.assertIn("Mode d’exécution non précisé", document)
        self.assertNotIn('href="#evidence-', document)

    def test_blockers_disagreements_and_evidence_keep_their_provenance(self):
        item = company()
        item["research"]["decision"]["blockers"] = ["Prix non daté."]
        item["research"]["decision"]["proposed_action"] = "shortlist"
        _, document = self.report([item])
        self.assertIn("Prix non daté.", document)
        self.assertIn("Une synthèse ne remplace pas le document complet.", document)
        self.assertIn("Obtenir un rapport annuel complet.", document)
        self.assertIn("Limite à la surveillance", document)
        self.assertIn("Hypothèses à vérifier", document)
        self.assertIn("Proposition initiale du modèle", document)
        self.assertIn('href="#evidence-1-1"', document)
        self.assertIn('id="evidence-1-1"', document)
        self.assertIn("Publication : 2026-03-15", document)
        self.assertIn("Récupération : 2026-10-05T12:00:00Z", document)
        self.assertIn('href="https://example.org/annual?year=2025&amp;lang=fr"', document)
        self.assertIn("Unité : EUR", document)

    def test_nested_untrusted_content_and_evidence_ids_cannot_inject_html_or_links(self):
        attack = '<img src=x onerror="alert(1)">'
        item = company()
        dossier = item["research"]
        dossier["as_of"] = attack
        dossier["decision"].update(summary=attack, proposed_action=attack, reasons=[attack],
                                   blockers=[attack], conditions_to_reconsider=[attack], evidence_ids=[attack])
        dossier["quality"]["note"] = attack
        dossier["llm"]["model"] = attack
        dossier["caveats"] = [attack]
        dossier["gates"][0].update(code=attack, reason=attack, evidence_ids=[attack])
        dossier["disagreements"] = [{"agent_id": attack, "status": attack, "reasons": [attack]}]
        dossier["agents"][0].update(agent_id=attack, role=attack, reasons=[attack], hypotheses=[attack],
                                     missing_data=[attack], blockers=[attack], error=attack, evidence_ids=[attack])
        dossier["evidence"] = {attack: {"path": attack, "value": attack, "period": attack,
                                        "unit": attack, "published_at": attack, "retrieved_at": attack,
                                        "kind": attack, "source_url": "javascript:alert(1)"}}
        _, document = self.report([item])
        self.assertNotIn("<img", document)
        self.assertNotIn('href="javascript:', document)
        self.assertEqual(document.count("<script>"), 1)
        self.assertIn("&lt;img src=x onerror=&quot;alert(1)&quot;&gt;", document)
        self.assertIn('href="#evidence-1-1"', document)
        self.assertIn("Lien HTTPS indisponible", document)

    def test_new_csv_cells_are_formula_safe_and_full_research_survives_json_export(self):
        item = company()
        item["research"]["decision"]["summary"] = " \t=HYPERLINK(\"bad\")"
        item["research"]["llm"]["model"] = "+payload"
        item["research"]["quality"]["coverage_pct"] = math.nan
        item["research"]["evidence"]["revenue_2025"]["value"] = [math.inf, -math.inf]
        original = copy.deepcopy(item)
        paths, first = self.report([item])
        original_bytes = {key: Path(path).read_bytes() for key, path in paths.items()}
        with Path(paths["csv"]).open(encoding="utf-8-sig", newline="") as handle:
            row = next(csv.DictReader(handle))
        self.assertTrue(row["decision_summary"].startswith("'"))
        self.assertTrue(row["llm_model"].startswith("'"))
        self.assertEqual(row["research_coverage_pct"], "")
        dossier = json.loads(row["research_json"], parse_constant=lambda value: self.fail(value))
        self.assertIsNone(dossier["quality"]["coverage_pct"])
        self.assertEqual(dossier["evidence"]["revenue_2025"]["value"], [None, None])
        payload = json.loads(Path(paths["json"]).read_text(encoding="utf-8"))
        self.assertEqual(payload["results"][0]["research"], dossier)
        _, second = self.report([item])
        self.assertEqual(first, second)
        self.assertEqual(original_bytes, {key: Path(path).read_bytes() for key, path in paths.items()})
        self.assertEqual(item["research"]["decision"], original["research"]["decision"])
        self.assertTrue(math.isnan(item["research"]["quality"]["coverage_pct"]))

    def test_unknown_scope_does_not_render_a_research_shortlist(self):
        item = company(action="shortlist")
        item["research"]["decision"]["scope"] = "trade"
        _, document = self.report([item])
        self.assertIn("Décision indisponible : action ou portée de recherche non conforme.", document)
        self.assertIn('<span class="badge neutral">Décision indisponible</span>', document)
        alert = render_alert([item], self.summary)
        self.assertNotIn("EXAMPLE —", alert)
        self.assertIn("À étudier en priorité : 0", alert)

    def test_alert_uses_research_decisions_instead_of_high_scores_and_stays_bounded(self):
        results = [company("EXCLUDED", 99, "avoid"), company("ABSTAIN", 98, "abstain"),
                   company("WATCH", 70, "watch"), company("STUDY", 50, "shortlist")]
        results[0]["research"]["data_kind"] = "synthetic"
        alert = render_alert(results, self.summary)
        self.assertIn("DÉMONSTRATION SYNTHÉTIQUE", alert)
        self.assertNotIn("EXCLUDED —", alert)
        self.assertNotIn("ABSTAIN —", alert)
        self.assertLess(alert.index("STUDY —"), alert.index("WATCH —"))
        self.assertIn("2025-12-31", alert)
        self.assertIn("Score heuristique ≠ probabilité de gain", alert)
        long_results = [company(str(index)) for index in range(30)]
        for item in long_results:
            item["research"]["decision"]["summary"] = "x" * 10000
        self.assertLessEqual(len(render_alert(long_results, dict(self.summary, top_n=30))), 3500)

    def test_mixed_legacy_results_do_not_acquire_invented_analyst_reports(self):
        old = company("LEGACY", 90)
        del old["research"]
        paths, document = self.report([old, company("NEW", 70)])
        self.assertIn("1 fiche(s) sans rapport des analystes", document)
        self.assertEqual(document.count('class="analyst-card"'), 7)
        with Path(paths["csv"]).open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(rows[0]["symbol"], "LEGACY")
        self.assertEqual(rows[0]["research_action"], "")
        self.assertEqual(rows[0]["research_json"], "")


if __name__ == "__main__":
    unittest.main()
