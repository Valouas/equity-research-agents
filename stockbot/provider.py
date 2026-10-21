"""EODHD connector and conservative normalization, using the standard library.

The endpoint returns today's version of historical statements, not a guaranteed
point-in-time archive. Its dates and unverified share definitions must not be
used to claim a bias-free historical backtest.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import time
import warnings
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


class ProviderError(RuntimeError):
    """Public error whose message never contains credentials or server bodies."""


class BudgetExceeded(ProviderError):
    """A local budget or the provider's daily quota has been reached."""


class AccessDenied(ProviderError):
    """Authentication or entitlement failure: a caller should stop its scan."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


DEMO_SYMBOLS = ("AAPL.US", "AMZN.US", "TSLA.US")
_PSEUDO_EXCHANGES = {"CC", "FOREX", "INDX", "MONEY", "GBOND", "EUFUND"}
_STATEMENTS = ("Income_Statement", "Balance_Sheet", "Cash_Flow")
_SYMBOL = re.compile(r"[A-Z0-9^][A-Z0-9.^_&=+-]*\.[A-Z0-9_-]+\Z")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_timestamp(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("A UTC offset is required.")
    return result.astimezone(timezone.utc)


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    result = value.strip()
    return result if result and result.lower() not in {"null", "none", "unknown", "n/a"} else None


def _currency(value: Any) -> str | None:
    result = _text(value)
    if result == "GBp":
        return "GBX"
    return result.upper() if result and re.fullmatch(r"[A-Za-z]{3}", result) else None


def _date(value: Any) -> str | None:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return None
    try:
        date.fromisoformat(value)
    except ValueError:
        return None
    return value


def _mapping(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _valid_symbol(symbol: str) -> str:
    if not isinstance(symbol, str):
        raise ValueError("Le symbole doit suivre le format CODE.BOURSE.")
    result = symbol.strip().upper()
    if len(result) > 80 or not _SYMBOL.fullmatch(result):
        raise ValueError("Le symbole doit suivre le format CODE.BOURSE.")
    return result


def normalise_fundamentals(raw: dict, symbol: str, retrieved_at: str) -> dict:
    """Normalize at most six annual periods, joined by exact fiscal dates.

    Monetary values of a statement whose currency is unknown or incompatible
    with the current reporting currency are set to None. No currency conversion
    or calendar-year matching is guessed. Missing values remain missing.
    """
    symbol = _valid_symbol(symbol)
    try:
        collected = _parse_timestamp(retrieved_at)
    except (ValueError, TypeError, AttributeError):
        raise ValueError("La date de collecte doit être un horodatage ISO avec fuseau.") from None
    if not isinstance(raw, dict):
        raise ProviderError("Le fournisseur n'a pas renvoyé un objet de fondamentaux.")
    general = _mapping(raw.get("General"))
    financials = _mapping(raw.get("Financials"))
    valuation = _mapping(raw.get("Valuation"))
    notes: list[str] = []

    def note(message: str) -> None:
        if message not in notes:
            notes.append(message)

    reports: dict[str, dict[str, dict]] = {}
    currencies: dict[str, str | None] = {}
    today = collected.date().isoformat()
    for name in _STATEMENTS:
        section = _mapping(financials.get(name))
        currencies[name] = _currency(section.get("currency_symbol"))
        yearly = _mapping(section.get("yearly"))
        reports[name] = {}
        for key, value in yearly.items():
            if not isinstance(value, dict):
                continue
            # Prefer the report's own date; never join on just the year.
            period = _date(value.get("date")) if value.get("date") is not None else _date(key)
            if period is None:
                note(f"{name}: une période sans date fiscale valide a été écartée.")
                continue
            filing = _date(value.get("filing_date"))
            if period > today or (filing is not None and filing > today):
                note(f"{name} {period}: données datées après la collecte, écartées.")
                continue
            if filing is not None and filing < period:
                note(f"{name} {period}: date de dépôt antérieure à la clôture, ignorée.")
                filing = None
            copy = dict(value)
            copy["date"] = period
            copy["filing_date"] = filing
            copy["currency_symbol"] = _currency(value.get("currency_symbol")) or currencies[name]
            if period in reports[name]:
                note(f"{name} {period}: doublon de période; dépôt le plus récent retenu.")
                if (reports[name][period].get("filing_date") or "") >= (filing or ""):
                    continue
            reports[name][period] = copy

    # Header currency describes the current reporting basis; rows can reveal a
    # historical change of currency and must not silently enter a growth rate.
    financial_currency = currencies["Income_Statement"]
    if financial_currency is None:
        for name in _STATEMENTS:
            for period in sorted(reports[name], reverse=True):
                candidate = reports[name][period].get("currency_symbol")
                if candidate:
                    financial_currency = candidate
                    break
            if financial_currency:
                break
    if financial_currency is None:
        note("Devise des comptes inconnue: les montants financiers ne sont pas exploitables.")

    annual: list[dict] = []
    periods = sorted(set().union(*(set(reports[name]) for name in _STATEMENTS)), reverse=True)[:6]
    for period in periods:
        original = {name: reports[name].get(period, {}) for name in _STATEMENTS}
        safe: dict[str, dict] = {}
        for name, row in original.items():
            row_currency = row.get("currency_symbol")
            if not row:
                note(f"{period}: {name} absent; aucune autre date n'a été substituée.")
                safe[name] = {}
            elif not row_currency or row_currency != financial_currency:
                note(f"{period}: devise {name} ({row_currency or 'inconnue'}) incompatible avec {financial_currency or 'inconnue'}; montants neutralisés.")
                safe[name] = {}
            else:
                safe[name] = row

        income, balance, cashflow = (safe[name] for name in _STATEMENTS)
        known_filings = [row.get("filing_date") for row in original.values() if row]
        # A merged period is not fully dated when one of its statements has no
        # filing date. Choosing the latest known date would hide that uncertainty.
        filing_date = max(known_filings) if known_filings and all(known_filings) else None
        if filing_date is None:
            note(f"{period}: date de publication complète non vérifiée; inutilisable pour un backtest daté.")
        ocf = _number(cashflow.get("totalCashFromOperatingActivities"))
        capex = _number(cashflow.get("capitalExpenditures"))
        capex = abs(capex) if capex is not None else None
        fcf = _number(cashflow.get("freeCashFlow"))
        computed_fcf = ocf - capex if ocf is not None and capex is not None else None
        if computed_fcf is not None:
            tolerance = max(1.0, 0.02 * max(abs(ocf), capex, abs(computed_fcf)))
            if fcf is not None and abs(fcf - computed_fcf) > tolerance:
                note(f"{period}: free cash-flow fournisseur incohérent; recalculé avec flux opérationnel moins dépenses d'investissement.")
                fcf = computed_fcf
            elif fcf is None:
                fcf = computed_fcf

        dividends = _number(cashflow.get("dividendsPaid"))
        # This field is described as weighted-average diluted shares in EODHD's
        # official glossary, despite its misleading location/name.
        diluted = _number(original["Balance_Sheet"].get("commonStockSharesOutstanding"))
        if diluted is not None and diluted <= 0:
            note(f"{period}: nombre moyen dilué d'actions invalide, ignoré.")
            diluted = None
        debt = _number(balance.get("shortLongTermDebtTotal"))
        if debt is not None and debt < 0:
            note(f"{period}: dette totale négative invalide, ignorée.")
            debt = None
        cash = _number(balance.get("cashAndEquivalents"))
        if cash is None:
            cash = _number(balance.get("cash"))
        if cash is not None and cash < 0:
            note(f"{period}: trésorerie négative non interprétée comme un actif, ignorée.")
            cash = None

        annual.append({
            "date": period,
            "filing_date": filing_date,
            "currency": original["Income_Statement"].get("currency_symbol") or financial_currency,
            "revenue": _number(income.get("totalRevenue")),
            "gross_profit": _number(income.get("grossProfit")),
            "operating_income": _number(income.get("operatingIncome")),
            "net_income": _number(income.get("netIncome")),
            "operating_cash_flow": ocf,
            "capex": capex,
            "free_cash_flow": fcf,
            "dividends_paid": abs(dividends) if dividends is not None else None,
            "dividends_are_common": False,
            "common_dividend_paid": None,
            "common_dividend_source": None,
            "shares_end": None,
            "shares_diluted": diluted,
            "total_debt": debt,
            "cash": cash,
            "equity": _number(balance.get("totalStockholderEquity")),
            "tax_expense": _number(income.get("incomeTaxExpense")),
            "income_before_tax": _number(income.get("incomeBeforeTax")),
            "interest_expense": _number(income.get("interestExpense")),
        })

    if not annual:
        note("Aucun compte annuel exploitable n'a été renvoyé.")
    note("Actions en fin de période non vérifiées; la moyenne diluée ne les remplace pas.")
    note("Les dividendes payés ne sont pas garantis comme réservés aux actions ordinaires.")
    note("Historique potentiellement révisé: la collecte actuelle ne garantit pas les données disponibles à une date passée.")
    return {
        "symbol": symbol,
        "name": _text(general.get("Name")) or symbol,
        "country": _text(general.get("CountryName")),
        "exchange": _text(general.get("Exchange")) or symbol.rsplit(".", 1)[1],
        "sector": _text(general.get("Sector")),
        "industry": _text(general.get("Industry")),
        "isin": _text(general.get("ISIN")),
        "quote_currency": _currency(general.get("CurrencyCode")),
        "financial_currency": financial_currency,
        "source_url": "https://eodhd.com/api/v1.1/fundamentals/" + quote(symbol, safe="."),
        "retrieved_at": retrieved_at,
        "provider_updated_at": _text(general.get("UpdatedAt")),
        "data_warnings": notes,
        "valuation": {
            "trailing_pe": _number(valuation.get("TrailingPE")),
            "forward_pe": _number(valuation.get("ForwardPE")),
            "price_sales": _number(valuation.get("PriceSalesTTM")),
            "price_book": _number(valuation.get("PriceBookMRQ")),
            "ev_ebitda": _number(valuation.get("EnterpriseValueEbitda")),
        },
        "annual": annual,
    }


class EODHDProvider:
    """Synchronous EODHD client with persistent TTL cache and call-unit budget.

    Every network attempt is reserved against the budget, including retries.
    This conservative local estimate can exceed EODHD's billed usage on errors.
    Cached responses cost zero units. A run means the lifetime of this instance.
    """

    def __init__(self, token: str, cache_path: str | Path = "data/cache.sqlite",
                 max_units_per_run: int = 1000, min_request_interval: float = 0.3,
                 timeout: float = 25, *, max_units_per_day: int | None = 100_000,
                 max_retries: int = 2):
        if not isinstance(token, str) or not token.strip():
            raise ValueError("Une clé EODHD ou le mode demo est nécessaire.")
        if isinstance(max_units_per_run, bool) or not isinstance(max_units_per_run, int) or max_units_per_run < 0:
            raise ValueError("Le budget doit être un entier positif ou nul.")
        if max_units_per_day is not None and (isinstance(max_units_per_day, bool) or not isinstance(max_units_per_day, int) or max_units_per_day < 0):
            raise ValueError("Le budget journalier doit être un entier positif ou nul.")
        if not 0 <= min_request_interval <= 60 or not 0 < timeout <= 60:
            raise ValueError("Intervalle et délai réseau doivent rester entre 0 et 60 secondes.")
        if isinstance(max_retries, bool) or not isinstance(max_retries, int) or not 0 <= max_retries <= 5:
            raise ValueError("Le nombre de nouvelles tentatives doit être compris entre 0 et 5.")
        self._token = token.strip()
        self._scope = hashlib.sha256(self._token.encode()).hexdigest()[:24]
        self.max_units_per_run = max_units_per_run
        self.max_units_per_day = max_units_per_day
        self.min_request_interval = float(min_request_interval)
        self.timeout = float(timeout)
        self.max_retries = max_retries
        self.units_used = 0
        self.discovery_warnings: list[str] = []
        self.discovery_complete = False
        self._dividends_access_denied = False
        self._last_request: float | None = None
        if str(cache_path) != ":memory:":
            Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(cache_path), timeout=30)
        self._db.execute("CREATE TABLE IF NOT EXISTS eodhd_cache (account_hash TEXT NOT NULL, cache_key TEXT NOT NULL, retrieved_at TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY (account_hash, cache_key))")
        self._db.execute("CREATE TABLE IF NOT EXISTS eodhd_usage (account_hash TEXT NOT NULL, date_utc TEXT NOT NULL, units INTEGER NOT NULL, PRIMARY KEY (account_hash, date_utc))")
        self._db.commit()

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> EODHDProvider:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def _reserve(self, units: int) -> None:
        if self.units_used + units > self.max_units_per_run:
            raise BudgetExceeded("Budget d'appels de cette exécution atteint; reprise possible depuis le cache.")
        day = _utc_now().date().isoformat()
        with self._db:
            self._db.execute("BEGIN IMMEDIATE")
            row = self._db.execute("SELECT units FROM eodhd_usage WHERE account_hash=? AND date_utc=?", (self._scope, day)).fetchone()
            previous = row[0] if row else 0
            if self.max_units_per_day is not None and previous + units > self.max_units_per_day:
                raise BudgetExceeded("Budget journalier local EODHD atteint (jour UTC).")
            self._db.execute("INSERT INTO eodhd_usage (account_hash,date_utc,units) VALUES (?,?,?) ON CONFLICT(account_hash,date_utc) DO UPDATE SET units=excluded.units", (self._scope, day, previous + units))
        self.units_used += units

    def _cache_get(self, key: str, ttl_hours: float) -> tuple[Any, str] | None:
        row = self._db.execute("SELECT payload,retrieved_at FROM eodhd_cache WHERE account_hash=? AND cache_key=?", (self._scope, key)).fetchone()
        if row is None or ttl_hours <= 0:
            return None
        try:
            age = (_utc_now() - _parse_timestamp(row[1])).total_seconds()
            if 0 <= age < ttl_hours * 3600:
                return json.loads(row[0]), row[1]
        except (ValueError, TypeError):
            pass
        return None

    def _request_json(self, path: str, parameters: dict, units: int,
                      ttl_hours: float) -> tuple[Any, str]:
        if not math.isfinite(ttl_hours) or ttl_hours < 0:
            raise ValueError("La durée du cache doit être positive ou nulle.")
        public_query = urlencode(sorted(parameters.items()))
        key = path + ("?" + public_query if public_query else "")
        cached = self._cache_get(key, ttl_hours)
        if cached is not None:
            return cached
        query = dict(parameters)
        query["api_token"] = self._token
        url = "https://eodhd.com" + path + "?" + urlencode(query)

        for attempt in range(self.max_retries + 1):
            if self._last_request is not None:
                pause = self.min_request_interval - (time.monotonic() - self._last_request)
                if pause > 0:
                    time.sleep(pause)
            self._reserve(units)
            self._last_request = time.monotonic()
            try:
                request = Request(url, headers={"Accept": "application/json", "User-Agent": "StockResearchBot/1.0"})
                with urlopen(request, timeout=self.timeout) as response:
                    body = response.read(25 * 1024 * 1024 + 1)
                if len(body) > 25 * 1024 * 1024:
                    raise ProviderError("Réponse EODHD trop volumineuse; requête interrompue.")
                payload = json.loads(body)
            except HTTPError as error:
                status = error.code
                # Do not interpolate error, error.url, reason or response body.
                retryable = status == 429 or 500 <= status < 600
                if retryable and attempt < self.max_retries:
                    retry_after = _number(error.headers.get("Retry-After")) if error.headers else None
                    time.sleep(min(30.0, max(0.0, retry_after if retry_after is not None else 2 ** attempt)))
                    continue
                if status == 402:
                    raise BudgetExceeded("Quota EODHD épuisé (HTTP 402).") from None
                if status in (401, 403):
                    raise AccessDenied(f"Accès EODHD refusé (HTTP {status}); vérifier la clé et l'abonnement.", status=status) from None
                raise ProviderError(f"La requête EODHD a échoué (HTTP {status}).") from None
            except (URLError, OSError, TimeoutError):
                if attempt < self.max_retries:
                    time.sleep(min(30.0, float(2 ** attempt)))
                    continue
                raise ProviderError("Connexion EODHD indisponible après les tentatives autorisées.") from None
            except (ValueError, UnicodeError):
                raise ProviderError("EODHD n'a pas renvoyé du JSON valide.") from None
            if not isinstance(payload, (list, dict)) or (isinstance(payload, dict) and any(str(k).lower() in {"error", "errors", "error message"} for k in payload)):
                raise ProviderError("Réponse EODHD inattendue; aucune donnée mise en cache.")
            collected_at = _timestamp(_utc_now())
            with self._db:
                self._db.execute("INSERT INTO eodhd_cache(account_hash,cache_key,retrieved_at,payload) VALUES(?,?,?,?) ON CONFLICT(account_hash,cache_key) DO UPDATE SET retrieved_at=excluded.retrieved_at,payload=excluded.payload", (self._scope, key, collected_at, json.dumps(payload, ensure_ascii=False, allow_nan=False)))
            return payload, collected_at
        raise ProviderError("Les tentatives EODHD sont épuisées.")

    def fundamentals(self, symbol: str, ttl_hours: float = 20) -> dict:
        symbol = _valid_symbol(symbol)
        if self._token == "demo" and symbol not in DEMO_SYMBOLS:
            raise ProviderError("Le mode démo est limité à AAPL.US, AMZN.US et TSLA.US.")
        raw, collected_at = self._request_json("/api/v1.1/fundamentals/" + quote(symbol, safe="."), {"fmt": "json"}, 10, ttl_hours)
        if not isinstance(raw, dict) or not isinstance(raw.get("General"), dict):
            raise ProviderError("Fondamentaux EODHD absents ou incomplets.")
        company = normalise_fundamentals(raw, symbol, collected_at)
        self._confirm_common_dividend(company, raw["General"], ttl_hours)
        return company

    def _confirm_common_dividend(self, company: dict, general: dict,
                                  ttl_hours: float) -> None:
        """Prove existence of a paid common dividend, without summing money.

        The cash-flow total remains ambiguous. The separate boolean uses the
        payment date of this exact common-stock listing, never its ex-date.
        """
        annual = company["annual"]
        if not annual or general.get("Type") != "Common Stock":
            return
        latest = annual[0]
        if latest["dividends_paid"] is None or latest["dividends_paid"] <= 0:
            return
        if self._dividends_access_denied:
            company["data_warnings"].append("Paiement d'un dividende ordinaire non vérifié: accès à cet historique déjà refusé pendant cette exécution.")
            return
        if len(annual) < 2:
            company["data_warnings"].append("Paiement d'un dividende ordinaire non vérifié: début de l'exercice inconnu.")
            return
        start, end = annual[1]["date"], latest["date"]
        duration = (date.fromisoformat(end) - date.fromisoformat(start)).days
        if not 300 <= duration <= 430:
            company["data_warnings"].append("Paiement d'un dividende ordinaire non vérifié: périodes annuelles non consécutives ou atypiques.")
            return
        symbol = company["symbol"]
        source = "/api/div/" + quote(symbol, safe=".")
        try:
            # from/to filter on ex-date. Full history avoids losing a dividend
            # whose ex-date and payment date fall in different fiscal years.
            rows, retrieved_at = self._request_json(source, {"fmt": "json"}, 1, ttl_hours)
            if not isinstance(rows, list):
                raise ProviderError("Historique des dividendes non exploitable.")
        except BudgetExceeded:
            company["data_warnings"].append("Paiement d'un dividende ordinaire non vérifié: budget API atteint.")
            return
        except AccessDenied as error:
            if error.status == 401:
                raise
            # Fundamentals-only plans may exclude dividends. Do not spend one
            # failed enrichment call per company after the first denial.
            self._dividends_access_denied = True
            company["data_warnings"].append("Paiement d'un dividende ordinaire non vérifié: accès à l'historique refusé; enrichissement désactivé pour cette exécution.")
            return
        except ProviderError:
            company["data_warnings"].append("Paiement d'un dividende ordinaire non vérifié: historique indisponible avec cet accès.")
            return
        for row in rows:
            if not isinstance(row, dict):
                continue
            payment = _date(row.get("paymentDate"))
            amount = _number(row.get("unadjustedValue"))
            if amount is None:
                amount = _number(row.get("value"))
            if payment and start < payment <= end and amount is not None and amount > 0:
                latest["common_dividend_paid"] = True
                latest["common_dividend_source"] = "https://eodhd.com" + source
                latest["common_dividend_payment_date"] = payment
                latest["common_dividend_retrieved_at"] = retrieved_at
                return
        company["data_warnings"].append("Paiement d'un dividende ordinaire non vérifié: aucun montant positif avec date de paiement dans l'exercice; les dates ex-dividende ne sont pas substituées.")

    @staticmethod
    def _physical_exchange(row: dict) -> bool:
        code = (_text(row.get("Code")) or "").upper()
        name = (_text(row.get("Name")) or "").lower()
        return bool(code and code not in _PSEUDO_EXCHANGES and "virtual" not in name
                    and _text(row.get("Country"))
                    and _text(row.get("OperatingMIC"))
                    and _text(row.get("CountryISO2")))

    def discover(self, exchanges: list[str] | None = None) -> list[dict]:
        """Enumerate active common-stock listings; not historical membership."""
        self.discovery_complete = False
        self.discovery_warnings = []
        requested = None
        if exchanges is not None:
            if not isinstance(exchanges, list) or any(not isinstance(x, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", x.strip()) for x in exchanges):
                raise ValueError("Les codes de bourse doivent être fournis dans une liste.")
            requested = list(dict.fromkeys(x.strip().upper() for x in exchanges))
            if any(code in _PSEUDO_EXCHANGES for code in requested):
                raise ValueError("Cette sélection contient un marché virtuel sans actions ordinaires.")
        if self._token == "demo":
            message = "Mode démo: recherche limitée à AAPL.US, AMZN.US et TSLA.US; aucune couverture mondiale."
            self.discovery_warnings.append(message)
            warnings.warn(message, UserWarning, stacklevel=2)
            if requested is not None and "US" not in requested:
                return []
            return [{"symbol": symbol, "name": name, "exchange": "NASDAQ", "country": "USA", "isin": None}
                    for symbol, name in zip(DEMO_SYMBOLS, ("Apple Inc.", "Amazon.com Inc.", "Tesla Inc."))]
        if requested == []:
            self.discovery_complete = True
            return []
        exchange_rows, _ = self._request_json("/api/exchanges-list/", {}, 1, 168)
        if not isinstance(exchange_rows, list):
            raise ProviderError("La liste des bourses EODHD est invalide.")
        physical = {str(row["Code"]).upper(): row for row in exchange_rows if isinstance(row, dict) and self._physical_exchange(row)}
        if requested is not None and any(code not in physical for code in requested):
            raise ProviderError("Une bourse demandée n'est pas un marché d'actions vérifié dans la liste EODHD.")
        selected = requested if requested is not None else sorted(physical)
        if not selected:
            raise ProviderError("Aucun marché d'actions vérifié dans la liste EODHD.")
        found: dict[str, dict] = {}
        complete = True
        for code in selected:
            try:
                rows, _ = self._request_json("/api/exchange-symbol-list/" + quote(code, safe=""), {"fmt": "json", "type": "common_stock", "delisted": 0}, 1, 168)
            except BudgetExceeded:
                complete = False
                self.discovery_warnings.append("Découverte partielle: budget API atteint avant la récupération de toutes les bourses.")
                if not found:
                    raise
                break
            except AccessDenied:
                self.discovery_warnings.append("Découverte interrompue: clé ou droits d'accès refusés; conserver l'univers antérieur.")
                raise
            except ProviderError:
                complete = False
                self.discovery_warnings.append(f"Découverte partielle: bourse {code} indisponible; conserver ses anciens titres.")
                continue
            if not isinstance(rows, list):
                complete = False
                self.discovery_warnings.append(f"Découverte partielle: liste de symboles invalide pour {code}; conserver ses anciens titres.")
                continue
            for row in rows:
                if not isinstance(row, dict) or row.get("Type") != "Common Stock":
                    continue
                ticker = _text(row.get("Code"))
                if not ticker:
                    continue
                try:
                    symbol = _valid_symbol(ticker + "." + code)
                except ValueError:
                    continue
                found[symbol] = {"symbol": symbol, "name": _text(row.get("Name")) or ticker,
                                 "exchange": _text(row.get("Exchange")) or code,
                                 "country": _text(row.get("Country")) or _text(physical[code].get("Country")),
                                 "isin": _text(row.get("Isin")) or _text(row.get("ISIN"))}
        self.discovery_complete = complete
        return [found[symbol] for symbol in sorted(found)]
