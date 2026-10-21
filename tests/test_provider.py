"""Financial-integrity and request-budget tests; fixtures are synthetic."""

import copy
import io
import json
import tempfile
import traceback
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from stockbot.provider import AccessDenied, BudgetExceeded, EODHDProvider, ProviderError, normalise_fundamentals


NOW = datetime(2026, 10, 6, 16, 40, tzinfo=timezone.utc)
COLLECTED = "2026-10-06T16:40:00Z"


def fixture():
    """A fictitious company; amounts are deliberately small, not market data."""
    return {
        "General": {"Name": "Synthetic Example", "Type": "Common Stock", "Exchange": "TEST",
                    "CurrencyCode": "CHF", "CountryName": "Switzerland", "UpdatedAt": "2026-10-05"},
        "Valuation": {"TrailingPE": "12.5", "ForwardPE": None, "PriceSalesTTM": "0", "EnterpriseValueEbitda": "NaN"},
        "Financials": {
            "Income_Statement": {"currency_symbol": "USD", "yearly": {
                "2025-09-30": {"date": "2025-09-30", "filing_date": "2025-11-02", "totalRevenue": "1000", "grossProfit": "600", "operatingIncome": "100", "netIncome": "70", "interestExpense": "0"},
                "2024-09-30": {"date": "2024-09-30", "filing_date": "2024-11-02", "totalRevenue": "800"}}},
            "Balance_Sheet": {"currency_symbol": "USD", "yearly": {
                "2025-09-30": {"date": "2025-09-30", "filing_date": "2025-11-03", "commonStockSharesOutstanding": "10", "shortLongTermDebtTotal": "0", "cashAndEquivalents": "0", "cash": "99", "totalStockholderEquity": "-5"},
                "2024-09-30": {"date": "2024-09-30", "filing_date": "2024-11-03", "commonStockSharesOutstanding": "11"}}},
            "Cash_Flow": {"currency_symbol": "USD", "yearly": {
                "2025-09-30": {"date": "2025-09-30", "filing_date": "2025-11-04", "totalCashFromOperatingActivities": "100", "capitalExpenditures": "-20", "freeCashFlow": "80", "dividendsPaid": "0"},
                "2024-09-30": {"date": "2024-09-30", "filing_date": "2024-11-04", "totalCashFromOperatingActivities": "50", "capitalExpenditures": "10"}}}},
        "outstandingShares": {"annual": {"0": {"dateFormatted": "2025-12-31", "shares": 987654321}}},
    }


def response(payload):
    return io.BytesIO(json.dumps(payload).encode())


def exchange(code, country="USA", iso="US", mic="XNAS"):
    return {"Code": code, "Name": code + " exchange", "Country": country,
            "CountryISO2": iso, "OperatingMIC": mic}


class NormalizationTests(unittest.TestCase):
    def test_numbers_dates_and_unknown_shares(self):
        company = normalise_fundamentals(fixture(), "test.sw", COLLECTED)
        latest = company["annual"][0]
        self.assertEqual(company["symbol"], "TEST.SW")
        self.assertEqual(company["quote_currency"], "CHF")
        self.assertEqual(company["financial_currency"], "USD")
        self.assertEqual(latest["filing_date"], "2025-11-04")
        self.assertEqual(latest["revenue"], 1000)
        self.assertEqual(latest["cash"], 0)
        self.assertEqual(latest["total_debt"], 0)
        self.assertEqual(latest["interest_expense"], 0)
        self.assertEqual(latest["equity"], -5)
        self.assertIsNone(latest["tax_expense"])
        self.assertIsNone(latest["shares_end"])
        self.assertEqual(latest["shares_diluted"], 10)
        self.assertFalse(latest["dividends_are_common"])
        self.assertIsNone(company["valuation"]["ev_ebitda"])
        self.assertNotIn("api_token", company["source_url"])

    def test_fcf_reconciliation_and_missing_zero(self):
        raw = fixture()
        raw["Financials"]["Cash_Flow"]["yearly"]["2025-09-30"]["freeCashFlow"] = "999"
        company = normalise_fundamentals(raw, "TEST.SW", COLLECTED)
        self.assertEqual(company["annual"][0]["free_cash_flow"], 80)
        self.assertEqual(company["annual"][0]["capex"], 20)
        self.assertEqual(company["annual"][1]["free_cash_flow"], 40)
        self.assertTrue(any("incohérent" in note for note in company["data_warnings"]))
        raw["Financials"]["Cash_Flow"]["yearly"]["2025-09-30"] = {"date": "2025-09-30", "capitalExpenditures": 0}
        latest = normalise_fundamentals(raw, "TEST.SW", COLLECTED)["annual"][0]
        self.assertEqual(latest["capex"], 0)
        self.assertIsNone(latest["free_cash_flow"])

    def test_cross_statement_currency_mismatch_is_not_used(self):
        raw = fixture()
        raw["Financials"]["Balance_Sheet"]["yearly"]["2025-09-30"]["currency_symbol"] = "EUR"
        company = normalise_fundamentals(raw, "TEST.SW", COLLECTED)
        latest = company["annual"][0]
        self.assertEqual(latest["revenue"], 1000)
        self.assertIsNone(latest["equity"])
        self.assertIsNone(latest["cash"])
        self.assertIsNone(latest["total_debt"])
        self.assertEqual(latest["shares_diluted"], 10)
        self.assertTrue(any("incompatible" in note for note in company["data_warnings"]))

    def test_historical_currency_change_is_not_a_growth_input(self):
        raw = fixture()
        raw["Financials"]["Income_Statement"]["yearly"]["2024-09-30"]["currency_symbol"] = "EUR"
        old = normalise_fundamentals(raw, "TEST.SW", COLLECTED)["annual"][1]
        self.assertEqual(old["currency"], "EUR")
        self.assertIsNone(old["revenue"])

    def test_different_fiscal_dates_do_not_join_by_year(self):
        raw = fixture()
        cashflows = raw["Financials"]["Cash_Flow"]["yearly"]
        row = cashflows.pop("2025-09-30")
        row["date"] = "2025-09-27"
        cashflows["2025-09-27"] = row
        company = normalise_fundamentals(raw, "TEST.SW", COLLECTED)
        rows = {row["date"]: row for row in company["annual"]}
        self.assertIsNone(rows["2025-09-30"]["operating_cash_flow"])
        self.assertEqual(rows["2025-09-27"]["operating_cash_flow"], 100)
        self.assertIsNone(rows["2025-09-27"]["revenue"])

    def test_future_publication_and_unknown_publication_are_not_fabricated(self):
        raw = fixture()
        raw["Financials"]["Cash_Flow"]["yearly"]["2025-09-30"]["filing_date"] = "2026-12-31"
        company = normalise_fundamentals(raw, "TEST.SW", COLLECTED)
        self.assertIsNone(company["annual"][0]["free_cash_flow"])
        raw["Financials"]["Income_Statement"]["yearly"]["2025-09-30"]["filing_date"] = None
        self.assertIsNone(normalise_fundamentals(raw, "TEST.SW", COLLECTED)["annual"][0]["filing_date"])

    def test_only_latest_six_periods_and_input_not_mutated(self):
        raw = fixture()
        for year in range(2015, 2024):
            raw["Financials"]["Income_Statement"]["yearly"][f"{year}-09-30"] = {"totalRevenue": 1}
        before = copy.deepcopy(raw)
        company = normalise_fundamentals(raw, "TEST.SW", COLLECTED)
        self.assertEqual(len(company["annual"]), 6)
        self.assertEqual(company["annual"][-1]["date"], "2020-09-30")
        self.assertEqual(raw, before)


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.clock = patch("stockbot.provider._utc_now", return_value=NOW)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.sleep = patch("stockbot.provider.time.sleep")
        self.sleep.start()
        self.addCleanup(self.sleep.stop)

    def provider(self, **kwargs):
        options = {"token": "unit-test-key", "cache_path": Path(self.temp.name) / "cache.sqlite",
                   "min_request_interval": 0, "max_retries": 0}
        options.update(kwargs)
        provider = EODHDProvider(**options)
        self.addCleanup(provider.close)
        return provider

    def test_cache_preserves_original_timestamp_and_costs_nothing(self):
        provider = self.provider()
        with patch("stockbot.provider.urlopen", return_value=response(fixture())) as fetch:
            first = provider.fundamentals("TEST.SW")
            with patch("stockbot.provider._utc_now", return_value=NOW + timedelta(hours=4)):
                second = provider.fundamentals("TEST.SW")
            self.assertEqual(fetch.call_count, 1)
        self.assertEqual(provider.units_used, 10)
        self.assertEqual(first["retrieved_at"], second["retrieved_at"])
        self.assertEqual(second["retrieved_at"], COLLECTED)
        rows = provider._db.execute("SELECT account_hash,cache_key,payload FROM eodhd_cache").fetchall()
        self.assertNotIn("unit-test-key", repr(rows))

    def test_expired_cache_does_not_bypass_budget(self):
        provider = self.provider(max_units_per_run=10)
        with patch("stockbot.provider.urlopen", return_value=response(fixture())) as fetch:
            provider.fundamentals("TEST.SW")
            with patch("stockbot.provider._utc_now", return_value=NOW + timedelta(hours=21)):
                with self.assertRaises(BudgetExceeded):
                    provider.fundamentals("TEST.SW")
            self.assertEqual(fetch.call_count, 1)

    def test_daily_budget_persists_across_instances_and_resets_at_utc_day(self):
        first = self.provider(max_units_per_day=10)
        second = self.provider(max_units_per_day=10)
        with patch("stockbot.provider.urlopen", side_effect=lambda *a, **k: response(fixture())) as fetch:
            first.fundamentals("TEST.SW")
            with self.assertRaises(BudgetExceeded):
                second.fundamentals("OTHER.SW")
            with patch("stockbot.provider._utc_now", return_value=NOW + timedelta(days=1)):
                second.fundamentals("OTHER.SW")
            self.assertEqual(fetch.call_count, 2)

    def test_errors_and_tracebacks_do_not_reveal_token(self):
        provider = self.provider(token="sensitive-test-secret", max_retries=2)
        error = HTTPError("https://eodhd.com/?api_token=sensitive-test-secret", 403,
                          "sensitive-test-secret", {}, io.BytesIO(b"sensitive-test-secret"))
        with patch("stockbot.provider.urlopen", side_effect=error) as fetch:
            try:
                provider.fundamentals("TEST.SW")
            except ProviderError as caught:
                rendered = "".join(traceback.format_exception(type(caught), caught, caught.__traceback__))
            else:
                self.fail("Expected a sanitized provider error")
            self.assertEqual(fetch.call_count, 1)
        self.assertNotIn("sensitive-test-secret", rendered)
        self.assertIn("403", rendered)

    def test_retry_attempts_consume_budget(self):
        provider = self.provider(max_units_per_run=20, max_retries=2)
        error = HTTPError("private", 429, "rate limited", {"Retry-After": "0"}, None)
        with patch("stockbot.provider.urlopen", side_effect=[error, response(fixture())]) as fetch:
            provider.fundamentals("TEST.SW")
            self.assertEqual(fetch.call_count, 2)
        self.assertEqual(provider.units_used, 20)

    def test_demo_discovery_is_explicit_and_never_calls_worldwide_api(self):
        provider = self.provider(token="demo")
        with patch("stockbot.provider.urlopen") as fetch:
            with self.assertWarnsRegex(UserWarning, "aucune couverture mondiale"):
                found = provider.discover()
            with self.assertRaises(ProviderError):
                provider.fundamentals("NESN.SW")
            fetch.assert_not_called()
        self.assertEqual({r["symbol"] for r in found}, {"AAPL.US", "AMZN.US", "TSLA.US"})
        self.assertFalse(provider.discovery_complete)

    def test_discovery_filters_pseudo_markets_and_keeps_common_stock_only(self):
        provider = self.provider()
        exchanges = [exchange("US"), exchange("CC", "Unknown", "", None), exchange("INDX")]
        rows = [{"Code": "ABC", "Type": "Common Stock", "Exchange": "NASDAQ", "Isin": "TEST123"},
                {"Code": "ETF", "Type": "ETF"}, {"Code": "PREF", "Type": "Preferred Stock"}]
        with patch("stockbot.provider.urlopen", side_effect=[response(exchanges), response(rows)]) as fetch:
            found = provider.discover()
            self.assertEqual(fetch.call_count, 2)
        self.assertEqual(found[0]["symbol"], "ABC.US")
        self.assertEqual(found[0]["exchange"], "NASDAQ")
        self.assertEqual(found[0]["isin"], "TEST123")
        self.assertEqual(len(found), 1)
        self.assertTrue(provider.discovery_complete)
        self.assertEqual(provider.units_used, 2)

    def test_partial_discovery_is_flagged(self):
        provider = self.provider()
        exchanges = [exchange("US"), exchange("SW", "Switzerland", "CH", "XSWX")]
        failure = HTTPError("private", 503, "unavailable", {}, None)
        rows = [{"Code": "ABC", "Type": "Common Stock"}]
        with patch("stockbot.provider.urlopen", side_effect=[response(exchanges), failure, response(rows)]):
            found = provider.discover()
        self.assertFalse(provider.discovery_complete)
        self.assertTrue(provider.discovery_warnings)
        self.assertEqual(found[0]["symbol"], "ABC.US")

    def test_discovery_stops_on_auth_denial_without_scanning_other_markets(self):
        provider = self.provider()
        exchanges = [exchange("US"), exchange("SW", "Switzerland", "CH", "XSWX")]
        failure = HTTPError("private", 403, "denied", {}, None)
        with patch("stockbot.provider.urlopen", side_effect=[response(exchanges), failure]) as fetch:
            with self.assertRaises(AccessDenied):
                provider.discover()
            self.assertEqual(fetch.call_count, 2)
        self.assertFalse(provider.discovery_complete)

    def test_dividends_entitlement_denial_disables_only_optional_enrichment(self):
        raw = fixture()
        raw["Financials"]["Cash_Flow"]["yearly"]["2025-09-30"]["dividendsPaid"] = "5"
        provider = self.provider()
        failure = HTTPError("private", 403, "denied", {}, None)
        with patch("stockbot.provider.urlopen", side_effect=[response(raw), failure, response(raw)]) as fetch:
            first = provider.fundamentals("TEST.SW")
            second = provider.fundamentals("OTHER.SW")
            self.assertEqual(fetch.call_count, 3)
        self.assertIsNone(first["annual"][0]["common_dividend_paid"])
        self.assertEqual(second["annual"][0]["revenue"], 1000)
        self.assertEqual(provider.units_used, 21)

    def test_dividend_confirmation_uses_payment_date_not_ex_date(self):
        raw = fixture()
        raw["Financials"]["Cash_Flow"]["yearly"]["2025-09-30"]["dividendsPaid"] = "5"
        provider = self.provider()
        rows = [{"date": "2024-09-20", "paymentDate": "2024-10-15", "value": 0.10}]
        with patch("stockbot.provider.urlopen", side_effect=[response(raw), response(rows)]):
            company = provider.fundamentals("TEST.SW")
        latest = company["annual"][0]
        self.assertTrue(latest["common_dividend_paid"])
        self.assertEqual(latest["common_dividend_payment_date"], "2024-10-15")
        self.assertEqual(latest["dividends_paid"], 5)
        self.assertFalse(latest["dividends_are_common"])
        self.assertNotIn("api_token", latest["common_dividend_source"])
        self.assertEqual(provider.units_used, 11)

    def test_ex_date_alone_or_payment_outside_period_cannot_confirm_dividend(self):
        raw = fixture()
        raw["Financials"]["Cash_Flow"]["yearly"]["2025-09-30"]["dividendsPaid"] = "5"
        provider = self.provider()
        rows = [{"date": "2025-08-01", "paymentDate": None, "value": 0.1},
                {"date": "2025-09-01", "paymentDate": "2025-10-15", "value": 0.1},
                {"date": "2025-07-01", "paymentDate": "2025-07-15", "value": 0}]
        with patch("stockbot.provider.urlopen", side_effect=[response(raw), response(rows)]):
            company = provider.fundamentals("TEST.SW")
        self.assertIsNone(company["annual"][0]["common_dividend_paid"])

    def test_optional_dividend_request_budget_failure_keeps_main_analysis(self):
        raw = fixture()
        raw["Financials"]["Cash_Flow"]["yearly"]["2025-09-30"]["dividendsPaid"] = "5"
        provider = self.provider(max_units_per_run=10)
        with patch("stockbot.provider.urlopen", return_value=response(raw)) as fetch:
            company = provider.fundamentals("TEST.SW")
            self.assertEqual(fetch.call_count, 1)
        self.assertEqual(company["annual"][0]["revenue"], 1000)
        self.assertIsNone(company["annual"][0]["common_dividend_paid"])
        self.assertTrue(any("budget API atteint" in note for note in company["data_warnings"]))


if __name__ == "__main__":
    unittest.main()
