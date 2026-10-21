"""Conservative, deterministic financial research rules (Python 3.10+).

``classify_phase`` implements the publicly documented *annual* decision tree
at https://stocksimplifier.com/phase-check. It does not query that service.
The first satisfied rule wins. Missing information is never interpreted as
zero. A positive total dividend that is not identified as a common dividend
cannot establish rule 3. Alternatively, ``common_dividend_paid=True`` can
establish the existence of a payment during the financial year, independently
of the ambiguous aggregate amount. A zero profit is deliberately unclassified:
the public documentation does not specify that boundary. Period-end shares
are never substituted with weighted-average or diluted shares.

``analyse_company`` adds OUR unvalidated research heuristic, not the site's
proprietary rating. It scores growth, financial quality, balance sheet,
dilution and positive valuation multiples. Piecewise-linear scoring knots
below are explicit design choices, not fitted probabilities or fair prices.
Negative-profit phases are assessed on margin improvement and cash runway,
not required to have mature-company profits. Banks, insurers, REITs and other
financial lenders need specialist analysis and receive no generic score.

ROIC is only a proxy: operating income * (1 - observed effective tax rate),
divided by average (debt + equity - cash). Both consecutive balance sheets
and a usable tax rate are required. Leases, goodwill and accounting-specific
adjustments are not made. Different sectors therefore remain imperfectly
comparable. No moat or management judgement is inferred from these numbers.

Missing checks receive zero points and remain in the denominator. Thus the
score never exceeds weighted data coverage. Ranking is withheld if coverage
is below 75%, no valuation check is usable, fewer than three annual
observations exist, the phase is unknown, a publication is in the future,
critical inputs are anomalous, the latest financial year ended more than
550 days ago, or the provider snapshot is more than 14 days old. A missing
snapshot date lowers confidence and is never replaced by the retrieval date.
The provider date is a snapshot proxy, not the timestamp of every ratio.
Coverage/confidence
describe data availability and classification evidence, NOT success odds.

Configuration (all optional) lives in ``config['scoring']``:
  min_coverage_pct: 75; min_annual_periods: 3;
  max_financial_age_days: 550; max_snapshot_age_days: 14;
  weights: overrides for growth, quality, balance_sheet, dilution, valuation;
  phase_weights: per-phase overrides, keyed by "1" ... "5".
Weights must be nonnegative and sum to a positive number. They are normalized
to 100. Defaults vary by phase; the ranking_bucket keeps transition candidates
separate from expansion/capital-return phases. Phase 4 itself does not prove
profitability, since dividends take priority over the profit test. Call
``validate_config(config)`` before any API request to reject malformed limits
and weights in every phase. A historical as_of is a validation aid,
not a point-in-time backtest: source revisions and valuation snapshots are
not reconstructed by this engine.
"""

from __future__ import annotations

import math
import unicodedata
from datetime import date, datetime
from typing import Any


PHASE_NAMES = {
    1: "Startup", 2: "Hyper Growth", 3: "Operating Leverage",
    4: "Capital Return", 5: "Decline",
}
CATEGORIES = ("growth", "quality", "balance_sheet", "dilution", "valuation")
ANNUAL_NUMBERS = (
    "revenue", "gross_profit", "operating_income", "net_income",
    "operating_cash_flow", "capex", "free_cash_flow", "dividends_paid",
    "shares_end", "shares_diluted", "total_debt", "cash", "equity",
    "tax_expense", "income_before_tax", "interest_expense",
)
VALUATION_KEYS = ("trailing_pe", "forward_pe", "price_sales", "price_book", "ev_ebitda")


def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def _text(value: Any) -> str:
    return unicodedata.normalize("NFKD", str(value or "")).encode(
        "ascii", "ignore"
    ).decode().lower()


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(str(v) for v in values if v))


def _annual(company: dict) -> tuple[list[dict], list[str]]:
    rows: list[dict] = []
    problems: list[str] = []
    raw_rows = company.get("annual") or []
    if not isinstance(raw_rows, list):
        return [], ["Les comptes annuels ne sont pas une liste exploitable."]
    seen: set[date] = set()
    for raw in raw_rows:
        if not isinstance(raw, dict) or _date(raw.get("date")) is None:
            problems.append("Une date de clôture annuelle est absente ou invalide.")
            continue
        period = _date(raw["date"])
        if period in seen:
            problems.append("Plusieurs observations ont la même clôture annuelle.")
            continue
        seen.add(period)
        row = dict(raw)
        row["_date"] = period
        row["_filing_date"] = _date(raw.get("filing_date"))
        for key in ANNUAL_NUMBERS:
            row[key] = _num(raw.get(key))
            if raw.get(key) is not None and row[key] is None:
                problems.append(f"Valeur non numérique ou non finie : {key} ({period}).")
        rows.append(row)
    rows.sort(key=lambda row: row["_date"], reverse=True)
    return rows, _unique(problems)


def _consecutive(newer: dict, older: dict) -> bool:
    # Allows 52/53-week fiscal years, but not a skipped annual report.
    return 300 <= (newer["_date"] - older["_date"]).days <= 430


def _same_currency(*rows: dict) -> bool:
    currencies = {str(row.get("currency")).upper() for row in rows if row.get("currency")}
    return len(currencies) <= 1


def _profit_metric(company: dict) -> str:
    industry = _text(company.get("industry"))
    # Payments are tested first: a payment company can also say "financial services".
    cash_flow_industries = (
        "software", "information technology services", "it services", "payment",
        "biotechnology", "biotech", "pharmaceutical", "health care technology",
        "healthcare technology", "health information", "life sciences tools",
        "life science tools", "media", "entertainment", "professional services",
    )
    if any(term in industry for term in cash_flow_industries):
        return "operating_cash_flow"
    net_income_industries = (
        "bank", "capital markets", "consumer finance", "financial services",
        "insurance", "assurance", "mortgage reit", "credit services",
        "asset management", "investment banking", "securities brokerage",
    )
    if any(term in industry for term in net_income_industries):
        return "net_income"
    return "operating_income"


def _specialist(company: dict) -> bool:
    industry = _text(company.get("industry"))
    sector = _text(company.get("sector"))
    if not industry and "financ" in sector:
        # A missing industry cannot make a potential lender look industrial.
        return True
    if any(term in industry for term in ("reit", "real estate investment trust")):
        return True
    return _profit_metric(company) == "net_income"


def _phase(
    phase_id: int | None, reason: str, metric: str,
    confidence: str = "documented", warnings: list[str] | None = None,
) -> dict:
    return {
        "id": phase_id,
        "name": PHASE_NAMES.get(phase_id, "Unknown"),
        "reason": reason,
        "profit_metric": metric,
        "confidence": confidence if phase_id is not None else (
            "proxy" if confidence == "proxy" else "incomplete"
        ),
        "warnings": _unique(warnings or []),
    }


def classify_phase(company: dict) -> dict:
    """Classify from annual statements; return explicit uncertainty when needed."""
    metric = _profit_metric(company)
    rows, problems = _annual(company)
    if not rows or problems:
        return _phase(None, "Comptes annuels insuffisants ou incohérents.", metric,
                      warnings=problems)
    current = rows[0]
    if len(rows) < 2:
        return _phase(None, "Il manque l'exercice précédent pour tester les règles prioritaires.", metric)
    previous = rows[1]
    if not _consecutive(current, previous):
        return _phase(None, "Les deux derniers exercices disponibles ne sont pas consécutifs.", metric)
    if not _same_currency(current, previous):
        return _phase(None, "La devise des revenus change entre les deux derniers exercices.", metric)
    revenue, old_revenue = current["revenue"], previous["revenue"]
    if revenue is None or old_revenue is None or revenue < 0 or old_revenue < 0:
        return _phase(None, "Chiffre d'affaires annuel absent ou anormal : phase non déterminable.", metric)
    if revenue == 0 and old_revenue == 0:
        return _phase(1, "Chiffre d'affaires nul pendant deux exercices consécutifs.", metric)
    if revenue < old_revenue:
        if len(rows) < 3 or not _consecutive(previous, rows[2]) or not _same_currency(current, previous, rows[2]):
            return _phase(None, "Une baisse des revenus est observée, mais le deuxième exercice de comparaison manque.", metric)
        older_revenue = rows[2]["revenue"]
        if older_revenue is None or older_revenue < 0:
            return _phase(None, "Historique des revenus insuffisant pour écarter deux baisses successives.", metric)
        if old_revenue < older_revenue:
            return _phase(5, "Chiffre d'affaires en baisse pendant deux exercices consécutifs.", metric)
    if current.get("common_dividend_paid") is True:
        result = _phase(4, "Un paiement de dividende ordinaire du titre est identifié pendant le dernier exercice.", metric)
        if current.get("common_dividend_source"):
            result["evidence_source"] = current["common_dividend_source"]
        return result
    dividend = current["dividends_paid"]
    if dividend is None or dividend < 0:
        return _phase(None, "Le montant des dividendes est absent ou anormal ; l'absence de dividende n'est pas établie.", metric)
    if dividend > 0:
        if current.get("dividends_are_common") is True:
            return _phase(4, "Un dividende ordinaire a été versé pendant le dernier exercice.", metric)
        return _phase(
            None, "Dividende ordinaire à confirmer : le montant global ne distingue pas les catégories d'actions.",
            metric, confidence="proxy",
            warnings=["Un dividende global positif ne suffit pas à valider la phase 4."],
        )
    profit, old_profit = current[metric], previous[metric]
    if profit is None:
        return _phase(None, "L'indicateur de profit adapté au secteur est absent.", metric)
    if profit == 0:
        return _phase(None, "Profit exactement nul : ce cas limite n'est pas précisé dans la règle publique.", metric)
    if profit < 0:
        if old_profit is not None and old_profit < 0 and profit > old_profit:
            return _phase(2, "La perte annuelle diminue strictement par rapport à la perte précédente.", metric)
        if old_profit is None:
            return _phase(
                1, "L'entreprise est en perte et la perte antérieure manque ; la règle publique la place en Startup.",
                metric, confidence="incomplete", warnings=["L'amélioration éventuelle de la perte ne peut pas être vérifiée."],
            )
        return _phase(1, "La perte ne diminue pas, ou le dernier exercice est passé du profit à la perte.", metric)
    shares, old_shares = current["shares_end"], previous["shares_end"]
    if shares is not None and old_shares is not None:
        if shares <= 0 or old_shares <= 0:
            return _phase(None, "Nombre d'actions en fin d'exercice nul ou négatif : donnée anormale.", metric)
        if shares < old_shares:
            return _phase(4, "L'entreprise est profitable et le nombre d'actions en fin d'exercice diminue.", metric)
        return _phase(3, "L'entreprise est profitable, sans dividende, et ses actions en fin d'exercice ne diminuent pas.", metric)
    return _phase(
        3, "L'entreprise est profitable sans dividende ; la règle publique retient la phase 3 lorsque les actions de fin d'exercice manquent.",
        metric, confidence="incomplete",
        warnings=["Rachats nets non vérifiables : actions de fin d'exercice absentes. Les actions diluées ne les remplacent pas."],
    )


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    result = numerator / denominator
    return result if math.isfinite(result) else None


def _cagr(rows: list[dict], field: str) -> tuple[float | None, float | None]:
    if len(rows) < 2 or rows[0].get(field) is None or rows[0][field] <= 0:
        return None, None
    current = rows[0]
    for previous in reversed(rows[1:5]):
        if previous.get(field) is None or previous[field] <= 0 or not _same_currency(current, previous):
            continue
        years = (current["_date"] - previous["_date"]).days / 365.25
        if years < 0.75:
            continue
        try:
            growth = (current[field] / previous[field]) ** (1 / years) - 1
        except (OverflowError, ZeroDivisionError):
            continue
        if math.isfinite(growth):
            return growth, years
    return None, None


def _margin_change(current: dict, previous: dict | None, numerator: str) -> float | None:
    if previous is None or not _consecutive(current, previous) or not _same_currency(current, previous):
        return None
    now, old = _ratio(current.get(numerator), current.get("revenue")), _ratio(previous.get(numerator), previous.get("revenue"))
    return now - old if now is not None and old is not None else None


def _roic_proxy(current: dict, previous: dict | None) -> float | None:
    if previous is None or not _consecutive(current, previous) or not _same_currency(current, previous):
        return None
    tax = current["tax_expense"]
    pre_tax = current["income_before_tax"]
    income = current["operating_income"]
    if tax is None or pre_tax is None or income is None or pre_tax <= 0 or not 0 <= tax <= pre_tax:
        return None
    capitals: list[float] = []
    for row in (current, previous):
        if any(row[key] is None for key in ("total_debt", "equity", "cash")):
            return None
        capital = row["total_debt"] + row["equity"] - row["cash"]
        if capital <= 0:
            return None
        capitals.append(capital)
    return _ratio(income * (1 - tax / pre_tax), sum(capitals) / 2)


def _metrics(rows: list[dict], profit_metric: str, specialist: bool) -> dict:
    result: dict[str, Any] = {}
    if not rows:
        return result
    now = rows[0]
    previous = rows[1] if len(rows) > 1 else None
    for key in ("revenue", "operating_income", "net_income", "operating_cash_flow", "free_cash_flow", "total_debt", "cash"):
        result[key] = now[key]
    result["revenue_cagr"], result["revenue_cagr_years"] = _cagr(rows, "revenue")
    result["revenue_growth_latest_annualized"], result["revenue_growth_latest_years"] = _cagr(rows[:2], "revenue")
    result["diluted_share_cagr"], result["diluted_share_cagr_years"] = _cagr(rows, "shares_diluted")
    result["gross_margin"] = _ratio(now["gross_profit"], now["revenue"])
    result["operating_margin"] = _ratio(now["operating_income"], now["revenue"])
    result["free_cash_flow_margin"] = _ratio(now["free_cash_flow"], now["revenue"])
    result["profit_metric_margin"] = _ratio(now[profit_metric], now["revenue"])
    result["gross_margin_change"] = _margin_change(now, previous, "gross_profit")
    result["operating_margin_change"] = _margin_change(now, previous, "operating_income")
    result["profit_margin_change"] = _margin_change(now, previous, profit_metric)
    result["fcf_margin_change"] = _margin_change(now, previous, "free_cash_flow")
    result["roic_proxy"] = None if specialist else _roic_proxy(now, previous)
    result["net_debt"] = (
        now["total_debt"] - now["cash"]
        if now["total_debt"] is not None and now["cash"] is not None else None
    )
    result["net_debt_to_fcf"] = None if specialist else _ratio(result["net_debt"], now["free_cash_flow"])
    interest = now["interest_expense"]
    result["interest_coverage"] = None if specialist else _ratio(
        now["operating_income"], abs(interest) if interest is not None else None
    )
    result["cash_runway_years"] = (
        _ratio(now["cash"], -now["operating_cash_flow"])
        if now["operating_cash_flow"] is not None and now["operating_cash_flow"] < 0 else None
    )
    result["cash_to_debt"] = None if specialist else _ratio(now["cash"], now["total_debt"])
    result["fcf_to_net_income"] = _ratio(now["free_cash_flow"], now["net_income"])
    result["consecutive_latest_years"] = len(rows) > 1 and _consecutive(rows[0], rows[1])
    recent = rows[:3]
    complete_fcf = len(recent) == 3 and all(row["free_cash_flow"] is not None for row in recent)
    result["fcf_positive_last_three_years"] = (
        all(row["free_cash_flow"] > 0 for row in recent)
        if complete_fcf and all(_consecutive(recent[i], recent[i + 1]) for i in range(2)) else None
    )
    return {
        key: (round(value, 8) if math.isfinite(value) else None)
        if isinstance(value, float) else value
        for key, value in result.items()
    }


def _interpolate(value: float | None, knots: list[tuple[float, float]]) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    if value <= knots[0][0]:
        return knots[0][1]
    for (left, a), (right, b) in zip(knots, knots[1:]):
        if value <= right:
            return a + (b - a) * (value - left) / (right - left)
    return knots[-1][1]


def _settings(config: dict, phase_id: int | None) -> tuple[dict, dict]:
    settings = config.get("scoring", config) if isinstance(config, dict) else {}
    if not isinstance(settings, dict):
        raise ValueError("La configuration scoring doit être un dictionnaire.")
    weights = dict(zip(CATEGORIES, (25.0, 30.0, 20.0, 10.0, 15.0)))
    if phase_id in (1, 2):
        weights.update(dict(zip(CATEGORIES, (35.0, 20.0, 25.0, 10.0, 10.0))))
    elif phase_id == 5:
        weights.update(dict(zip(CATEGORIES, (10.0, 20.0, 35.0, 10.0, 25.0))))
    overrides = settings.get("weights", {})
    per_phase = settings.get("phase_weights", {})
    if not isinstance(overrides, dict) or not isinstance(per_phase, dict):
        raise ValueError("weights et phase_weights doivent être des dictionnaires.")
    phase_override = per_phase.get(str(phase_id), per_phase.get(phase_id, {}))
    if not isinstance(phase_override, dict):
        raise ValueError("Chaque entrée phase_weights doit être un dictionnaire.")
    for key, raw in {**overrides, **phase_override}.items():
        if key not in CATEGORIES:
            raise ValueError(f"Catégorie de score inconnue : {key}.")
        value = _num(raw)
        if value is None or value < 0:
            raise ValueError(f"Pondération invalide : {key}.")
        weights[key] = value
    total = sum(weights.values())
    if total <= 0 or not math.isfinite(total):
        raise ValueError("Au moins une pondération doit être positive.")
    weights = {key: value * 100 / total for key, value in weights.items()}
    return settings, weights


def _limits(settings: dict) -> tuple[float, float, int, float]:
    min_coverage = _num(settings.get("min_coverage_pct", 75))
    max_age = _num(settings.get("max_financial_age_days", 550))
    min_periods = _num(settings.get("min_annual_periods", 3))
    max_snapshot_age = _num(settings.get("max_snapshot_age_days", 14))
    if min_coverage is None or not 0 <= min_coverage <= 100:
        raise ValueError("min_coverage_pct doit être compris entre 0 et 100.")
    if max_age is None or max_age < 0:
        raise ValueError("max_financial_age_days doit être un nombre positif ou nul.")
    if min_periods is None or min_periods < 2 or not min_periods.is_integer():
        raise ValueError("min_annual_periods doit être un entier d'au moins 2.")
    if max_snapshot_age is None or max_snapshot_age < 0:
        raise ValueError("max_snapshot_age_days doit être un nombre positif ou nul.")
    return min_coverage, max_age, int(min_periods), max_snapshot_age


def validate_config(config: dict) -> None:
    """Validate every phase and numeric limit without I/O or company data.

    Raise ValueError before a caller spends API requests on an invalid scan.
    This function neither mutates the input nor invokes analyse_company.
    """
    if not isinstance(config, dict):
        raise ValueError("La configuration doit être un dictionnaire.")
    settings, _ = _settings(config, None)
    _limits(settings)
    per_phase = settings.get("phase_weights", {})
    for phase_key in per_phase:
        if isinstance(phase_key, bool) or str(phase_key) not in {"1", "2", "3", "4", "5"}:
            raise ValueError(f"Phase inconnue dans phase_weights : {phase_key}.")
    for phase_id in PHASE_NAMES:
        _settings(config, phase_id)


def _checks(rows: list[dict], phase: dict, metrics: dict, valuation: dict, weights: dict) -> list[dict]:
    if not rows:
        return []
    checks: list[dict] = []
    current = rows[0]
    early = phase["id"] in (1, 2)

    def add(category: str, portion: float, label: str, value: Any, fraction: float | None) -> None:
        maximum = weights[category] * portion
        if maximum <= 0:
            return
        if isinstance(value, float):
            value = round(value, 4)
        fraction = max(0.0, min(1.0, fraction)) if fraction is not None else None
        checks.append({
            "label": label, "value": value,
            "passed": None if fraction is None else fraction >= 0.6,
            "points": round(maximum * fraction, 6) if fraction is not None else 0.0,
            "max_points": round(maximum, 6), "category": category,
        })

    def percent(value: float | None) -> float | None:
        return value * 100 if value is not None else None

    growth_knots = [(-0.10, 0.0), (0.0, 0.2), (0.05, 0.4), (0.10, 0.6), (0.20, 0.85), (0.35, 1.0)]
    if early:
        growth_knots = [(-0.10, 0.0), (0.0, 0.15), (0.10, 0.4), (0.20, 0.65), (0.35, 0.85), (0.50, 1.0)]
    for key, part, label in (
        ("revenue_cagr", 0.6, "Croissance annualisée des revenus sur l'historique disponible (%/an)"),
        ("revenue_growth_latest_annualized", 0.4, "Croissance annualisée des revenus sur la dernière période (%/an)"),
    ):
        add("growth", part, label, percent(metrics.get(key)), _interpolate(metrics.get(key), growth_knots))
    margin_knots = [(-0.10, 0.0), (-0.03, 0.15), (0.0, 0.5), (0.02, 0.8), (0.05, 1.0)]
    if early:
        improvement_knots = [(-0.20, 0.0), (0.0, 0.25), (0.05, 0.6), (0.15, 0.85), (0.30, 1.0)]
        for key, part, label, knots in (
            ("profit_margin_change", 0.5, "Amélioration de la marge du profit sectoriel (points de %)", improvement_knots),
            ("gross_margin_change", 0.25, "Évolution de la marge brute (points de %)", margin_knots),
            ("fcf_margin_change", 0.25, "Amélioration de la marge de trésorerie disponible (points de %)", improvement_knots),
        ):
            add("quality", part, label, percent(metrics.get(key)), _interpolate(metrics.get(key), knots))
    else:
        for key, part, label, knots in (
            ("operating_margin_change", 0.27, "Évolution de la marge opérationnelle (points de %)", margin_knots),
            ("roic_proxy", 0.33, "ROIC approximatif, avant ajustements comptables (%)", [(0, 0), (0.05, 0.2), (0.10, 0.5), (0.15, 0.8), (0.25, 1)]),
            ("free_cash_flow_margin", 0.27, "Marge de trésorerie disponible (%)", [(-0.20, 0), (0, 0.2), (0.03, 0.4), (0.10, 0.7), (0.20, 1)]),
            ("gross_margin_change", 0.13, "Évolution de la marge brute (points de %)", margin_knots),
        ):
            add("quality", part, label, percent(metrics.get(key)), _interpolate(metrics.get(key), knots))
    if early:
        runway = metrics.get("cash_runway_years")
        add("balance_sheet", 0.6, "Autonomie de trésorerie au rythme du cash-flow opérationnel (années)", runway,
            _interpolate(runway, [(0, 0), (0.5, 0.1), (1, 0.4), (2, 0.8), (3, 1)]))
        cash, debt = current["cash"], current["total_debt"]
        fraction = _interpolate(metrics.get("cash_to_debt"), [(0, 0), (0.25, 0.2), (0.5, 0.5), (1, 0.8), (2, 1)])
        value: Any = metrics.get("cash_to_debt")
        if debt == 0 and cash is not None and cash >= 0:
            fraction, value = 1.0, "Aucune dette financière déclarée"
        add("balance_sheet", 0.4, "Trésorerie rapportée à la dette financière", value, fraction)
    else:
        net_debt, fcf = metrics.get("net_debt"), current["free_cash_flow"]
        value = metrics.get("net_debt_to_fcf")
        fraction = _interpolate(value, [(0, 1), (1, 0.9), (3, 0.6), (5, 0.25), (8, 0)])
        if net_debt is not None and net_debt <= 0:
            value, fraction = "Trésorerie nette positive ou nulle", 1.0
        elif net_debt is not None and fcf is not None and fcf <= 0:
            value, fraction = "Dette nette avec trésorerie disponible non positive", 0.0
        add("balance_sheet", 0.6, "Capacité de couverture de la dette nette", value, fraction)
        interest, income = current["interest_expense"], current["operating_income"]
        value = metrics.get("interest_coverage")
        fraction = _interpolate(value, [(0, 0), (1, 0.1), (3, 0.4), (5, 0.7), (10, 1)])
        if interest == 0 and income is not None:
            value = "Charge d'intérêts déclarée nulle"
            fraction = 1.0 if income > 0 else 0.0
        add("balance_sheet", 0.4, "Couverture des intérêts par le résultat opérationnel", value, fraction)
    dilution = metrics.get("diluted_share_cagr")
    add("dilution", 1.0, "Croissance annualisée du nombre dilué d'actions (%/an)", percent(dilution),
        _interpolate(dilution, [(-0.02, 1), (0, 0.8), (0.02, 0.5), (0.05, 0.2), (0.10, 0)]))
    if early:
        multiple = valuation.get("price_sales")
        usable = multiple if multiple is not None and multiple > 0 else None
        add("valuation", 1.0, "Prix / chiffre d'affaires (heuristique, à comparer au secteur)", multiple,
            _interpolate(usable, [(1, 1), (3, 0.8), (5, 0.6), (10, 0.2), (20, 0)]))
    else:
        for key, part, label, knots in (
            ("trailing_pe", 0.35, "P/E historique positif (heuristique)", [(10, 1), (15, 0.85), (25, 0.55), (40, 0.2), (60, 0)]),
            ("forward_pe", 0.35, "P/E prévisionnel positif (estimations incertaines)", [(10, 1), (15, 0.85), (25, 0.55), (40, 0.2), (60, 0)]),
            ("ev_ebitda", 0.3, "Valeur d'entreprise / EBITDA positif (heuristique)", [(6, 1), (10, 0.8), (16, 0.5), (25, 0.15), (40, 0)]),
        ):
            value = valuation.get(key)
            usable = value if value is not None and value > 0 else None
            add("valuation", part, label, value, _interpolate(usable, knots))
    return checks


def _anomalies(rows: list[dict], as_of: date, company: dict) -> list[str]:
    risks: list[str] = []
    for row in rows:
        if row["_date"] > as_of:
            risks.append("Une clôture annuelle se situe dans le futur : classement refusé.")
        if row["_filing_date"] is not None and row["_filing_date"] > as_of:
            risks.append("Une publication financière se situe après la date d'analyse : classement refusé.")
        if row["_filing_date"] is not None and row["_filing_date"] < row["_date"]:
            risks.append("Une publication annuelle précède la clôture correspondante.")
        for key in ("revenue", "total_debt", "cash", "capex", "dividends_paid"):
            if row[key] is not None and row[key] < 0:
                risks.append(f"Montant anormal pour {key} : une valeur positive ou nulle est attendue.")
        for key in ("shares_end", "shares_diluted"):
            if row[key] is not None and row[key] <= 0:
                risks.append(f"Nombre d'actions anormal : {key} est nul ou négatif.")
        revenue, gross_profit = row["revenue"], row["gross_profit"]
        if revenue is not None and gross_profit is not None and gross_profit > revenue + max(1e-6, abs(revenue) * 0.005):
            risks.append("Le bénéfice brut dépasse le chiffre d'affaires : données à contrôler.")
        if row.get("filing_date") and row["_filing_date"] is None:
            risks.append("Une date de publication financière est invalide.")
    if rows and not _same_currency(*rows):
        risks.append("La devise comptable change dans l'historique ; les montants ne sont pas comparables directement.")
    for newer, older in zip(rows, rows[1:]):
        if not _consecutive(newer, older):
            continue
        for key in ("shares_end", "shares_diluted"):
            a, b = newer[key], older[key]
            if a is not None and b is not None and a > 0 and b > 0 and (a / b >= 5 or a / b <= 0.2):
                risks.append("Variation extrême du nombre d'actions : fractionnement, regroupement ou émission à vérifier.")
    return _unique(risks)


def analyse_company(company: dict, config: dict, as_of: date | None = None) -> dict:
    """Return a JSON-compatible research record; never make a trading decision."""
    analysis_date = _date(as_of) if as_of is not None else date.today()
    if analysis_date is None:
        raise ValueError("as_of doit être une date valide.")
    rows, preparation_problems = _annual(company)
    phase = classify_phase(company)
    settings, weights = _settings(config, phase["id"])
    min_coverage, max_age, min_periods, max_snapshot_age = _limits(settings)
    specialist = _specialist(company)
    metrics = _metrics(rows, phase["profit_metric"], specialist)
    raw_valuation = company.get("valuation") or {}
    valuation = {key: _num(raw_valuation.get(key)) for key in VALUATION_KEYS}
    checks = [] if specialist else _checks(rows, phase, metrics, valuation, weights)
    valuation_available = any(check["category"] == "valuation" and check["passed"] is not None for check in checks)
    maximum = sum(check["max_points"] for check in checks)
    available = sum(check["max_points"] for check in checks if check["passed"] is not None)
    coverage = round(100 * available / maximum, 2) if maximum else 0.0
    raw_score = round(100 * sum(check["points"] for check in checks) / maximum, 2) if maximum else None
    raw_warnings = company.get("data_warnings") or []
    risks = list(raw_warnings) if isinstance(raw_warnings, list) else [str(raw_warnings)]
    risks.extend(phase.get("warnings", []))
    fatal = _unique(preparation_problems + _anomalies(rows, analysis_date, company))
    snapshot_date = _date(company.get("provider_updated_at"))
    snapshot_age = (analysis_date - snapshot_date).days if snapshot_date is not None else None
    if snapshot_age is not None and snapshot_age < 0:
        fatal.append("La date du snapshot fournisseur est dans le futur : classement refusé.")
    if snapshot_date is None:
        risks.append("Date du snapshot fournisseur absente ou invalide : fraîcheur des ratios non vérifiable ; la date de récupération ne la remplace pas.")
    risks.extend(fatal)
    strengths: list[str] = []
    for check in checks:
        if check["passed"] is None:
            continue
        proportion = check["points"] / check["max_points"]
        description = f"{check['label']} : {check['value']}."
        if proportion >= 0.8:
            strengths.append(description)
        elif proportion <= 0.25:
            risks.append(description)
    if rows and rows[0]["_filing_date"] is None:
        risks.append("Date de publication absente : chronologie de disponibilité non vérifiée, inutilisable comme preuve d'un backtest.")
    if len(rows) > 1 and any(not _consecutive(a, b) for a, b in zip(rows, rows[1:])):
        risks.append("L'historique contient des exercices manquants ; les croissances utilisent les durées calendaires exactes.")
    if phase["id"] is None:
        risks.append(phase["reason"])
    if phase["id"] == 5:
        risks.append("Déclin apparent : l'analyse des actifs et du caractère cyclique reste nécessaire ; les multiples seuls peuvent tromper.")
    if coverage < 100 and checks:
        risks.append("Certains critères ne sont pas calculables ; ils n'apportent aucun point au score.")
    if not specialist and not valuation_available:
        risks.append("Aucun critère de valorisation n'est exploitable : le prix ne peut pas être évalué, classement refusé.")
    if len(rows) < min_periods:
        risks.append(f"Historique trop court : au moins {int(min_periods)} exercices sont requis pour le classement.")
    if metrics.get("roic_proxy") is not None:
        risks.append("Le ROIC est une approximation comptable non ajustée, pas une mesure auditée du rendement du capital.")
    if any(valuation.get(key) is not None and valuation[key] <= 0 for key in ("trailing_pe", "forward_pe", "ev_ebitda", "price_sales")):
        risks.append("Les multiples nuls ou négatifs sont exclus de la note de valorisation ; ils ne prouvent pas une décote.")
    financial_date = rows[0]["_date"] if rows else None
    age = (analysis_date - financial_date).days if financial_date is not None else None
    if fatal:
        status = "insufficient_data"
    elif age is not None and age > max_age:
        status = "stale_data"
        risks.append(f"Dernière clôture vieille de {age} jours, au-delà de la limite de {int(max_age)} jours.")
    elif snapshot_age is not None and snapshot_age > max_snapshot_age:
        status = "stale_data"
        risks.append(f"Snapshot fournisseur vieux de {snapshot_age} jours, au-delà de la limite de {int(max_snapshot_age)} jours ; une récupération récente ne rajeunit pas les données.")
    elif specialist:
        status = "specialist_review"
        risks.append("Banque, assurance, REIT ou intermédiaire financier : modèle sectoriel requis, score générique désactivé.")
    elif phase["id"] is None or coverage < min_coverage or len(rows) < min_periods or raw_score is None or not valuation_available:
        status = "insufficient_data"
    else:
        status = "ranked"
    confidence = "low"
    if status == "ranked" and coverage >= 90 and phase["confidence"] == "documented":
        confidence = "high"
    elif status == "ranked" and coverage >= 70 and phase["id"] is not None:
        confidence = "medium"
    if snapshot_date is None:
        confidence = {"high": "medium", "medium": "low", "low": "low"}[confidence]
    bucket = {1: "early_stage", 2: "transition", 3: "profitable_growth", 4: "profitable_growth", 5: "decline_review"}.get(phase["id"], "unclassified")
    return {
        "symbol": company.get("symbol"), "name": company.get("name"),
        "country": company.get("country"), "sector": company.get("sector"),
        "phase": phase, "metrics": metrics,
        "score": raw_score if status == "ranked" else None,
        "coverage_pct": coverage, "status": status,
        "strengths": _unique(strengths), "risks": _unique(risks), "checks": checks,
        "financial_date": financial_date.isoformat() if financial_date else None,
        "source_url": company.get("source_url"), "retrieved_at": company.get("retrieved_at"),
        "provider_updated_at": snapshot_date.isoformat() if snapshot_date else None,
        "snapshot_age_days": snapshot_age,
        "valuation": valuation, "confidence": confidence,
        "confidence_note": "Qualité et couverture des données, pas probabilité de gain.",
        "ranking_bucket": bucket,
    }
