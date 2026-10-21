"""Bounded normalized JSON input and explicitly fictitious, date-relative examples."""
from __future__ import annotations

import copy
import json
import re
from datetime import date, timedelta
from pathlib import Path


MAX_INPUT_BYTES = 20 * 1024 * 1024


def _no_constant(value):
    raise ValueError("Le JSON ne peut pas contenir NaN ou Infinity.")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Une clé JSON est dupliquée.")
        result[key] = value
    return result


def load_companies(path: Path) -> list[dict]:
    """Read data, never code or remote URLs. Dates are not silently refreshed."""
    with path.open("rb") as handle:
        raw = handle.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError("Fichier d'entrée trop volumineux (limite vingt mégaoctets).")
    try:
        data = json.loads(raw.decode("utf-8-sig"), parse_constant=_no_constant, object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        raise ValueError("Le fichier d'entrée doit être un JSON UTF-8 valide.") from None
    if isinstance(data, list):
        companies = data
        synthetic = False
    elif isinstance(data, dict):
        companies = data.get("companies")
        synthetic = data.get("data_kind") == "synthetic"
        if data.get("schema_version", "0.2") != "0.2":
            raise ValueError("Version de format d'entrée non prise en charge.")
    else:
        raise ValueError("Le fichier doit contenir une liste companies.")
    if not isinstance(companies, list) or not 1 <= len(companies) <= 10000:
        raise ValueError("Le fichier doit contenir entre une et dix mille sociétés.")
    seen = set()
    for company in companies:
        if not isinstance(company, dict):
            raise ValueError("Chaque société doit être un objet JSON.")
        symbol = company.get("symbol")
        if not isinstance(symbol, str) or not re.fullmatch(r"[A-Za-z0-9^_.:-]{1,80}", symbol):
            raise ValueError("Chaque société nécessite un symbole simple et non vide.")
        if symbol.upper() in seen:
            raise ValueError("Un symbole est dupliqué dans le fichier d'entrée.")
        seen.add(symbol.upper())
        rows = company.get("annual")
        if not isinstance(rows, list) or len(rows) > 30 or any(not isinstance(r, dict) for r in rows):
            raise ValueError("annual doit être une liste d'au plus trente exercices.")
        if not isinstance(company.get("valuation", {}), dict):
            raise ValueError("valuation doit être un objet JSON.")
        if company.get("documents") is not None:
            if not isinstance(company["documents"], list) or len(company["documents"]) > 10:
                raise ValueError("documents doit contenir au plus dix extraits.")
            if any(not isinstance(d, dict) or not isinstance(d.get("text", ""), str) for d in company["documents"]):
                raise ValueError("Les documents doivent contenir des extraits textuels.")
        if synthetic:
            company["is_synthetic"] = True
    return companies


def sample_companies(as_of: date) -> list[dict]:
    """A complete four-outcome example; every figure and document is fictitious."""
    latest_year = as_of.year - (1 if as_of >= date(as_of.year, 3, 1) else 2)
    annual = []
    for offset, revenue, profit, shares in (
        (0, 180.0, 40.0, 100.0), (1, 140.0, 28.0, 101.0),
        (2, 110.0, 20.0, 102.0), (3, 90.0, 15.0, 103.0), (4, 75.0, 11.0, 104.0),
    ):
        year = latest_year - offset
        annual.append({
            "date": f"{year}-12-31", "filing_date": f"{year + 1}-03-01", "currency": "USD",
            "revenue": revenue, "gross_profit": revenue * (0.54 - offset * 0.01),
            "operating_income": profit, "net_income": profit * 0.75,
            "operating_cash_flow": profit * 1.1, "capex": 4.0, "free_cash_flow": profit * 1.1 - 4,
            "dividends_paid": 0.0, "dividends_are_common": False,
            "shares_end": shares, "shares_diluted": shares + 1,
            "total_debt": 15.0, "cash": 25.0, "equity": 130.0,
            "tax_expense": profit * 0.25, "income_before_tax": profit, "interest_expense": 2.0,
        })
    alpha = {
        "symbol": "ALPHA.SYN", "name": "Alpha Industrie — société fictive", "country": "Fictif",
        "exchange": "SYNTHETIC", "sector": "Industrials", "industry": "Industrial Machinery",
        "financial_currency": "USD", "quote_currency": "USD", "is_synthetic": True,
        "source_url": "https://example.invalid/alpha/comptes-fictifs",
        "retrieved_at": as_of.isoformat() + "T00:00:00Z",
        "provider_updated_at": (as_of - timedelta(days=1)).isoformat(),
        "annual": annual, "data_warnings": ["Tous les chiffres et les extraits de cette société sont synthétiques."],
        "valuation": {"trailing_pe": 18.0, "forward_pe": 16.0, "price_sales": 4.0,
                      "price_book": 3.0, "ev_ebitda": 11.0},
        "documents": [{"title": "Extrait fictif pour tester les agents",
                       "published_at": annual[0]["filing_date"],
                       "source_url": "https://example.invalid/alpha/rapport-fictif",
                       "text": "DOCUMENT SYNTHÉTIQUE. La direction fictive décrit une activité industrielle en croissance. "
                               "Une dépendance à certains clients et un risque de renchérissement des matières premières "
                               "sont évoqués. Cet extrait sert uniquement à illustrer le format de données du bot."}],
    }
    beta = copy.deepcopy(alpha)
    beta.update(symbol="BETA.SYN", name="Beta Chère — société fictive", documents=[])
    beta["valuation"].update(trailing_pe=120, forward_pe=100, ev_ebitda=80)
    gamma = copy.deepcopy(alpha)
    gamma.update(symbol="GAMMA.SYN", name="Gamma Fragile — société fictive")
    gamma["annual"][0].update(operating_income=-20, net_income=-15, operating_cash_flow=-22,
                               free_cash_flow=-26, cash=10, dividends_paid=1, dividends_are_common=True)
    delta = copy.deepcopy(alpha)
    delta.update(symbol="DELTA.SYN", name="Delta Incomplète — société fictive")
    delta["annual"] = delta["annual"][:2]
    for company in (beta, gamma, delta):
        slug = company["symbol"].split(".")[0].lower()
        company["source_url"] = f"https://example.invalid/{slug}/comptes-fictifs"
        for document in company["documents"]:
            document["source_url"] = f"https://example.invalid/{slug}/rapport-fictif"
    return [alpha, beta, gamma, delta]
