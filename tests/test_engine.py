"""Tests of economically meaningful boundaries, with synthetic fixtures only."""

import copy
import json
import unittest
from datetime import date

from stockbot.engine import analyse_company, classify_phase, validate_config


AS_OF = date(2026, 10, 6)


def company_fixture():
    annual = []
    for year, revenue, profit, shares in (
        (2025, 180.0, 40.0, 100.0),
        (2024, 140.0, 28.0, 101.0),
        (2023, 110.0, 20.0, 102.0),
        (2022, 90.0, 15.0, 103.0),
        (2021, 75.0, 11.0, 104.0),
    ):
        annual.append({
            "date": f"{year}-12-31", "filing_date": f"{year + 1}-03-01", "currency": "USD",
            "revenue": revenue, "gross_profit": revenue * (0.50 + (year - 2021) * 0.01),
            "operating_income": profit, "net_income": profit * 0.75,
            "operating_cash_flow": profit * 1.1, "capex": 4.0,
            "free_cash_flow": profit * 1.1 - 4.0,
            "dividends_paid": 0.0, "dividends_are_common": False,
            "shares_end": shares, "shares_diluted": shares + 1.0,
            "total_debt": 15.0, "cash": 25.0, "equity": 130.0,
            "tax_expense": profit * 0.25, "income_before_tax": profit,
            "interest_expense": 2.0,
        })
    return {
        "symbol": "SYNTH", "name": "Synthetic test company", "country": "United States",
        "exchange": "TEST", "sector": "Industrials", "industry": "Industrial Machinery",
        "isin": None, "quote_currency": "USD", "financial_currency": "USD",
        "source_url": "https://example.invalid/synthetic-fixture", "retrieved_at": "2026-10-06T10:00:00Z",
        "provider_updated_at": "2026-10-05", "data_warnings": [], "annual": annual,
        "valuation": {"trailing_pe": 18.0, "forward_pe": 16.0, "price_sales": 4.0, "price_book": 3.0, "ev_ebitda": 11.0},
    }


class PhaseTests(unittest.TestCase):
    def setUp(self):
        self.company = company_fixture()

    def test_startup_no_revenue_precedes_dividend(self):
        for row in self.company["annual"][:2]:
            row["revenue"] = 0.0
        self.company["annual"][0].update(dividends_paid=1.0, dividends_are_common=True)
        self.assertEqual(classify_phase(self.company)["id"], 1)

    def test_decline_precedes_common_dividend_and_profit(self):
        for row, value in zip(self.company["annual"][:3], (100.0, 120.0, 140.0)):
            row["revenue"] = value
        self.company["annual"][0].update(dividends_paid=1.0, dividends_are_common=True)
        self.assertEqual(classify_phase(self.company)["id"], 5)

    def test_one_declining_year_is_not_decline(self):
        for row, value in zip(self.company["annual"][:3], (140.0, 180.0, 120.0)):
            row["revenue"] = value
        self.assertEqual(classify_phase(self.company)["id"], 4)

    def test_common_dividend_precedes_loss(self):
        self.company["annual"][0].update(dividends_paid=0.01, dividends_are_common=True, operating_income=-10.0)
        self.assertEqual(classify_phase(self.company)["id"], 4)

    def test_global_dividend_is_not_proof_of_common_dividend(self):
        self.company["annual"][0].update(dividends_paid=1.0, dividends_are_common=False)
        phase = classify_phase(self.company)
        self.assertIsNone(phase["id"])
        self.assertEqual(phase["confidence"], "proxy")
        self.assertIn("Dividende ordinaire à confirmer", phase["reason"])

    def test_dated_common_payment_proves_phase4_despite_ambiguous_total(self):
        self.company["annual"][0].update(
            dividends_paid=1.0, dividends_are_common=False,
            common_dividend_paid=True, common_dividend_source="https://example.invalid/dividends",
        )
        phase = classify_phase(self.company)
        self.assertEqual(phase["id"], 4)
        self.assertEqual(phase["confidence"], "documented")
        self.assertEqual(phase["evidence_source"], "https://example.invalid/dividends")

    def test_dated_common_payment_needs_no_aggregate_total(self):
        self.company["annual"][0].update(dividends_paid=None, common_dividend_paid=True)
        self.assertEqual(classify_phase(self.company)["id"], 4)

    def test_unknown_dividend_is_not_zero(self):
        self.company["annual"][0]["dividends_paid"] = None
        self.assertIsNone(classify_phase(self.company)["id"])

    def test_zero_profit_is_explicitly_unknown(self):
        self.company["annual"][0]["operating_income"] = 0.0
        self.assertIsNone(classify_phase(self.company)["id"])
        self.assertIn("nul", classify_phase(self.company)["reason"])

    def test_narrowing_loss_and_equal_loss_differ(self):
        self.company["annual"][0]["operating_income"] = -5.0
        self.company["annual"][1]["operating_income"] = -10.0
        self.assertEqual(classify_phase(self.company)["id"], 2)
        self.company["annual"][1]["operating_income"] = -5.0
        self.assertEqual(classify_phase(self.company)["id"], 1)

    def test_profit_to_loss_is_startup(self):
        self.company["annual"][0]["operating_income"] = -5.0
        self.assertEqual(classify_phase(self.company)["id"], 1)

    def test_current_unknown_profit_does_not_create_profitability(self):
        self.company["annual"][0]["operating_income"] = None
        self.assertIsNone(classify_phase(self.company)["id"])

    def test_missing_prior_profit_follows_explicit_public_rule_with_warning(self):
        self.company["annual"][0]["operating_income"] = -5.0
        self.company["annual"][1]["operating_income"] = None
        phase = classify_phase(self.company)
        self.assertEqual(phase["id"], 1)
        self.assertEqual(phase["confidence"], "incomplete")

    def test_actual_period_end_shares_win_over_diluted_shares(self):
        self.company["annual"][0].update(shares_end=105.0, shares_diluted=95.0)
        self.assertEqual(classify_phase(self.company)["id"], 3)
        self.company["annual"][0].update(shares_end=100.0, shares_diluted=110.0)
        self.assertEqual(classify_phase(self.company)["id"], 4)

    def test_missing_period_end_shares_are_not_filled_from_diluted(self):
        self.company["annual"][0].update(shares_end=None, shares_diluted=50.0)
        phase = classify_phase(self.company)
        self.assertEqual(phase["id"], 3)
        self.assertEqual(phase["confidence"], "incomplete")
        self.assertTrue(phase["warnings"])

    def test_software_uses_operating_cash_flow_not_fcf_or_net_income(self):
        self.company["industry"] = "Software - Application"
        self.company["annual"][0].update(operating_cash_flow=-5.0, free_cash_flow=5.0, net_income=5.0)
        self.company["annual"][1]["operating_cash_flow"] = -10.0
        phase = classify_phase(self.company)
        self.assertEqual(phase["profit_metric"], "operating_cash_flow")
        self.assertEqual(phase["id"], 2)

    def test_bank_uses_net_income(self):
        self.company["industry"] = "Banks - Regional"
        self.company["annual"][0].update(net_income=-5.0, operating_income=20.0, operating_cash_flow=20.0)
        self.company["annual"][1]["net_income"] = -10.0
        phase = classify_phase(self.company)
        self.assertEqual(phase["profit_metric"], "net_income")
        self.assertEqual(phase["id"], 2)

    def test_missing_years_do_not_create_two_consecutive_declines(self):
        self.company["annual"][0]["revenue"] = 80.0
        self.company["annual"] = [self.company["annual"][0], self.company["annual"][2], self.company["annual"][4]]
        self.assertIsNone(classify_phase(self.company)["id"])

    def test_second_missing_year_prevents_decline_claim(self):
        self.company["annual"][0]["revenue"] = 100.0
        self.company["annual"] = [self.company["annual"][0], self.company["annual"][1], self.company["annual"][3]]
        self.assertIsNone(classify_phase(self.company)["id"])

    def test_missing_old_revenue_does_not_block_rising_recent_revenue(self):
        self.company["annual"][2]["revenue"] = None
        self.assertEqual(classify_phase(self.company)["id"], 4)


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.company = company_fixture()

    def analyse(self, config=None):
        return analyse_company(self.company, config or {}, AS_OF)

    def test_complete_company_has_a_bounded_score_and_json_safe_output(self):
        result = self.analyse()
        self.assertEqual(result["status"], "ranked")
        self.assertEqual(result["coverage_pct"], 100.0)
        self.assertGreater(result["score"], 0)
        self.assertLessEqual(result["score"], 100)
        self.assertEqual(result["ranking_bucket"], "profitable_growth")
        json.dumps(result, allow_nan=False)

    def test_input_is_not_mutated(self):
        snapshot = copy.deepcopy(self.company)
        self.analyse()
        self.assertEqual(snapshot, self.company)

    def test_unknowns_receive_no_points_or_favourable_pass(self):
        full = self.analyse()
        self.company["valuation"]["forward_pe"] = None
        result = self.analyse()
        check = next(c for c in result["checks"] if c["label"].startswith("P/E prévisionnel"))
        self.assertIsNone(check["passed"])
        self.assertEqual(check["points"], 0)
        self.assertLess(result["coverage_pct"], full["coverage_pct"])
        self.assertLess(result["score"], full["score"])
        self.assertLessEqual(result["score"], result["coverage_pct"])

    def test_missing_taxes_do_not_invent_a_roic(self):
        self.company["annual"][0]["tax_expense"] = None
        self.assertIsNone(self.analyse()["metrics"]["roic_proxy"])

    def test_prior_invested_capital_is_required_for_roic(self):
        self.company["annual"][1]["equity"] = None
        self.assertIsNone(self.analyse()["metrics"]["roic_proxy"])

    def test_negative_pe_is_not_a_cheap_stock_signal(self):
        self.company["valuation"]["trailing_pe"] = -3.0
        result = self.analyse()
        check = next(c for c in result["checks"] if c["label"].startswith("P/E historique"))
        self.assertEqual(check["points"], 0)
        self.assertIsNone(check["passed"])

    def test_missing_valuation_and_balance_data_abstains(self):
        self.company["valuation"] = {}
        for row in self.company["annual"]:
            row.update(cash=None, total_debt=None, interest_expense=None, equity=None, shares_diluted=None)
        result = self.analyse()
        self.assertEqual(result["status"], "insufficient_data")
        self.assertIsNone(result["score"])
        self.assertLess(result["coverage_pct"], 75)

    def test_valuation_is_required_despite_high_total_coverage(self):
        self.company["valuation"] = {}
        result = self.analyse()
        self.assertEqual(result["coverage_pct"], 85)
        self.assertEqual(result["status"], "insufficient_data")
        self.assertIsNone(result["score"])
        self.assertTrue(any("Aucun critère de valorisation" in risk for risk in result["risks"]))

    def test_unusable_negative_multiples_also_block_ranking(self):
        self.company["valuation"].update(trailing_pe=-1, forward_pe=0, ev_ebitda=-2)
        result = self.analyse()
        self.assertEqual(result["coverage_pct"], 85)
        self.assertEqual(result["status"], "insufficient_data")

    def test_one_usable_valuation_check_is_sufficient(self):
        self.company["valuation"] = {"forward_pe": 16}
        self.assertEqual(self.analyse()["status"], "ranked")

    def test_old_provider_snapshot_is_stale_despite_fresh_retrieval(self):
        self.company.update(provider_updated_at="2026-09-01", retrieved_at="2026-10-06T12:00:00Z")
        result = self.analyse()
        self.assertEqual(result["coverage_pct"], 100)
        self.assertEqual(result["status"], "stale_data")
        self.assertEqual(result["snapshot_age_days"], 35)
        self.assertIsNone(result["score"])

    def test_provider_snapshot_age_limit_is_configurable(self):
        self.company["provider_updated_at"] = "2026-09-01"
        result = self.analyse({"scoring": {"max_snapshot_age_days": 40}})
        self.assertEqual(result["status"], "ranked")

    def test_provider_snapshot_at_exact_age_limit_is_accepted(self):
        self.company["provider_updated_at"] = "2026-09-22"
        self.assertEqual(self.analyse()["status"], "ranked")

    def test_future_provider_snapshot_is_rejected(self):
        self.company["provider_updated_at"] = "2026-10-07"
        result = self.analyse()
        self.assertEqual(result["status"], "insufficient_data")
        self.assertTrue(any("snapshot fournisseur est dans le futur" in risk for risk in result["risks"]))

    def test_missing_provider_snapshot_lowers_confidence_not_coverage(self):
        self.company["provider_updated_at"] = None
        result = self.analyse()
        self.assertEqual(result["status"], "ranked")
        self.assertEqual(result["coverage_pct"], 100)
        self.assertEqual(result["confidence"], "medium")
        self.assertIsNone(result["snapshot_age_days"])
        self.assertTrue(any("date de récupération ne la remplace pas" in risk for risk in result["risks"]))

    def test_fully_missing_data_never_gets_a_good_score(self):
        result = analyse_company({"symbol": "EMPTY", "annual": []}, {}, AS_OF)
        self.assertEqual(result["status"], "insufficient_data")
        self.assertIsNone(result["score"])
        self.assertEqual(result["coverage_pct"], 0)

    def test_unknown_common_dividend_abstains_even_with_complete_quant_data(self):
        self.company["annual"][0].update(dividends_paid=10.0, dividends_are_common=False)
        result = self.analyse()
        self.assertEqual(result["coverage_pct"], 100)
        self.assertEqual(result["status"], "insufficient_data")
        self.assertIsNone(result["score"])

    def test_stale_financial_year_is_not_ranked(self):
        self.company["annual"] = self.company["annual"][1:]
        result = self.analyse()
        self.assertEqual(result["status"], "stale_data")
        self.assertIsNone(result["score"])
        self.assertEqual(result["confidence"], "low")

    def test_future_publication_is_rejected(self):
        self.company["annual"][0]["filing_date"] = "2026-10-07"
        result = self.analyse()
        self.assertEqual(result["status"], "insufficient_data")
        self.assertTrue(any("après la date" in r for r in result["risks"]))

    def test_financial_specialists_are_not_scored(self):
        for industry in ("Banks - Diversified", "Insurance - Life", "REIT - Residential", "Mortgage REITs"):
            with self.subTest(industry=industry):
                self.company["industry"] = industry
                result = self.analyse()
                self.assertEqual(result["status"], "specialist_review")
                self.assertIsNone(result["score"])
                self.assertEqual(result["checks"], [])
                self.assertIsNone(result["metrics"]["roic_proxy"])

    def test_missing_financial_industry_does_not_enable_generic_score(self):
        self.company.update(sector="Financial Services", industry=None)
        self.assertEqual(self.analyse()["status"], "specialist_review")

    def test_gap_cagr_uses_actual_years_not_observation_count(self):
        self.company["annual"] = [self.company["annual"][0], self.company["annual"][2], self.company["annual"][4]]
        result = self.analyse()
        years = (date(2025, 12, 31) - date(2021, 12, 31)).days / 365.25
        expected = (180.0 / 75.0) ** (1 / years) - 1
        self.assertAlmostEqual(result["metrics"]["revenue_cagr"], expected, places=7)
        self.assertEqual(result["status"], "insufficient_data")

    def test_negative_profit_transition_can_be_ranked_without_positive_fcf(self):
        self.company["industry"] = "Software - Infrastructure"
        for row, ocf, fcf in zip(self.company["annual"], (-5.0, -20.0, -30.0, -35.0, -40.0), (-9.0, -24.0, -34.0, -39.0, -44.0)):
            row.update(operating_cash_flow=ocf, free_cash_flow=fcf, net_income=ocf, operating_income=ocf)
        result = self.analyse()
        self.assertEqual(result["phase"]["id"], 2)
        self.assertEqual(result["status"], "ranked")
        self.assertEqual(result["ranking_bucket"], "transition")
        self.assertEqual(result["coverage_pct"], 100)
        self.assertTrue(any(c["passed"] for c in result["checks"] if c["category"] == "quality"))

    def test_missing_shares_end_lower_phase_confidence_without_guessing_buybacks(self):
        for row in self.company["annual"]:
            row["shares_end"] = None
        result = self.analyse()
        self.assertEqual(result["phase"]["id"], 3)
        self.assertEqual(result["phase"]["confidence"], "incomplete")
        self.assertEqual(result["confidence"], "medium")

    def test_anomalous_financials_abstain(self):
        self.company["annual"][0]["gross_profit"] = 200.0
        result = self.analyse()
        self.assertEqual(result["status"], "insufficient_data")
        self.assertIsNone(result["score"])

    def test_nonfinite_numbers_do_not_escape_to_json(self):
        self.company["annual"][0]["revenue"] = float("nan")
        self.company["valuation"]["forward_pe"] = float("inf")
        result = self.analyse()
        self.assertEqual(result["status"], "insufficient_data")
        json.dumps(result, allow_nan=False)

    def test_currency_change_blocks_ranking_and_growth_comparison(self):
        self.company["annual"][0]["currency"] = "EUR"
        result = self.analyse()
        self.assertEqual(result["status"], "insufficient_data")
        self.assertIsNone(result["metrics"]["revenue_cagr"])

    def test_weights_are_configurable_and_normalized(self):
        result = self.analyse({"scoring": {"weights": {"valuation": 30}}})
        self.assertAlmostEqual(sum(c["max_points"] for c in result["checks"]), 100, places=4)
        self.assertAlmostEqual(sum(c["max_points"] for c in result["checks"] if c["category"] == "valuation"), 30 / 115 * 100, places=4)

    def test_invalid_weights_are_not_silently_accepted(self):
        with self.assertRaises(ValueError):
            self.analyse({"scoring": {"weights": {"growth": -10}}})

    def test_two_years_can_classify_but_cannot_rank(self):
        self.company["annual"] = self.company["annual"][:2]
        result = self.analyse()
        self.assertEqual(result["phase"]["id"], 4)
        self.assertEqual(result["status"], "insufficient_data")


class ConfigurationTests(unittest.TestCase):
    def test_default_configuration_is_valid(self):
        self.assertIsNone(validate_config({}))

    def test_invalid_weight_in_an_unused_phase_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_config({"scoring": {"phase_weights": {"2": {"growth": -1}}}})

    def test_phase_with_no_positive_weight_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_config({"scoring": {"phase_weights": {"5": {
                "growth": 0, "quality": 0, "balance_sheet": 0, "dilution": 0, "valuation": 0,
            }}}})

    def test_invalid_limits_are_rejected_before_any_company(self):
        for key, value in (
            ("min_coverage_pct", 101), ("min_coverage_pct", float("nan")),
            ("max_financial_age_days", -1), ("max_snapshot_age_days", -1),
            ("max_snapshot_age_days", True), ("min_annual_periods", 2.5),
        ):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                validate_config({"scoring": {key: value}})

    def test_unknown_phase_and_wrong_container_types_are_rejected(self):
        for config in (
            {"scoring": {"phase_weights": {"6": {"growth": 10}}}},
            {"scoring": {"weights": []}},
            {"scoring": {"phase_weights": {"3": []}}},
            {"scoring": []},
        ):
            with self.subTest(config=config), self.assertRaises(ValueError):
                validate_config(config)

    def test_config_validation_does_not_mutate_input(self):
        config = {"scoring": {"weights": {"growth": 30}, "phase_weights": {"2": {"quality": 10}}, "max_snapshot_age_days": 7}}
        original = copy.deepcopy(config)
        validate_config(config)
        self.assertEqual(config, original)


if __name__ == "__main__":
    unittest.main()
