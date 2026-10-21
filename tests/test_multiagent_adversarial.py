"""Independent public-contract tests for the research agents and decision gate.

All financial records and document excerpts here are synthetic.  The fake
local model never uses a network or fetches a document URL.  Tests deliberately
ask an optimistic model to shortlist unsafe dossiers: data gates must win.
"""

import copy
import json
import unittest
from datetime import timedelta

from test_engine import AS_OF, company_fixture
from stockbot.engine import analyse_company
from stockbot.multiagent import analyse_research, expire_cached_research


AGENT_IDS = {
    "data_quality", "fundamentals", "growth", "valuation", "risk",
    "documents", "challenger",
}
ACTIONS = {"shortlist", "watch", "avoid", "abstain"}


def documented_company():
    company = company_fixture()
    company["is_synthetic"] = True
    company["documents"] = [{
        "title": "Rapport synthétique 2025 — test technique",
        "published_at": "2026-03-01",
        "source_url": "https://example.invalid/synthetic-annual-report-2025",
        "is_synthetic": True,
        "text": (
            "Extrait fictif, sans valeur d'investissement. Les revenus annuels "
            "du cas de test sont 180, 140 et 110 unités en 2025, 2024 et 2023. "
            "En 2025 : résultat opérationnel 40, flux opérationnel 44, "
            "investissements 4, dette 15, trésorerie 25. Ces chiffres ne "
            "démontrent aucun avantage concurrentiel ni rendement futur."
        ),
    }]
    return company


class OptimisticLocalModel:
    """Schema-valid optimistic replies; selected failures are injected by role."""

    def __init__(self, *, fail_role=None, invalid_reference_role=None,
                 malformed_role=None, decision_action="shortlist",
                 foreign_reference=None, status_overrides=None):
        self.fail_role = fail_role
        self.invalid_reference_role = invalid_reference_role
        self.malformed_role = malformed_role
        self.decision_action = decision_action
        self.foreign_reference = foreign_reference
        self.status_overrides = status_overrides or {}
        self.calls = []
        self.bundles = []

    def chat(self, *, role, prompt, evidence_bundle, schema):
        self.calls.append(role)
        self.bundles.append(copy.deepcopy(evidence_bundle))
        if role == self.fail_role:
            raise TimeoutError("Synthetic local-model failure")
        evidence = evidence_bundle["evidence"]
        baseline = evidence_bundle.get("baseline") or {}
        references = [item for item in baseline.get("evidence_ids", []) if item in evidence]
        if not references:
            references = list(evidence)[:2]
        references = list(dict.fromkeys(references))[:5]
        if role == self.invalid_reference_role:
            references = [self.foreign_reference or "nonexistent:dossier:fact"]
        if role == "decision":
            response = {
                "action": self.decision_action,
                "evidence_ids": references,
                "reasons": ["Proposition optimiste synthétique pour éprouver les garde-fous."],
                "conditions_to_reconsider": [],
            }
        else:
            response = {
                "status": self.status_overrides.get(role, "support"),
                "evidence_ids": references,
                "reasons": ["Avis synthétique volontairement favorable, limité au test."],
                "hypotheses": [],
                "missing_data": [],
            }
        if role == self.malformed_role:
            response["execute_trade"] = True  # Not part of either allowed response schema.
        return response


class MultiagentSafetyTests(unittest.TestCase):
    def analyse(self, company=None, *, backend="rules", client=None, config=None, as_of=AS_OF):
        settings = copy.deepcopy(config or {})
        settings.setdefault("agents", {})["backend"] = backend
        return analyse_research(
            documented_company() if company is None else company,
            settings, as_of, llm_client=client,
        )

    def assert_research_only(self, result):
        decision = result["research"]["decision"]
        self.assertEqual(decision["scope"], "research_only")
        self.assertIn(decision["action"], ACTIONS)
        return decision

    def assert_abstains(self, result):
        self.assertEqual(self.assert_research_only(result)["action"], "abstain")

    def assert_valid_references(self, research):
        evidence = research["evidence"]
        self.assertIsInstance(evidence, dict)
        for report in research["agents"] + research["gates"] + [research["decision"]]:
            references = report["evidence_ids"]
            self.assertIsInstance(references, list)
            for reference in references:
                self.assertIn(reference, evidence)

    def test_rules_contract_has_seven_distinct_roles_and_resolvable_evidence(self):
        result = self.analyse()
        research = result["research"]
        reports = research["agents"]
        self.assertEqual(len(reports), len(AGENT_IDS))
        self.assertEqual({report["agent_id"] for report in reports}, AGENT_IDS)
        self.assertEqual(research["as_of"], AS_OF.isoformat())
        self.assert_research_only(result)
        for report in reports:
            self.assertIn(report["status"], {"support", "caution", "insufficient"})
            self.assertIn(report["execution_status"], {"completed", "failed", "skipped"})
            self.assertIn(report["method"], {"rules", "ollama", "none"})
            for key in ("evidence_ids", "reasons", "hypotheses", "missing_data", "blockers"):
                self.assertIsInstance(report[key], list)
        required_evidence_fields = {
            "path", "value", "period", "unit", "source_url", "published_at",
            "retrieved_at", "kind",
        }
        for record in research["evidence"].values():
            self.assertTrue(required_evidence_fields <= set(record))
        self.assert_valid_references(research)
        json.dumps(result, allow_nan=False)

    def test_dossier_and_configuration_are_not_mutated(self):
        company = documented_company()
        config = {"agents": {"backend": "ollama"}, "scoring": {"min_coverage_pct": 75}}
        original_company, original_config = copy.deepcopy(company), copy.deepcopy(config)
        analyse_research(company, config, AS_OF, llm_client=OptimisticLocalModel())
        self.assertEqual(company, original_company)
        self.assertEqual(config, original_config)

    def test_three_annual_periods_are_sufficient_for_the_history_gate(self):
        company = documented_company()
        company["annual"] = company["annual"][:3]
        result = self.analyse(company)
        self.assertEqual(result["status"], "ranked")
        self.assertIn(self.assert_research_only(result)["action"], {"shortlist", "watch"})

    def test_valid_numeric_configuration_strings_are_normalized(self):
        baseline = self.analyse()
        for config in (
            {"agents": {"min_shortlist_score": "75"}},
            {"agents": {"min_shortlist_coverage_pct": "85"}},
            {"scoring": {"max_snapshot_age_days": "14"}},
        ):
            with self.subTest(config=config):
                result = self.analyse(config=config)
                self.assertEqual(result["score"], baseline["score"])
                self.assertEqual(
                    self.assert_research_only(result)["action"],
                    self.assert_research_only(baseline)["action"],
                )

    def test_two_periods_cannot_be_enabled_by_lowering_engine_configuration(self):
        company = documented_company()
        company["annual"] = company["annual"][:2]
        config = {"scoring": {"min_annual_periods": 2}}
        # A rejected configuration is also safe; an eligible decision is not.
        try:
            result = self.analyse(company, config=config, backend="ollama", client=OptimisticLocalModel())
        except ValueError:
            return
        self.assert_abstains(result)

    def test_duplicate_observations_do_not_count_as_three_valid_exercises(self):
        company = documented_company()
        company["annual"] = [company["annual"][0], company["annual"][1], copy.deepcopy(company["annual"][1])]
        self.assert_abstains(self.analyse(company))

    def test_optimistic_model_cannot_override_engine_ineligibility(self):
        for corruption in ("missing_valuation", "missing_annual", "future_publication", "currency_change", "gross_profit_anomaly"):
            with self.subTest(corruption=corruption):
                company = documented_company()
                if corruption == "missing_valuation":
                    company["valuation"] = {}
                elif corruption == "missing_annual":
                    company["annual"] = []
                elif corruption == "future_publication":
                    company["annual"][0]["filing_date"] = "2026-10-07"
                elif corruption == "currency_change":
                    company["annual"][0]["currency"] = "EUR"
                else:
                    company["annual"][0]["gross_profit"] = 200.0
                result = self.analyse(company, backend="ollama", client=OptimisticLocalModel())
                self.assertNotEqual(result["status"], "ranked")
                self.assert_abstains(result)

    def test_stale_or_future_snapshot_is_not_rejuvenated_by_retrieval(self):
        for snapshot in ("2026-09-01", "2026-10-07"):
            with self.subTest(snapshot=snapshot):
                company = documented_company()
                company.update(provider_updated_at=snapshot, retrieved_at="2026-10-06T12:00:00Z")
                self.assert_abstains(self.analyse(company, backend="ollama", client=OptimisticLocalModel()))

    def test_old_financial_year_abstains_with_a_fresh_provider_snapshot(self):
        company = documented_company()
        company["annual"] = company["annual"][1:]
        company["provider_updated_at"] = AS_OF.isoformat()
        self.assert_abstains(self.analyse(company, backend="ollama", client=OptimisticLocalModel()))

    def test_freshness_is_recomputed_from_dates_when_analysis_date_advances(self):
        company = documented_company()
        company["provider_updated_at"] = (AS_OF - timedelta(days=13)).isoformat()
        earlier = self.analyse(company)
        self.assertEqual(earlier["status"], "ranked")
        later = self.analyse(company, as_of=AS_OF + timedelta(days=6))
        self.assert_abstains(later)
        self.assertEqual(later["research"]["as_of"], (AS_OF + timedelta(days=6)).isoformat())

    def test_financial_specialists_including_unmapped_lenders_abstain(self):
        for sector, industry in (
            ("Financial Services", "Lending"),
            ("Financial Services", "Banks - Regional"),
            ("Financial Services", None),
            ("Financial Services", "Insurance - Life"),
            ("Real Estate", "REIT - Residential"),
        ):
            with self.subTest(industry=industry):
                company = documented_company()
                company.update(sector=sector, industry=industry)
                self.assert_abstains(self.analyse(company, backend="ollama", client=OptimisticLocalModel()))

    def test_unknown_snapshot_caps_even_a_high_score_and_optimistic_model(self):
        company = documented_company()
        company["provider_updated_at"] = None
        company["valuation"] = {"trailing_pe": 18}
        result = self.analyse(company, backend="ollama", client=OptimisticLocalModel())
        self.assertEqual(result["status"], "ranked")
        self.assertGreater(result["score"], 75)
        self.assertNotEqual(self.assert_research_only(result)["action"], "shortlist")

    def test_phase4_negative_fcf_cannot_be_shortlisted_despite_high_score(self):
        company = documented_company()
        company["annual"][0].update(common_dividend_paid=True, free_cash_flow=-1.0, capex=45.0)
        baseline = analyse_company(company, {}, AS_OF)
        self.assertEqual(baseline["phase"]["id"], 4)
        self.assertEqual(baseline["status"], "ranked")
        self.assertGreater(baseline["score"], 75)
        result = self.analyse(company, backend="ollama", client=OptimisticLocalModel())
        self.assertNotEqual(self.assert_research_only(result)["action"], "shortlist")

    def test_missing_documents_are_explicit_and_cannot_support_shortlist(self):
        company = company_fixture()
        result = self.analyse(company)
        report = next(item for item in result["research"]["agents"] if item["agent_id"] == "documents")
        self.assertEqual(report["status"], "insufficient")
        self.assertTrue(report["missing_data"])
        # Generic uncertainty is allowed; the absence must not become support
        # or a fabricated document reference.
        self.assert_valid_references(result["research"])
        self.assertNotEqual(self.assert_research_only(result)["action"], "shortlist")

    def test_invalid_documents_do_not_unlock_shortlist_or_enter_evidence(self):
        marker = "SYNTHETIC_EXCLUDED_DOCUMENT_MARKER"
        variants = (
            {"published_at": "2026-10-07"},
            {"published_at": "2020-01-01"},
            {"published_at": "invalid-date"},
            {"source_url": "http://example.invalid/unverified-document"},
            {"source_url": "javascript:alert(1)"},
        )
        for change in variants:
            with self.subTest(change=change):
                company = documented_company()
                company["documents"][0].update(text=marker, **change)
                result = self.analyse(company, backend="ollama", client=OptimisticLocalModel())
                self.assertNotEqual(self.assert_research_only(result)["action"], "shortlist")
                self.assertNotIn(marker, json.dumps(result["research"]["evidence"], ensure_ascii=False))

    def test_empty_document_text_is_not_a_qualitative_review(self):
        company = documented_company()
        company["documents"][0]["text"] = "   "
        result = self.analyse(company, backend="ollama", client=OptimisticLocalModel())
        self.assertNotEqual(self.assert_research_only(result)["action"], "shortlist")

    def test_document_age_limit_is_applied_from_configuration(self):
        company = documented_company()
        company["documents"][0]["published_at"] = (AS_OF - timedelta(days=31)).isoformat()
        result = self.analyse(
            company, config={"agents": {"max_document_age_days": 30}},
            backend="ollama", client=OptimisticLocalModel(),
        )
        self.assertNotEqual(self.assert_research_only(result)["action"], "shortlist")

    def test_nonfinite_financial_inputs_abstain_and_remain_json_safe(self):
        company = documented_company()
        company["annual"][0]["revenue"] = float("nan")
        result = self.analyse(company)
        self.assert_abstains(result)
        json.dumps(result, allow_nan=False)

    def test_unknown_reference_fails_analyst_and_decision_abstains(self):
        client = OptimisticLocalModel(invalid_reference_role="risk")
        result = self.analyse(backend="ollama", client=client)
        self.assertIn("risk", client.calls)
        report = next(item for item in result["research"]["agents"] if item["agent_id"] == "risk")
        self.assertEqual(report["execution_status"], "failed")
        self.assert_abstains(result)

    def test_document_and_challenger_reservations_cannot_be_outvoted(self):
        for role in ("documents", "challenger"):
            for status in ("caution", "insufficient"):
                with self.subTest(role=role, status=status):
                    client = OptimisticLocalModel(status_overrides={role: status})
                    result = self.analyse(backend="ollama", client=client)
                    report = next(item for item in result["research"]["agents"] if item["agent_id"] == role)
                    self.assertEqual(report["execution_status"], "completed")
                    self.assertEqual(report["status"], status)
                    decision = self.assert_research_only(result)
                    self.assertEqual(decision["proposed_action"], "shortlist")
                    self.assertEqual(decision["action"], "watch")

    def test_reference_from_another_company_cannot_be_reused(self):
        first_company = documented_company()
        first = self.analyse(first_company)
        old_reference = next(iter(first["research"]["evidence"]))
        second_company = documented_company()
        second_company.update(symbol="SYNTH_OTHER", name="Other synthetic company")
        client = OptimisticLocalModel(invalid_reference_role="growth", foreign_reference=old_reference)
        second = self.analyse(second_company, backend="ollama", client=client)
        self.assertNotIn(old_reference, second["research"]["evidence"])
        self.assert_abstains(second)

    def test_each_executed_model_role_failure_cannot_be_outvoted(self):
        baseline_client = OptimisticLocalModel()
        self.analyse(backend="ollama", client=baseline_client)
        called_roles = set(baseline_client.calls)
        self.assertIn("decision", called_roles)
        self.assertGreaterEqual(len(called_roles - {"decision"}), 2)
        for role in sorted(called_roles):
            with self.subTest(role=role):
                client = OptimisticLocalModel(fail_role=role)
                result = self.analyse(backend="ollama", client=client)
                self.assertIn(role, client.calls)
                self.assert_abstains(result)

    def test_malformed_analyst_response_does_not_silently_fall_back_to_success(self):
        result = self.analyse(backend="ollama", client=OptimisticLocalModel(malformed_role="fundamentals"))
        report = next(item for item in result["research"]["agents"] if item["agent_id"] == "fundamentals")
        self.assertEqual(report["execution_status"], "failed")
        self.assert_abstains(result)

    def test_unknown_decision_reference_is_rejected(self):
        client = OptimisticLocalModel(invalid_reference_role="decision")
        result = self.analyse(backend="ollama", client=client)
        self.assertIn("decision", client.calls)
        self.assert_abstains(result)

    def test_model_cannot_propose_a_trade_or_an_unknown_decision_action(self):
        for action in ("buy", "sell", "execute_order", "SHORTLIST"):
            with self.subTest(action=action):
                client = OptimisticLocalModel(decision_action=action)
                result = self.analyse(backend="ollama", client=client)
                self.assertIn("decision", client.calls)
                self.assert_abstains(result)

    def test_valid_local_model_path_uses_provided_evidence_and_stays_research_only(self):
        client = OptimisticLocalModel(decision_action="watch")
        result = self.analyse(backend="ollama", client=client)
        self.assertIn("decision", client.calls)
        self.assertEqual(self.assert_research_only(result)["action"], "watch")
        self.assert_valid_references(result["research"])
        for bundle in client.bundles:
            self.assertEqual(bundle["company"]["symbol"], "SYNTH")
            self.assertEqual(bundle["as_of"], AS_OF.isoformat())
            self.assertTrue(set(bundle["evidence"]) <= set(result["research"]["evidence"]))
        json.dumps(result, allow_nan=False)

    def test_cached_decision_expires_without_mutating_or_redating_the_original(self):
        company = documented_company()
        company["provider_updated_at"] = (AS_OF - timedelta(days=13)).isoformat()
        original = self.analyse(company)
        self.assertEqual(self.assert_research_only(original)["action"], "shortlist")
        original["snapshot_age_days"] = 0  # A cached age is not proof of freshness.
        saved = copy.deepcopy(original)
        report_date = AS_OF + timedelta(days=6)
        expired = expire_cached_research(original, report_date)
        self.assertEqual(original, saved)
        self.assert_abstains(expired)
        self.assertEqual(expired["research"]["decision"]["previous_action"], "shortlist")
        self.assertEqual(expired["research"]["as_of"], AS_OF.isoformat())
        self.assertEqual(expired["research"]["report_as_of"], report_date.isoformat())
        self.assertEqual(expired["snapshot_age_days"], 19)
        self.assertTrue(any(not gate["passed"] and gate["severity"] == "block" for gate in expired["research"]["gates"]))
        json.dumps(expired, allow_nan=False)

    def test_same_day_cached_decision_is_preserved_but_returns_a_deep_copy(self):
        original = self.analyse()
        saved = copy.deepcopy(original)
        same_day = expire_cached_research(original, AS_OF)
        self.assertEqual(same_day, original)
        self.assertEqual(self.assert_research_only(same_day)["action"], "shortlist")
        same_day["research"]["agents"][0]["reasons"].append("Changed only in the returned copy")
        self.assertEqual(original, saved)


if __name__ == "__main__":
    unittest.main()
