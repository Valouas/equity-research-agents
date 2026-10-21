"""Local, transparent research reports. No network or trading actions occur here.

The public API is ``write_reports(results, summary, output_dir)`` and the optional
plain-text ``render_alert(results, summary)`` helper. Only records explicitly
marked ``ranked`` and carrying a finite numerical score enter the ranking.
"""

from __future__ import annotations

import csv
import html
import json
import math
from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


_STATUS_LABELS = {
    "ranked": "Classée",
    "insufficient_data": "Données insuffisantes",
    "specialist_review": "Analyse sectorielle nécessaire",
    "stale_data": "Données trop anciennes",
}

_BUCKET_LABELS = {
    "profitable_growth": "Entreprises établies — phases 3 et 4",
    "transition": "Transition vers la rentabilité — phase 2",
    "early_stage": "Début de développement — phase 1",
    "decline_review": "Déclin à examiner — phase 5",
    "unclassified": "Famille non précisée",
}

_AGENT_ROLES = {
    "data_quality": "Qualité et fraîcheur des données",
    "fundamentals": "Fondamentaux économiques",
    "growth": "Croissance",
    "valuation": "Valorisation",
    "risk": "Risques",
    "documents": "Documents et contexte",
    "challenger": "Contre-analyse",
}
_DECISION_LABELS = {
    "shortlist": "À étudier en priorité",
    "watch": "À surveiller",
    "avoid": "Écartée selon les critères",
    "abstain": "Aucune décision",
}
_AGENT_STATUS_LABELS = {
    "support": "Éléments favorables à l’étude",
    "caution": "Réserves",
    "insufficient": "Éléments insuffisants",
}
_QUALITY_LABELS = {
    "documented": "Documentée", "partial": "Partielle", "insufficient": "Insuffisante",
}
_RESEARCH_MODE_LABELS = {
    "rules": "Analyses déterministes par règles",
    "ollama": "Mode Ollama déclaré — exécutions détaillées ci-dessous",
    "mixed": "Mode mixte : règles et appels Ollama",
    "ollama_failed": "Appels Ollama en échec — vérifier le repli sur les règles",
}
_DECISION_METHOD_LABELS = {
    "rules": "Décideur déterministe",
    "ollama_constrained": "Synthèse Ollama encadrée par les contrôles du programme",
    "rules_after_ai_failure": "Décideur déterministe après échec de l’IA",
}

_FRACTION_FIELDS = {
    "revenue_cagr", "revenue_growth_latest_annualized", "diluted_share_cagr",
    "gross_margin", "operating_margin", "free_cash_flow_margin",
    "profit_metric_margin", "roic_proxy",
}
_DELTA_FIELDS = {
    "gross_margin_change", "operating_margin_change", "profit_margin_change", "fcf_margin_change",
}
_YEAR_FIELDS = {
    "revenue_cagr_years", "revenue_growth_latest_years", "diluted_share_cagr_years", "cash_runway_years",
}
_MULTIPLE_FIELDS = {
    "net_debt_to_fcf", "interest_coverage", "cash_to_debt", "fcf_to_net_income",
    "trailing_pe", "forward_pe", "price_sales", "price_book", "ev_ebitda",
    "pe", "pe_ratio", "ps_ratio", "pfcf", "p_fcf", "price_to_fcf",
}

_FIELD_LABELS = {
    "revenue": "Chiffre d’affaires",
    "revenue_growth": "Croissance du chiffre d’affaires",
    "revenue_growth_pct": "Croissance du chiffre d’affaires (%)",
    "revenue_cagr": "Croissance annuelle composée du chiffre d’affaires",
    "revenue_cagr_pct": "Croissance annuelle composée du chiffre d’affaires (%)",
    "net_income": "Résultat net",
    "operating_income": "Résultat opérationnel",
    "operating_cash_flow": "Flux de trésorerie opérationnel",
    "free_cash_flow": "Flux de trésorerie disponible",
    "fcf": "Flux de trésorerie disponible",
    "gross_margin": "Marge brute",
    "gross_margin_pct": "Marge brute (%)",
    "operating_margin": "Marge opérationnelle",
    "operating_margin_pct": "Marge opérationnelle (%)",
    "net_margin": "Marge nette",
    "net_margin_pct": "Marge nette (%)",
    "fcf_margin": "Marge de trésorerie disponible",
    "fcf_margin_pct": "Marge de trésorerie disponible (%)",
    "cash": "Trésorerie",
    "total_debt": "Dette totale",
    "net_debt": "Dette nette",
    "shares_outstanding": "Nombre d’actions en circulation",
    "shares_growth_pct": "Variation du nombre d’actions (%)",
    "share_dilution_pct": "Dilution des actions (%)",
    "market_cap": "Capitalisation boursière",
    "enterprise_value": "Valeur d’entreprise",
    "pe": "Cours / bénéfice",
    "pe_ratio": "Cours / bénéfice",
    "ps_ratio": "Capitalisation / chiffre d’affaires",
    "pfcf": "Capitalisation / trésorerie disponible",
    "p_fcf": "Capitalisation / trésorerie disponible",
    "price_to_fcf": "Capitalisation / trésorerie disponible",
    "fcf_yield": "Rendement de trésorerie disponible",
    "fcf_yield_pct": "Rendement de trésorerie disponible (%)",
    "price": "Cours",
    "price_date": "Date du cours",
    "currency": "Devise",
    "financial_currency": "Devise des comptes",
    "fiscal_year": "Exercice fiscal",
    "revenue_cagr_years": "Période du taux de croissance composé",
    "revenue_growth_latest_annualized": "Croissance récente du chiffre d’affaires, annualisée",
    "revenue_growth_latest_years": "Période de croissance récente",
    "diluted_share_cagr": "Variation annuelle composée du nombre d’actions dilué",
    "diluted_share_cagr_years": "Période de mesure du nombre d’actions",
    "free_cash_flow_margin": "Marge de trésorerie disponible",
    "profit_metric_margin": "Marge de la mesure de rentabilité retenue",
    "gross_margin_change": "Variation de marge brute",
    "operating_margin_change": "Variation de marge opérationnelle",
    "profit_margin_change": "Variation de la marge de rentabilité retenue",
    "fcf_margin_change": "Variation de marge de trésorerie disponible",
    "roic_proxy": "Rendement approximatif du capital investi",
    "net_debt_to_fcf": "Dette nette / trésorerie disponible",
    "interest_coverage": "Couverture des charges d’intérêts",
    "cash_runway_years": "Autonomie de trésorerie estimée",
    "cash_to_debt": "Trésorerie / dette",
    "fcf_to_net_income": "Trésorerie disponible / résultat net",
    "consecutive_latest_years": "Derniers exercices consécutifs",
    "fcf_positive_last_three_years": "Trésorerie disponible positive sur trois exercices consécutifs",
    "trailing_pe": "Cours / bénéfice constaté",
    "forward_pe": "Cours / bénéfice estimé",
    "price_sales": "Capitalisation / chiffre d’affaires",
    "price_book": "Capitalisation / valeur comptable",
    "ev_ebitda": "Valeur d’entreprise / EBITDA",
    "reason": "Explication",
    "status": "État",
    "method": "Méthode",
}


def _sanitize(value: Any) -> Any:
    """Make JSON strictly valid, including for nested NaN/infinity values."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Mapping):
        return {str(key): _sanitize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def _mapping(value: Any) -> Mapping:
    return value if isinstance(value, Mapping) else {}


def _items(value: Any) -> list:
    return list(value) if isinstance(value, (list, tuple)) else []


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        converted = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return converted if math.isfinite(converted) else None


def _number_text(value: Any, digits: int = 1) -> str:
    number = _number(value)
    if number is None:
        return "Non fourni"
    rendered = f"{number:,.{digits}f}"
    if digits:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered.replace(",", "\u202f").replace(".", ",")


def _value_text(value: Any) -> str:
    if value is None or value == "":
        return "Non fourni"
    if value is True:
        return "Oui"
    if value is False:
        return "Non"
    if isinstance(value, float):
        return _number_text(value, digits=4)
    if isinstance(value, int):
        return f"{value:,}".replace(",", "\u202f")
    if isinstance(value, (Mapping, list, tuple)):
        return json.dumps(_sanitize(value), ensure_ascii=False, allow_nan=False)
    return str(value)


def _escape(value: Any) -> str:
    return html.escape(_value_text(value), quote=True)


def _safe_url(value: Any) -> str | None:
    """Allow only explicit HTTPS links without credentials/control characters."""
    if not isinstance(value, str) or not value:
        return None
    if any(character.isspace() or ord(character) < 32 for character in value):
        return None
    if "\\" in value or any(character in value for character in ('<', '>', '"', "'")):
        return None
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme.lower() != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            return None
        # Accessing port validates malformed and out-of-range port specifications.
        _ = parsed.port
    except (ValueError, TypeError):
        return None
    return value


def _ranked_and_other(results: list[dict]) -> tuple[list[dict], list[dict]]:
    ranked, other = [], []
    for result in results:
        if not isinstance(result, Mapping):
            continue
        if result.get("status") == "ranked" and _number(result.get("score")) is not None:
            ranked.append(result)
        else:
            other.append(result)
    ranked.sort(
        key=lambda result: (
            list(_BUCKET_LABELS).index(_bucket(result)),
            -_number(result.get("score")),
            str(result.get("symbol", "")).casefold(),
            str(result.get("name", "")).casefold(),
        )
    )
    other.sort(
        key=lambda result: (
            str(result.get("status", "")),
            str(result.get("symbol", "")).casefold(),
            str(result.get("name", "")).casefold(),
        )
    )
    return ranked, other


def _bucket(result: Mapping) -> str:
    value = result.get("ranking_bucket")
    if isinstance(value, str) and value in _BUCKET_LABELS:
        return value
    phase_id = _number(_mapping(result.get("phase")).get("id"))
    return {1: "early_stage", 2: "transition", 3: "profitable_growth", 4: "profitable_growth", 5: "decline_review"}.get(phase_id, "unclassified")


def _rank_groups(ranked: list[dict]) -> list[tuple[str, list[tuple[int, dict]]]]:
    groups = {key: [] for key in _BUCKET_LABELS}
    for index, result in enumerate(ranked, 1):
        groups[_bucket(result)].append((index, result))
    return [(key, entries) for key, entries in groups.items() if entries]


def _status_label(result: Mapping) -> str:
    status = result.get("status")
    if status == "ranked" and _number(result.get("score")) is None:
        return "Score indisponible — non classée"
    return _STATUS_LABELS.get(status, "Non classée")


def _label(key: Any) -> str:
    name = str(key)
    return _FIELD_LABELS.get(name, name.replace("_", " ").capitalize())


def _source_link(value: Any) -> str:
    safe = _safe_url(value)
    if safe is None:
        return '<span class="muted">Lien HTTPS indisponible</span>'
    if (urlsplit(safe).hostname or "").endswith(".invalid"):
        return '<span class="muted">Référence fictive de démonstration — aucun document réel</span>'
    return (
        f'<a href="{html.escape(safe, quote=True)}" target="_blank" '
        'rel="noopener noreferrer">Consulter la source ↗</a>'
    )


def _list_html(values: Any, empty_message: str) -> str:
    items = _items(values)
    if not items:
        return f'<p class="muted">{html.escape(empty_message)}</p>'
    return "<ul>" + "".join(f"<li>{_escape(item)}</li>" for item in items) + "</ul>"


def _key_values(values: Any) -> str:
    data = _mapping(values)
    if not data:
        return '<p class="muted">Aucune mesure fournie.</p>'
    rows = "".join(
        f"<tr><th scope=\"row\">{_escape(_label(key))}</th><td>{_escape(_metric_text(str(key), value))}</td></tr>"
        for key, value in data.items()
    )
    return '<div class="table-scroll"><table class="metrics"><tbody>' + rows + "</tbody></table></div>"


def _metric_text(key: str, value: Any) -> str:
    number = _number(value)
    if number is not None:
        if key in _FRACTION_FIELDS:
            return _number_text(number * 100, 2) + " %"
        if key in _DELTA_FIELDS:
            return _number_text(number * 100, 2) + " points de %"
        if key in _YEAR_FIELDS:
            return _number_text(number, 2) + " ans"
        if key in _MULTIPLE_FIELDS:
            return _number_text(number, 2) + " ×"
    return _value_text(value)


def _coverage_text(value: Any) -> str:
    return _number_text(value) + " %" if _number(value) is not None else "Non fournie"


def _checks_html(values: Any) -> str:
    checks = [item for item in _items(values) if isinstance(item, Mapping)]
    if not checks:
        return '<p class="muted">Aucun contrôle détaillé fourni.</p>'
    rows = []
    for check in checks:
        passed = check.get("passed")
        state, css = (
            ("Validé", "yes") if passed is True
            else ("Non validé", "no") if passed is False
            else ("Non évalué", "neutral")
        )
        points = _number_text(check.get("points"))
        maximum = _number_text(check.get("max_points"))
        rows.append(
            f'<tr><th scope="row">{_escape(check.get("label"))}</th>'
            f'<td>{_escape(check.get("value"))}</td>'
            f'<td><span class="badge {css}">{state}</span></td>'
            f'<td class="numeric">{html.escape(points)} / {html.escape(maximum)}</td></tr>'
        )
    return (
        '<div class="table-scroll"><table class="checks"><thead><tr>'
        '<th scope="col">Contrôle</th><th scope="col">Valeur</th>'
        '<th scope="col">Résultat</th><th scope="col" class="numeric">Points</th>'
        '</tr></thead><tbody>' + "".join(rows) + "</tbody></table></div>"
    )


def _search_attr(result: Mapping) -> str:
    text = " ".join(str(result.get(key, "")) for key in ("symbol", "name", "country", "sector"))
    research = _mapping(result.get("research"))
    if research:
        action = _decision_action(research)
        text += " " + _DECISION_LABELS.get(action, "Décision indisponible")
    return html.escape(text, quote=True)


def _decision_action(research: Mapping) -> str | None:
    """Only the documented research scope produces a displayed decision."""
    decision = _mapping(research.get("decision"))
    action = decision.get("action")
    if decision.get("scope") != "research_only" or not isinstance(action, str):
        return None
    return action if action in _DECISION_LABELS else None


def _decision_badge(research: Mapping) -> str:
    action = _decision_action(research)
    css = {"shortlist": "yes", "watch": "watch", "avoid": "no", "abstain": "neutral"}.get(action, "neutral")
    return f'<span class="badge {css}">{_DECISION_LABELS.get(action, "Décision indisponible")}</span>'


def _agent_records(research: Mapping) -> list[Mapping]:
    return [agent for agent in _items(research.get("agents")) if isinstance(agent, Mapping)]


def _execution_counts(research: Mapping) -> dict[str, int]:
    """Count completed analyses from their records, never from a mode label."""
    agents = _agent_records(research)
    return {
        "rules": sum(agent.get("method") == "rules" and agent.get("execution_status") == "completed" for agent in agents),
        "ollama": sum(agent.get("method") == "ollama" and agent.get("execution_status") == "completed" for agent in agents),
        "failed": sum(agent.get("execution_status") == "failed" for agent in agents),
        "skipped": sum(agent.get("execution_status") == "skipped" for agent in agents),
        "roles": len({agent.get("agent_id") for agent in agents if isinstance(agent.get("agent_id"), str) and agent.get("agent_id") in _AGENT_ROLES}),
    }


def _data_kind_text(research: Mapping) -> str:
    kind = research.get("data_kind")
    if kind == "synthetic":
        return "Données synthétiques — chiffres de test, aucun résultat de marché"
    if kind == "provided":
        return "Données fournies — leur présence ne garantit ni vérification ni actualité"
    return "Nature des données non précisée"


def _evidence_links(values: Any, research: Mapping, index: int) -> str:
    evidence = _mapping(research.get("evidence"))
    anchors = {str(key): position for position, key in enumerate(evidence, 1)}
    links = []
    for item in _items(values):
        key = str(item)
        if key in anchors:
            links.append(f'<a class="evidence-ref" href="#evidence-{index}-{anchors[key]}">{_escape(key)}</a>')
        else:
            links.append(f'<span class="evidence-missing">{_escape(key)} — référence absente</span>')
    return ' · '.join(links) if links else '<span class="muted">Aucun élément référencé.</span>'


def _agent_execution_text(agent: Mapping) -> str:
    method, status = agent.get("method"), agent.get("execution_status")
    if status == "completed" and method == "ollama":
        return "IA locale exécutée via Ollama"
    if status == "completed" and method == "rules":
        return "Analyse déterministe exécutée"
    if status == "failed":
        return "Échec de l’analyse Ollama" if method == "ollama" else "Analyse en échec"
    if status == "skipped":
        return "Analyse non exécutée"
    return "Exécution non attestée"


def _analysts_html(research: Mapping, index: int) -> str:
    agents = _agent_records(research)
    cards = []
    ordered = []
    for agent_id, role in _AGENT_ROLES.items():
        records = [agent for agent in agents if agent.get("agent_id") == agent_id]
        if records:
            ordered.extend((agent_id, role, agent) for agent in records)
        else:
            ordered.append((agent_id, role, None))
    ordered.extend(
        (str(agent.get("agent_id")), "Rôle supplémentaire fourni", agent)
        for agent in agents
        if not isinstance(agent.get("agent_id"), str) or agent.get("agent_id") not in _AGENT_ROLES
    )
    for agent_id, default_role, agent in ordered:
        if agent is None:
            cards.append(
                f'<article class="analyst-card missing"><h4>{html.escape(default_role)}</h4>'
                '<p class="muted">Rapport absent — aucune exécution attestée.</p></article>'
            )
            continue
        status = _AGENT_STATUS_LABELS.get(str(agent.get("status")), "Avis non fourni")
        error = f'<p class="execution-error"><strong>Erreur :</strong> {_escape(agent.get("error"))}</p>' if agent.get("error") else ""
        cards.append(f"""
          <article class="analyst-card">
            <h4>{_escape(agent.get('role') or default_role)}</h4>
            <p class="agent-id">Rôle : {_escape(agent_id)} · {_escape(_agent_execution_text(agent))}</p>
            <span class="badge neutral">{status}</span>
            <h5>Constats et raisons</h5>{_list_html(agent.get('reasons'), 'Aucun constat fourni.')}
            <h5>Hypothèses à vérifier</h5>{_list_html(agent.get('hypotheses'), 'Aucune hypothèse fournie.')}
            <h5>Données manquantes</h5>{_list_html(agent.get('missing_data'), 'Aucun manque renseigné ; la complétude reste à vérifier.')}
            <h5>Blocages signalés</h5>{_list_html(agent.get('blockers'), 'Aucun blocage signalé par ce rôle.')}
            <p class="evidence-links"><strong>Éléments utilisés :</strong> {_evidence_links(agent.get('evidence_ids'), research, index)}</p>
            {error}
          </article>""")
    return '<div class="analyst-grid">' + "".join(cards) + '</div>'


def _gates_html(research: Mapping, index: int) -> str:
    gates = [gate for gate in _items(research.get("gates")) if isinstance(gate, Mapping)]
    if not gates:
        return '<p class="muted">Aucun contrôle de décision fourni.</p>'
    rows = []
    for gate in gates:
        passed = gate.get("passed")
        state = "Validé" if passed is True else "Non validé" if passed is False else "Non évalué"
        css = "yes" if passed is True else "no" if passed is False else "neutral"
        severity = {"block": "Bloque la décision", "cap_watch": "Limite à la surveillance"}.get(str(gate.get("severity")), "Effet non précisé")
        rows.append(
            f'<tr><th scope="row">{_escape(gate.get("code"))}</th>'
            f'<td><span class="badge {css}">{state}</span></td><td>{severity}</td>'
            f'<td>{_escape(gate.get("reason"))}<p class="evidence-links">'
            f'{_evidence_links(gate.get("evidence_ids"), research, index)}</p></td></tr>'
        )
    return (
        '<div class="table-scroll"><table class="gates"><thead><tr><th scope="col">Contrôle</th>'
        '<th scope="col">Résultat</th><th scope="col">Effet en cas d’échec</th><th scope="col">Raison et éléments</th>'
        '</tr></thead><tbody>' + "".join(rows) + '</tbody></table></div>'
    )


def _disagreements_html(research: Mapping) -> str:
    parts = []
    for disagreement in _items(research.get("disagreements")):
        if not isinstance(disagreement, Mapping):
            parts.append(f'<li>{_escape(disagreement)}</li>')
            continue
        agent_id = str(disagreement.get("agent_id", ""))
        role = _AGENT_ROLES.get(agent_id, agent_id or "Rôle non précisé")
        status = _AGENT_STATUS_LABELS.get(str(disagreement.get("status")), "Avis non précisé")
        parts.append(
            f'<li><strong>{_escape(role)}</strong> — {status}'
            + _list_html(disagreement.get("reasons"), 'Aucune raison détaillée fournie.') + '</li>'
        )
    return '<ul class="disagreements">' + "".join(parts) + '</ul>' if parts else '<p class="muted">Aucun désaccord consigné. Ce champ ne mesure pas la fiabilité d’une prévision.</p>'


def _evidence_html(research: Mapping, index: int) -> str:
    evidence = _mapping(research.get("evidence"))
    if not evidence:
        return '<p class="empty">Aucun élément de preuve fourni. Le contexte absent reste inconnu.</p>'
    rows = []
    for position, (evidence_id, raw) in enumerate(evidence.items(), 1):
        item = _mapping(raw)
        rows.append(f"""
          <tr id="evidence-{index}-{position}">
            <th scope="row">{_escape(evidence_id)}<span class="evidence-path">{_escape(item.get('path'))}</span></th>
            <td>{_escape(item.get('value'))}<span class="evidence-path">Type : {_escape(item.get('kind'))}</span></td>
            <td>{_escape(item.get('period'))}<span class="evidence-path">Unité : {_escape(item.get('unit'))}</span></td>
            <td>Publication : {_escape(item.get('published_at'))}<span class="evidence-path">Récupération : {_escape(item.get('retrieved_at'))}</span></td>
            <td>{_source_link(item.get('source_url'))}</td>
          </tr>""")
    return (
        f'<details class="evidence-registry"><summary>Ouvrir les {len(evidence)} éléments de preuve et leurs sources</summary>'
        '<div class="table-scroll"><table class="evidence-table"><thead><tr><th scope="col">Référence et champ</th>'
        '<th scope="col">Valeur fournie</th><th scope="col">Période et unité</th>'
        '<th scope="col">Dates de provenance</th><th scope="col">Source</th></tr></thead><tbody>'
        + "".join(rows) + '</tbody></table></div></details>'
    )


def _research_detail(result: Mapping, index: int) -> str:
    research = _mapping(result.get("research"))
    if not research:
        return ""
    decision = _mapping(research.get("decision"))
    quality = _mapping(research.get("quality"))
    llm = _mapping(research.get("llm"))
    counts = _execution_counts(research)
    mode = _RESEARCH_MODE_LABELS.get(str(research.get("execution_mode")), "Mode d’exécution non précisé")
    decision_method = _DECISION_METHOD_LABELS.get(str(decision.get("method")), "Méthode de décision non précisée")
    quality_note = _escape(quality.get("note")) + " " if quality.get("note") else ""
    llm_status = {"not_requested": "Non demandée", "completed": "Exécutée", "failed": "En échec", "skipped": "Non exécutée"}.get(str(decision.get("llm_status")), "Non précisée")
    invalid_scope = (
        '<p class="execution-error">Décision indisponible : action ou portée de recherche non conforme.</p>'
        if _decision_action(research) is None else ""
    )
    proposal = ""
    if decision.get("proposed_action") is not None:
        raw_proposal = str(decision.get("proposed_action"))
        proposal = f'<p class="small">Proposition initiale du modèle : {_escape(_DECISION_LABELS.get(raw_proposal, raw_proposal))}. La conclusion appliquée figure ci-dessus.</p>'
    history_note = ""
    if research.get("report_as_of") and research.get("report_as_of") != research.get("as_of"):
        previous = str(decision.get("previous_action", ""))
        history_note = (
            f'<p class="execution-error">Décision suspendue pour le rapport du {_escape(research.get("report_as_of"))}. '
            f'État précédent : {_escape(_DECISION_LABELS.get(previous, "Non fourni"))}. '
            'Les avis et les compteurs conservés ci-dessous proviennent de la date d’analyse initiale ; '
            'ils ne décrivent pas de nouvelles exécutions.</p>'
        )
    return f"""
      <section class="research-detail" aria-labelledby="decision-{index}">
        <div class="research-decision">
          <div class="eyebrow">Sept analystes spécialisés et un décideur · recherche uniquement</div>
          <h3 id="decision-{index}">Décision de recherche</h3>
          {_decision_badge(research)}
          <p class="decision-summary">{_escape(decision.get('summary'))}</p>
          <p class="small">{_escape(decision_method)} · Synthèse IA : {llm_status}.</p>
          {invalid_scope}{history_note}{proposal}
          <p class="scope-note">« À étudier » fixe une priorité de recherche. « À surveiller » demande un suivi ; « Écartée » concerne les critères étudiés ; « Aucune décision » correspond à une abstention. Aucun de ces états ne constitue un ordre de bourse.</p>
        </div>
        <dl class="metadata research-metadata">
          <div><dt>Date d’analyse</dt><dd>{_escape(research.get('as_of'))}</dd></div>
          <div><dt>Nature des données</dt><dd>{_escape(_data_kind_text(research))}</dd></div>
          <div><dt>Mode d’exécution</dt><dd>{_escape(mode)}</dd></div>
          <div><dt>Qualité du dossier</dt><dd>{_QUALITY_LABELS.get(str(quality.get('level')), 'Non fournie')}</dd></div>
          <div><dt>Couverture des critères financiers</dt><dd>{_coverage_text(quality.get('coverage_pct'))}</dd></div>
          <div><dt>Rapports spécialisés présents</dt><dd>{counts['roles']} / 7 rôles attendus</dd></div>
        </dl>
        <p class="small muted">{quality_note}La qualité et la couverture décrivent les données et les contrôles ; elles ne mesurent pas une probabilité de gain.</p>
        <p class="execution-ledger">Analyses spécialisées exécutées : <strong>{counts['rules']} par règles</strong>, <strong>{counts['ollama']} via Ollama</strong>.
          Échecs déclarés : {counts['failed']}. Analyses non exécutées : {counts['skipped']}.
          Demande IA : {_escape(llm.get('requested'))} ; modèle : {_escape(llm.get('model'))}.
          Tentatives de transport comptabilisées, décideur inclus : {_escape(llm.get('calls'))}.
          Analyses locales validées : {_escape(llm.get('successes'))} ; analyses en échec : {_escape(llm.get('failures'))}, y compris les rejets avant envoi.</p>
        <p class="small muted">Les comptes d’appels décrivent l’exécution technique. La couverture chiffrée reprend les critères du moteur ; les lacunes documentaires figurent dans les contrôles. Plusieurs rôles peuvent partager le même modèle et les mêmes sources.</p>
        <div class="two-columns">
          <section><h3>Raisons de la décision</h3>{_list_html(decision.get('reasons'), 'Aucune justification détaillée fournie.')}
            <p class="evidence-links">{_evidence_links(decision.get('evidence_ids'), research, index)}</p></section>
          <section><h3>Blocages du décideur</h3>{_list_html(decision.get('blockers'), 'Aucun blocage renseigné par le décideur.')}</section>
        </div>
        <h3>Conditions pour réexaminer le dossier</h3>{_list_html(decision.get('conditions_to_reconsider'), 'Aucune condition de réexamen fournie.')}
        <h3>Contrôles qui encadrent la décision</h3>{_gates_html(research, index)}
        <h3>Désaccords et réserves conservés</h3>{_disagreements_html(research)}
        <h3>Les sept rapports spécialisés</h3>
        <p class="small muted">Un rapport par rôle, avec ses constats, ses hypothèses et ses manques. La méthode et l’état d’exécution sont indiqués pour chaque analyse.</p>
        {_analysts_html(research, index)}
        <h3>Éléments de preuve et provenance</h3>
        <p class="small muted">Valeurs conservées dans leur unité d’origine. L’affichage arrondit certaines valeurs ; le JSON conserve leur précision. Une référence à un document permet de retrouver la source ; sa présence ne prouve pas une lecture complète ni une vérification indépendante.</p>
        {_evidence_html(research, index)}
        <h3>Limites du dossier</h3>{_list_html(research.get('caveats'), 'Aucune limite supplémentaire renseignée.')}
      </section>
      <h3 class="financial-section-title">Analyse financière déterministe</h3>
      <p class="small muted">Le score financier et les contrôles ci-dessous sont conservés séparément de la décision de recherche.</p>"""


def _research_overview(ordered: list[dict]) -> str:
    records = [(index, result) for index, result in enumerate(ordered, 1) if _mapping(result.get("research"))]
    if not records:
        return ""
    counts = {action: 0 for action in _DECISION_LABELS}
    rows = []
    for index, result in records:
        research = _mapping(result.get("research"))
        action = _decision_action(research)
        if action in counts:
            counts[action] += 1
        quality = _mapping(research.get("quality"))
        execution = _execution_counts(research)
        kind_label = {"synthetic": "Synthétiques", "provided": "Fournies"}.get(str(research.get("data_kind")), "Nature non précisée")
        rows.append(f"""
          <tr data-result data-search="{_search_attr(result)}">
            <td>{_decision_badge(research)}</td>
            <td><a class="ticker" href="#company-{index}">{_escape(result.get('symbol'))}</a><span class="company-name">{_escape(result.get('name'))}</span></td>
            <td>{_QUALITY_LABELS.get(str(quality.get('level')), 'Non fournie')}<span class="company-name">Couverture : {_coverage_text(quality.get('coverage_pct'))}</span></td>
            <td>{execution['rules']} règles · {execution['ollama']} Ollama<span class="company-name">{execution['roles']} / 7 rôles présents ; {execution['failed']} échecs</span></td>
            <td class="date">{_escape(research.get('as_of'))}<span class="company-name">{kind_label}</span></td>
          </tr>""")
    stats = "".join(f'<span><strong>{count}</strong> {label.lower()}</span>' for action, label in _DECISION_LABELS.items() for count in [counts[action]])
    missing = len(ordered) - len(records)
    missing_text = f'<p class="small muted">{missing} fiche(s) sans rapport des analystes : seule l’analyse financière est disponible pour ces dossiers.</p>' if missing else ""
    return (
        '<section class="section research-overview" aria-labelledby="research-title"><h2 id="research-title">Décisions de recherche</h2>'
        '<p class="section-lead">Le décideur rassemble les analyses spécialisées, les réserves et les contrôles obligatoires. '
        'Ces états orientent le travail d’étude et le suivi des dossiers.</p>'
        '<p class="small muted">Règles = analyses déterministes. Un avis IA exécuté exige un rapport terminé via Ollama. '
        'La couverture et la qualité ne sont pas des probabilités de gain ; les avis ne forment pas un vote.</p>'
        f'<div class="decision-counts">{stats}</div>'
        '<div class="table-scroll"><table class="research-table"><thead><tr>'
        '<th scope="col">Décision de recherche</th><th scope="col">Société</th><th scope="col">Qualité du dossier</th>'
        '<th scope="col">Analyses spécialisées exécutées</th><th scope="col">Date et données</th>'
        '</tr></thead><tbody>' + "".join(rows) + '</tbody></table></div>' + missing_text + '</section>'
    )


def _company_detail(result: Mapping, index: int) -> str:
    phase = _mapping(result.get("phase"))
    score = _number(result.get("score"))
    can_rank = result.get("status") == "ranked" and score is not None
    score_text = f"{_number_text(score)} / 100" if can_rank else "Hors classement"
    source = _source_link(result.get("source_url"))
    meta = [
        ("Pays", result.get("country")),
        ("Secteur", result.get("sector")),
        ("Date des comptes", result.get("financial_date")),
        ("Données récupérées le", result.get("retrieved_at")),
        ("Devise des comptes", result.get("financial_currency", result.get("currency"))),
    ]
    if result.get("provider_updated_at"):
        meta.append(("Mise à jour indiquée par la source", result.get("provider_updated_at")))
    if result.get("quote_currency"):
        meta.append(("Devise de cotation", result.get("quote_currency")))
    definition_list = "".join(f"<div><dt>{label}</dt><dd>{_escape(value)}</dd></div>" for label, value in meta)
    confidence_labels = {"high": "Élevée", "medium": "Moyenne", "low": "Faible"}
    phase_confidence_labels = {"documented": "Documentée", "incomplete": "Incomplète", "proxy": "Approximative"}
    data_confidence = confidence_labels.get(result.get("confidence"), "Non fournie")
    phase_confidence = phase_confidence_labels.get(phase.get("confidence"), "Non fournie")
    return f"""
    <details class="company" id="company-{index}" data-result data-search="{_search_attr(result)}">
      <summary>
        <span class="company-heading"><strong>{_escape(result.get('symbol'))}</strong>
          <span>{_escape(result.get('name'))}</span></span>
        <span class="summary-score">{html.escape(score_text)}</span>
      </summary>
      <div class="company-body">
        {_research_detail(result, index)}
        <div class="badge-line"><span class="badge neutral">{html.escape(_status_label(result))}</span>
          <span class="badge phase">{_escape(phase.get('name'))}</span>
          <span class="coverage">Couverture des données : {_coverage_text(result.get('coverage_pct'))}</span></div>
        <p class="small muted">Famille : {_BUCKET_LABELS[_bucket(result)]}. Qualité des données : {data_confidence}.
          Qualification de phase : {phase_confidence}. Ces indications ne mesurent pas une probabilité de gain.</p>
        <dl class="metadata">{definition_list}</dl>
        <p class="source">{source}</p>
        <div class="phase-explanation"><h3>Pourquoi cette phase ?</h3>
          <p>{_escape(phase.get('reason'))}</p>
          <p class="muted">Mesure de rentabilité utilisée : {_escape(_label(phase.get('profit_metric'))) if phase.get('profit_metric') else 'Non fournie'}.</p></div>
        <div class="two-columns">
          <section><h3>Points favorables</h3>{_list_html(result.get('strengths'), 'Aucun point favorable renseigné.')}</section>
          <section><h3>Risques et limites</h3>{_list_html(result.get('risks'), 'Aucun risque renseigné ; cela ne signifie pas une absence de risque.')}</section>
        </div>
        <h3>Détail du score et des contrôles</h3>{_checks_html(result.get('checks'))}
        <div class="two-columns measures">
          <section><h3>Mesures financières</h3>{_key_values(result.get('metrics'))}</section>
          <section><h3>Valorisation</h3>{_key_values(result.get('valuation'))}</section>
        </div>
      </div>
    </details>"""


_CSS = """
:root{color-scheme:light;--ink:#172c3a;--muted:#62737c;--line:#dbe4e7;--paper:#fff;--bg:#f0f4f5;--green:#16785b;--navy:#133747;--amber:#8b5508}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
a{color:#116575;text-underline-offset:3px}a:hover{color:#093843}button,input{font:inherit}main{max-width:1180px;margin:0 auto;padding:36px 24px 60px}
.masthead{background:var(--navy);color:#fff;padding:34px;border-radius:18px}.eyebrow{text-transform:uppercase;letter-spacing:.13em;font-size:11px;font-weight:750;opacity:.8}
h1{font-size:clamp(28px,4vw,42px);line-height:1.15;margin:11px 0 14px;letter-spacing:-.035em}h2{font-size:23px;line-height:1.3;margin:0 0 10px;letter-spacing:-.02em}h3{font-size:16px;margin:20px 0 8px}p{margin:8px 0 14px}
.masthead p{max-width:800px;color:#dce8ed}.masthead .meta{font-size:13px;color:#cfdee5;margin-bottom:0}.banner{border-radius:12px;margin:20px 0;padding:18px 22px;border:1px solid #e5c67f;background:#fff7e5;color:#634608}.banner p{margin:7px 0 0}.banner.live{border-color:#c8dee3;background:#e9f5f5;color:#234f58}
.stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;margin:20px 0}.stat{background:var(--paper);border:1px solid var(--line);border-radius:12px;padding:18px 20px}.stat strong{display:block;font-size:28px;line-height:1.25;letter-spacing:-.03em}.stat span{font-size:13px;color:var(--muted)}
.section{margin-top:26px;background:var(--paper);border:1px solid var(--line);border-radius:14px;padding:26px}.section-lead{color:var(--muted);max-width:850px}.method{font-size:14px;max-width:950px}.muted{color:var(--muted)}.small{font-size:12px}.run-meta{display:flex;flex-wrap:wrap;gap:6px 24px;font-size:13px;color:var(--muted);padding-top:6px}.run-meta strong{color:var(--ink)}
.search{display:flex;align-items:center;gap:15px;margin:24px 0 0}.search label{font-weight:650}.search input{width:360px;max-width:100%;border:1px solid #b7cbd2;background:#fff;border-radius:9px;padding:10px 12px;outline:none}.search input:focus{border-color:#147d83;box-shadow:0 0 0 3px #147d8320}
.table-scroll{overflow-x:auto;max-width:100%}table{width:100%;border-collapse:collapse;text-align:left;font-size:14px}th{font-weight:650;color:#415a65}td,th{padding:14px 12px;border-bottom:1px solid var(--line);vertical-align:top}thead th{background:#f4f8f9;position:sticky;top:0;font-size:12px;white-space:nowrap;z-index:1}tbody tr:last-child td,tbody tr:last-child th{border-bottom:0}.rank-table td:first-child{width:42px;color:var(--muted)}.ticker{font-weight:750;display:block}.company-name{display:block;color:var(--muted);font-size:12px;max-width:235px}.numeric{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}.score-cell{min-width:115px}.score-value{font-size:17px;font-weight:750}.score-denominator{font-size:11px;color:var(--muted);font-weight:400}.bar{height:4px;background:#e6edef;border-radius:9px;margin-top:7px;overflow:hidden}.bar span{display:block;height:100%;background:var(--green);border-radius:9px}.date{font-size:12px;white-space:nowrap}.badge{display:inline-block;padding:3px 8px;border-radius:6px;font-size:11px;font-weight:650;line-height:1.5}.phase{background:#edf4f9;color:#255873}.neutral{background:#eef1f3;color:#576772}.yes{background:#e4f2ea;color:#286244}.no{background:#fff0e2;color:#8b560f}.empty{padding:24px;background:#f5f8f9;border:1px dashed #c8d7dd;border-radius:10px}
.queue-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin:12px 0 22px}.queue-card{border:1px solid var(--line);border-radius:9px;padding:13px 15px;overflow-wrap:anywhere}.queue-card a{font-weight:750}.queue-card p{margin:3px 0;font-size:12px}.queue-title{font-size:16px;margin-top:20px}.company{border:1px solid var(--line);border-radius:10px;background:#fff;margin:12px 0;overflow:hidden;scroll-margin-top:20px}.company summary{cursor:pointer;display:flex;align-items:center;gap:18px;justify-content:space-between;padding:18px 20px;background:#f7fafb}.company summary:before{content:"+";font-size:20px;font-weight:400;color:#567b86}.company[open] summary:before{content:"−"}.company-heading{flex:1;display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;min-width:0;overflow-wrap:anywhere}.company-heading strong{font-size:17px}.company-heading span{font-size:14px;color:var(--muted)}.summary-score{font-size:13px;font-weight:700;white-space:nowrap}.company-body{padding:5px 22px 24px}.badge-line{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:15px 0}.coverage{font-size:12px;color:var(--muted)}.metadata{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin:20px 0}.metadata dt{font-size:11px;color:var(--muted)}.metadata dd{margin:2px 0 0;font-size:13px;overflow-wrap:anywhere}.source{font-size:13px}.phase-explanation{background:#f5f8f9;border-left:3px solid #94bac4;padding:1px 16px 4px;margin:18px 0}.phase-explanation h3{margin-top:12px}.phase-explanation p{font-size:13px}.two-columns{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:26px}.two-columns section{min-width:0}.two-columns ul{padding-left:20px;font-size:13px}.two-columns li{margin:8px 0;overflow-wrap:anywhere}.checks td,.checks th,.metrics td,.metrics th{font-size:12px;padding:11px 9px;overflow-wrap:anywhere}.metrics th{width:56%;font-weight:500}.metrics td{text-align:right;font-variant-numeric:tabular-nums}.notes{font-size:13px;overflow-wrap:anywhere}.notes li{margin:8px 0}.footer{font-size:12px;color:var(--muted);margin-top:28px}.hidden{display:none!important}
@media(max-width:760px){main{padding:16px 12px 36px}.masthead{padding:25px 22px;border-radius:12px}.stats{grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.stat{padding:15px}.stat strong{font-size:25px}.section{padding:20px 14px}.two-columns,.queue-grid{grid-template-columns:1fr;gap:8px}.metadata{grid-template-columns:repeat(2,minmax(0,1fr))}.search{align-items:stretch;flex-direction:column;gap:6px}.search input{width:100%}.company summary{padding:15px 12px;gap:10px}.company-body{padding:4px 13px 20px}.company-heading{display:block}.company-heading span{display:block;font-size:12px}.summary-score{font-size:11px}.rank-table{min-width:760px}}
@media print{body{background:#fff;font-size:11px}main{max-width:none;padding:0}.masthead{background:#fff;color:#172c3a;border:1px solid #dbe4e7}.masthead p,.masthead .meta{color:#415a65}.search{display:none}.section,.company{break-inside:avoid}.section{padding:15px}.table-scroll{overflow:visible}thead th{position:static}.hidden{display:revert!important}a{color:inherit}.bar{print-color-adjust:exact}}
"""


_SCRIPT = """
const search = document.getElementById('company-search');
const normalize = value => value.normalize('NFD').replace(/[\\u0300-\\u036f]/g, '').toLocaleLowerCase('fr');
if (search) {
  search.addEventListener('input', () => {
    const query = normalize(search.value.trim());
    document.querySelectorAll('[data-result]').forEach(item => {
      item.classList.toggle('hidden', !normalize(item.dataset.search || '').includes(query));
    });
  });
}
document.querySelectorAll('a[href^="#company-"]').forEach(link => {
  link.addEventListener('click', () => {
    const target = document.getElementById(link.getAttribute('href').slice(1));
    if (target) target.open = true;
  });
});
document.querySelectorAll('a[href^="#evidence-"]').forEach(link => {
  link.addEventListener('click', () => {
    let target = document.getElementById(link.getAttribute('href').slice(1));
    while (target) {
      if (target.tagName === 'DETAILS') target.open = true;
      target = target.parentElement;
    }
  });
});
"""


_RESEARCH_CSS = """
.evidence-registry{margin:12px 0 24px;border:1px solid #dbe4e7;border-radius:9px;overflow:hidden}.company .evidence-registry>summary{display:block;padding:13px 16px;font-size:13px;font-weight:650;background:#eef5f5;color:#275b62;cursor:pointer}.company .evidence-registry>summary:before{content:none}
.research-overview{border-top:4px solid #147b80}.research-overview .table-scroll{max-height:520px}.research-table{min-width:770px}.research-table td{font-size:13px}.decision-counts{display:flex;flex-wrap:wrap;gap:10px 24px;margin:18px 0 20px;font-size:13px}.decision-counts strong{font-size:22px;color:#133747;padding-right:4px}.watch{background:#e6f0f6;color:#295b76}.research-detail{overflow-wrap:anywhere}.research-decision{margin:20px 0 14px;padding:22px 24px;background:#eaf5f3;border-left:4px solid #16785b;border-radius:0 10px 10px 0}.research-decision .eyebrow{color:#36665e}.research-decision h3{margin:9px 0 14px;font-size:22px}.research-decision .badge{font-size:13px}.decision-summary{margin-top:14px;font-size:16px}.scope-note{font-size:12px;color:#41635f;margin-bottom:0}.research-metadata{border:1px solid #dbe4e7;padding:16px;border-radius:9px}.execution-ledger{padding:13px 16px;background:#f2f6f8;border-radius:8px;font-size:12px}.execution-error{padding:10px 12px;background:#fff2e7;color:#82561c;border-radius:7px;font-size:12px}.analyst-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;margin:16px 0 24px}.analyst-card{border:1px solid #dbe4e7;border-radius:10px;padding:18px;background:#fbfdfd;min-width:0}.analyst-card h4{font-size:16px;margin:0 0 5px;color:#214f5d}.analyst-card h5{font-size:12px;margin:17px 0 6px;color:#3b5964}.analyst-card p,.analyst-card li{font-size:12px}.analyst-card p{margin:5px 0 10px}.analyst-card ul{margin:5px 0;padding-left:18px}.analyst-card li{margin:6px 0}.analyst-card .agent-id{font-size:11px;color:#62737c}.analyst-card.missing{border-style:dashed;background:#f5f7f8}.evidence-links{font-size:11px;margin:10px 0 0}.evidence-ref{display:inline-block;overflow-wrap:anywhere}.evidence-missing{color:#8b5508}.evidence-table{min-width:860px;table-layout:fixed}.evidence-table th,.evidence-table td,.gates th,.gates td{font-size:12px;padding:11px 9px;overflow-wrap:anywhere}.evidence-table th:first-child{width:22%}.evidence-table th:nth-child(2){width:23%}.evidence-table tr[id]{scroll-margin-top:48px}.evidence-path{display:block;font-size:11px;font-weight:400;color:#62737c;margin-top:5px}.gates{min-width:650px}.disagreements{padding-left:20px;font-size:13px}.disagreements>li{margin:12px 0}.financial-section-title{padding-top:24px;border-top:2px solid #dbe4e7;font-size:20px}.research-detail>ul{font-size:13px;padding-left:20px}.research-detail>ul li{margin:7px 0}
@media(max-width:760px){.analyst-grid{grid-template-columns:1fr;gap:10px}.research-decision{padding:18px 16px}.research-decision h3{font-size:20px}.decision-summary{font-size:14px}.analyst-card{padding:15px}.decision-counts{gap:8px 18px}.research-metadata{padding:12px}.research-overview .table-scroll{max-height:430px}}
@media print{.research-overview .table-scroll{max-height:none}.analyst-card{break-inside:avoid}.research-detail{break-inside:auto}.evidence-table{min-width:0}.research-decision{border:1px solid #a2bfb7}}
"""


def _render_html(results: list[dict], summary: dict) -> str:
    ranked, other = _ranked_and_other(results)
    ordered = ranked + other
    demo = summary.get("mode") == "demo"
    research_records = [_mapping(result.get("research")) for result in ordered if _mapping(result.get("research"))]
    has_synthetic = any(item.get("data_kind") == "synthetic" for item in research_records)
    all_synthetic = bool(research_records) and len(research_records) == len(ordered) and all(item.get("data_kind") == "synthetic" for item in research_records)
    if has_synthetic:
        title = (
            "DÉMONSTRATION SYNTHÉTIQUE — chiffres de test ; aucun résultat de marché"
            if all_synthetic and len(research_records) == len(ordered)
            else "JEU MIXTE — des scénarios synthétiques figurent dans ce rapport"
        )
        banner = (
            f'<aside class="banner"><strong>{title}</strong><p>La nature des données est indiquée pour chaque société. '
            'Les scénarios synthétiques vérifient le fonctionnement du programme. Ils ne constituent pas une sélection mondiale '
            'ni une analyse de comptes réels.</p></aside>'
        )
    elif demo:
        banner = (
            '<aside class="banner"><strong>TEST TECHNIQUE — univers limité à Apple, Amazon et Tesla ; '
            'aucune sélection mondiale</strong><p>Ces trois titres servent à vérifier le fonctionnement du bot. '
            'Le classement est limité à cet échantillon.</p></aside>'
        )
    elif research_records:
        banner = (
            '<aside class="banner live"><strong>Périmètre : dossiers fournis au programme.</strong>'
            '<p>La présence d’une donnée ne garantit ni sa vérification ni son actualité. Les sources, les dates et les '
            'éléments manquants restent visibles par société. La couverture mondiale exhaustive n’est pas établie.</p></aside>'
        )
    else:
        banner = (
            '<aside class="banner live"><strong>Périmètre : titres effectivement collectés et analysés.</strong>'
            '<p>Les résultats dépendent de l’univers configuré, des données disponibles et de l’avancement du parcours. '
            'Un parcours partiel ne constitue pas une recherche mondiale exhaustive.</p></aside>'
        )
    research_html = _research_overview(ordered)
    search_html = (
        '<div class="search"><label for="company-search">Filtrer les sociétés</label>'
        '<input id="company-search" type="search" placeholder="Nom, symbole, pays ou secteur…" autocomplete="off"></div>'
    )
    cards = [
        (len(ranked), "Scores financiers admissibles" if research_records else "Actions classées"),
        (len(ordered), "Fiches dans ce rapport"),
        (summary.get("universe_total"), "Titres dans l’univers déclaré"),
        (summary.get("remaining_count"), "Titres restant à parcourir"),
    ]
    stats = "".join(
        f'<div class="stat"><strong>{_escape(value)}</strong><span>{label}</span></div>'
        for value, label in cards
    )
    run_meta = "".join(
        f'<span>{label} : <strong>{_escape(summary.get(key))}</strong></span>'
        for key, label in (
            ("attempted_count", "Titres tentés pendant ce passage"),
            ("success_count", "Collectes réussies pendant ce passage"),
            ("error_count", "Erreurs pendant ce passage"),
            ("units_used", "Unités de données utilisées"),
        )
    )
    rank_tables = []
    for group_index, (bucket, group) in enumerate(_rank_groups(ranked), 1):
        rows = []
        for rank, (index, result) in enumerate(group, 1):
            phase = _mapping(result.get("phase"))
            score = _number(result.get("score"))
            bar_width = max(0.0, min(100.0, score))
            rows.append(f"""
          <tr data-result data-search="{_search_attr(result)}">
            <td>{rank}</td>
            <td><a class="ticker" href="#company-{index}">{_escape(result.get('symbol'))}</a>
                <span class="company-name">{_escape(result.get('name'))}</span></td>
            <td><span class="badge phase">{_escape(phase.get('name'))}</span></td>
            <td class="numeric score-cell"><span class="score-value">{_number_text(score)}
                <span class="score-denominator">/ 100</span></span>
                <div class="bar" aria-hidden="true"><span style="width:{bar_width:.2f}%"></span></div></td>
            <td class="numeric">{_coverage_text(result.get('coverage_pct'))}</td>
            <td class="date">{_escape(result.get('financial_date'))}</td>
            <td>{_source_link(result.get('source_url'))}</td>
          </tr>""")
        table_id = "ranking" if group_index == 1 else f"ranking-{group_index}"
        rank_tables.append(
            f'<h3>{_BUCKET_LABELS[bucket]} ({len(group)})</h3>'
            f'<div class="table-scroll"><table class="rank-table" id="{table_id}"><thead><tr>'
            '<th scope="col">Rang dans la famille</th><th scope="col">Société</th><th scope="col">Phase</th>'
            '<th scope="col" class="numeric">Score heuristique</th><th scope="col" class="numeric">Couverture des données</th>'
            '<th scope="col">Date des comptes</th><th scope="col">Source</th>'
            '</tr></thead><tbody>' + "".join(rows) + '</tbody></table></div>'
        )
    ranking = "".join(rank_tables) or (
        '<p class="empty">Aucune société ne dispose actuellement d’une fiche admissible au classement.</p>'
    )
    groups = {
        "incomplete": ("Données insuffisantes ou non classées", []),
        "specialist": ("Analyse sectorielle nécessaire", []),
        "stale": ("Données trop anciennes", []),
    }
    for index, result in enumerate(other, len(ranked) + 1):
        status = result.get("status")
        group = "specialist" if status == "specialist_review" else "stale" if status == "stale_data" else "incomplete"
        groups[group][1].append((index, result))
    unranked_parts = []
    for heading, records in groups.values():
        if not records:
            continue
        entries = []
        for index, result in records:
            phase = _mapping(result.get("phase"))
            entries.append(f"""
              <article class="queue-card" data-result data-search="{_search_attr(result)}">
                <a href="#company-{index}">{_escape(result.get('symbol'))}</a> · {_escape(result.get('name'))}
                <p>{html.escape(_status_label(result))} · Couverture des données : {_coverage_text(result.get('coverage_pct'))}</p>
                <p class="muted">Comptes : {_escape(result.get('financial_date'))}</p>
                <p>{_escape(phase.get('reason'))}</p>
              </article>""")
        unranked_parts.append(f'<h3 class="queue-title">{heading} ({len(records)})</h3><div class="queue-grid">' + "".join(entries) + "</div>")
    unranked_html = (
        '<section class="section" aria-labelledby="outside-title"><h2 id="outside-title">Dossiers hors classement</h2>'
        '<p class="section-lead">Ces sociétés restent consultables. Leurs données ou leur activité demandent un examen complémentaire.</p>'
        + "".join(unranked_parts) + '</section>' if unranked_parts else ""
    )
    detail_html = "".join(_company_detail(result, index) for index, result in enumerate(ordered, 1))
    notes = _items(summary.get("notes"))
    errors = _items(summary.get("errors"))
    notes_html = ""
    if notes or errors:
        notes_html = '<section class="section notes"><h2>Notes de collecte</h2>'
        if notes:
            notes_html += _list_html(notes, "")
        if errors:
            error_texts = []
            for error in errors:
                if isinstance(error, Mapping):
                    message = error.get("error", error.get("message"))
                    error_texts.append(
                        f"{_value_text(error.get('symbol'))} : {_value_text(message)}"
                        if message is not None else _value_text(error)
                    )
                else:
                    error_texts.append(error)
            notes_html += '<h3>Échecs signalés</h3>' + _list_html(error_texts, "")
        notes_html += '</section>'
    mode = (
        "Démonstration synthétique" if all_synthetic else "Recherche avec sept rôles spécialisés" if research_records
        else "Démonstration technique" if demo else "Recherche sur données collectées"
    )
    header_description = (
        "Des décisions de recherche expliquées par sept analyses spécialisées, leurs sources, leurs réserves et les contrôles du décideur."
        if research_records else "Un classement explicable pour orienter la recherche : phase de développement, situation financière et valorisation disponible."
    )
    run_id = f" · Exécution {_escape(summary.get('run_id'))}" if summary.get("run_id") else ""
    return f"""<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="referrer" content="no-referrer">
  <title>Radar actions — Rapport de recherche</title>
  <style>{_CSS}{_RESEARCH_CSS if research_records else ''}</style>
</head>
<body><main>
  <header class="masthead">
    <div class="eyebrow">Radar actions · {mode}</div>
    <h1>Des sociétés à examiner,<br>des critères à vérifier.</h1>
    <p>{header_description}</p>
    <p class="meta">Rapport généré le {_escape(summary.get('generated_at'))}{run_id}</p>
  </header>
  {banner}
  {search_html if research_records else ''}
  {research_html}
  <div class="stats">{stats}</div>
  <div class="run-meta">{run_meta}</div>
  <section class="section method" aria-labelledby="method-title">
    <h2 id="method-title">Lire ce rapport</h2>
    <p>Le <strong>score heuristique</strong> résume les règles du moteur. Il ne représente ni une probabilité de gain ni une prévision de rendement.
       Le détail des contrôles figure dans chaque fiche.</p>
    <p>La <strong>couverture des données</strong> indique leur disponibilité pour l’analyse. Elle ne mesure pas les chances de réussite.
       Les dates des comptes et de récupération doivent être vérifiées société par société.</p>
    <p>Ce rapport sert à approfondir des pistes. Il ne déclenche aucun achat et aucun ordre de bourse.</p>
  </section>
  {'' if research_records else search_html}
  <section class="section" aria-labelledby="rank-title">
    <h2 id="rank-title">Classements par famille de développement</h2>
    <p class="section-lead">Chaque famille a ses propres critères de pondération. Les rangs repartent de 1 dans chaque famille,
      par score décroissant. Les scores de familles différentes ne constituent pas un classement commun.</p>
    {ranking}
  </section>
  {unranked_html}
  <section class="section" aria-labelledby="detail-title">
    <h2 id="detail-title">Fiches et justification</h2>
    <p class="section-lead">Ouvrir une société pour voir les mesures disponibles, les contrôles, les points favorables et les limites.</p>
    {detail_html or '<p class="empty">Aucune fiche de société disponible.</p>'}
  </section>
  {notes_html}
  <footer class="footer">Rapport autonome : aucun script, police ou graphique externe. Les liens de source s’ouvrent uniquement à votre demande.
    Exports de cette exécution : <a href="report.csv">CSV</a> · <a href="results.json">JSON</a>.</footer>
</main><script>{_SCRIPT}</script></body></html>"""


_CSV_COLUMNS = [
    "symbol", "name", "country", "sector", "status", "score", "coverage_pct",
    "ranking_bucket", "confidence", "phase_id", "phase_name", "phase_reason", "phase_confidence",
    "profit_metric", "financial_date", "financial_currency", "quote_currency", "provider_updated_at",
    "retrieved_at", "source_url", "strengths", "risks", "metrics_json",
    "valuation_json", "checks_json",
]

_RESEARCH_CSV_COLUMNS = [
    "research_version", "research_as_of", "data_kind", "backend_requested", "execution_mode",
    "research_action", "research_scope", "decision_method", "decision_summary",
    "research_quality_level", "research_coverage_pct", "analyst_roles_present",
    "analyst_rules_completed", "analyst_ollama_completed", "llm_requested", "llm_model",
    "llm_calls", "llm_successes", "llm_failures", "research_json",
]


def _research_csv_fields(research: Mapping) -> dict[str, Any]:
    if not research:
        return {key: None for key in _RESEARCH_CSV_COLUMNS}
    decision = _mapping(research.get("decision"))
    quality = _mapping(research.get("quality"))
    llm = _mapping(research.get("llm"))
    counts = _execution_counts(research)
    return {
        "research_version": research.get("version"),
        "research_as_of": research.get("as_of"),
        "data_kind": research.get("data_kind"),
        "backend_requested": research.get("backend_requested"),
        "execution_mode": research.get("execution_mode"),
        "research_action": decision.get("action"),
        "research_scope": decision.get("scope"),
        "decision_method": decision.get("method"),
        "decision_summary": decision.get("summary"),
        "research_quality_level": quality.get("level"),
        "research_coverage_pct": quality.get("coverage_pct"),
        "analyst_roles_present": counts["roles"],
        "analyst_rules_completed": counts["rules"],
        "analyst_ollama_completed": counts["ollama"],
        "llm_requested": llm.get("requested"), "llm_model": llm.get("model"),
        "llm_calls": llm.get("calls"), "llm_successes": llm.get("successes"),
        "llm_failures": llm.get("failures"),
        "research_json": json.dumps(_sanitize(research), ensure_ascii=False, allow_nan=False),
    }


def _csv_cell(value: Any) -> str:
    """Prevent formula execution, including after leading whitespace."""
    if value is None:
        return ""
    if isinstance(value, float) and not math.isfinite(value):
        return ""
    text = str(value)
    if text.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


def write_reports(results: list[dict], summary: dict, output_dir: Path | str) -> dict[str, str]:
    """Write HTML, formula-safe CSV and strict JSON; return absolute paths.

    Input objects are never mutated. Missing fields remain visibly unavailable;
    numeric values are never inferred from another company or from the score.
    Files use fixed names within ``output_dir`` so a scheduled run may refresh
    its latest report. Callers wanting history can pass a run-specific directory.
    """
    destination = Path(output_dir).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    summary = dict(_mapping(summary))
    ranked, other = _ranked_and_other(results)
    ordered = ranked + other
    has_research = any(_mapping(result.get("research")) for result in ordered)
    csv_columns = _CSV_COLUMNS + (_RESEARCH_CSV_COLUMNS if has_research else [])
    paths = {
        "html": destination / "report.html",
        "csv": destination / "report.csv",
        "json": destination / "results.json",
    }
    paths["html"].write_text(_render_html(ordered, summary), encoding="utf-8")
    paths["json"].write_text(
        json.dumps(_sanitize({"summary": summary, "results": ordered}), ensure_ascii=False,
                   indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    with paths["csv"].open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=csv_columns)
        writer.writeheader()
        for result in ordered:
            phase = _mapping(result.get("phase"))
            row = {key: result.get(key) for key in _CSV_COLUMNS}
            row.update({
                "phase_id": phase.get("id"),
                "phase_name": phase.get("name"),
                "phase_reason": phase.get("reason"),
                "phase_confidence": phase.get("confidence"),
                "ranking_bucket": _bucket(result),
                "financial_currency": result.get("financial_currency", result.get("currency")),
                "profit_metric": phase.get("profit_metric"),
                "strengths": " | ".join(str(item) for item in _items(result.get("strengths"))),
                "risks": " | ".join(str(item) for item in _items(result.get("risks"))),
                "metrics_json": json.dumps(_sanitize(_mapping(result.get("metrics"))), ensure_ascii=False, allow_nan=False),
                "valuation_json": json.dumps(_sanitize(_mapping(result.get("valuation"))), ensure_ascii=False, allow_nan=False),
                "checks_json": json.dumps(_sanitize(_items(result.get("checks"))), ensure_ascii=False, allow_nan=False),
            })
            if has_research:
                row.update(_research_csv_fields(_mapping(result.get("research"))))
            writer.writerow({key: _csv_cell(value) for key, value in row.items()})
    return {kind: str(path) for kind, path in paths.items()}


def _short_plain(value: Any, maximum: int = 160) -> str:
    return _value_text(value).replace("\n", " ").replace("\r", " ")[:maximum]


def _bounded_alert(lines: list[str]) -> str:
    rendered = "\n".join(lines)
    if len(rendered) > 3500:
        rendered = rendered[:3460].rsplit("\n", 1)[0] + "\n… Voir le rapport pour la suite."
    return rendered


def _render_research_alert(ordered: list[dict], summary: Mapping) -> str:
    records = [result for result in ordered if _mapping(result.get("research"))]
    lines = ["RADAR ACTIONS — DÉCISIONS DE RECHERCHE"]
    if any(_mapping(result.get("research")).get("data_kind") == "synthetic" for result in records):
        lines.append("DÉMONSTRATION SYNTHÉTIQUE présente — chiffres de test, aucun résultat de marché ; aucune sélection mondiale.")
    elif summary.get("mode") == "demo":
        lines.append("TEST TECHNIQUE — univers limité à Apple, Amazon et Tesla ; aucune sélection mondiale.")
    else:
        lines.append("Dossiers fournis : leur présence ne garantit ni vérification ni actualité. Couverture mondiale non établie.")
    lines.extend([
        "Recherche uniquement. Score heuristique ≠ probabilité de gain. Couverture des données ≠ chance de réussite. Aucun ordre envoyé.",
        "Règles = analyses déterministes. L’exécution IA est comptée seulement pour les rapports terminés via Ollama.",
        f"Rapport : {_short_plain(summary.get('generated_at'), 80)}.",
    ])
    counts = {action: 0 for action in _DECISION_LABELS}
    for result in records:
        action = _decision_action(_mapping(result.get("research")))
        if action in counts:
            counts[action] += 1
    lines.append(" ; ".join(f"{_DECISION_LABELS[action]} : {count}" for action, count in counts.items()) + ".")
    lines.append(f"Dossiers de recherche : {len(records)} ; fiches financières seules : {len(ordered) - len(records)}.")
    requested_top = _number(summary.get("top_n"))
    top_n = max(0, min(10, int(requested_top))) if requested_top is not None else 5
    selected = [result for result in records if _decision_action(_mapping(result.get("research"))) in ("shortlist", "watch")]
    selected.sort(key=lambda result: (
        0 if _decision_action(_mapping(result.get("research"))) == "shortlist" else 1,
        str(result.get("symbol", "")).casefold(),
    ))
    if not selected:
        lines.extend(["", "Aucun dossier à étudier ou à surveiller dans les décisions disponibles."])
    for result in selected[:top_n]:
        research = _mapping(result.get("research"))
        decision = _mapping(research.get("decision"))
        quality = _mapping(research.get("quality"))
        execution = _execution_counts(research)
        lines.extend([
            "", f"{_short_plain(result.get('symbol'), 40)} — {_DECISION_LABELS[_decision_action(research)]}",
            _short_plain(decision.get("summary"), 160),
            f"Couverture du dossier : {_coverage_text(quality.get('coverage_pct'))} ; analyses : {execution['rules']} règles, {execution['ollama']} Ollama, {execution['failed']} échec(s).",
            f"Comptes : {_short_plain(result.get('financial_date'), 40)} ; analyse : {_short_plain(research.get('as_of'), 40)}.",
        ])
    return _bounded_alert(lines)


def render_alert(results: list[dict], summary: dict) -> str:
    """Return a French plain-text summary (at most 3,500 chars), without sending it.

    This string does not require Telegram HTML/Markdown parse mode. Consumers
    must send it as plain text if they later enable a messaging integration.
    """
    summary = dict(_mapping(summary))
    ranked, other = _ranked_and_other(results)
    if any(_mapping(result.get("research")) for result in ranked + other):
        return _render_research_alert(ranked + other, summary)
    demo = summary.get("mode") == "demo"
    lines = ["RADAR ACTIONS — RECHERCHE"]
    if demo:
        lines.append("TEST TECHNIQUE — univers limité à Apple, Amazon et Tesla ; aucune sélection mondiale.")
    else:
        lines.append("Périmètre : titres effectivement collectés, selon l’univers configuré.")
    lines.extend([
        "Score heuristique ≠ probabilité de gain. Couverture des données ≠ chance de réussite. Aucun ordre envoyé.",
        f"Rapport : {_value_text(summary.get('generated_at'))[:80]}",
        f"Fiches : {len(ranked) + len(other)} ; classées : {len(ranked)} ; hors classement : {len(other)}.",
        f"Univers déclaré : {_value_text(summary.get('universe_total'))[:30]} ; reste à parcourir : {_value_text(summary.get('remaining_count'))[:30]}.",
        "",
    ])
    requested_top = _number(summary.get("top_n"))
    top_n = max(0, min(10, int(requested_top))) if requested_top is not None else 5
    if not ranked:
        lines.append("Aucun dossier actuellement admissible au classement.")
    groups = _rank_groups(ranked)
    selected = {bucket: [] for bucket, _ in groups}
    count = 0
    # Take one candidate from each family before taking the next candidate;
    # one well-populated family must not conceal all the others in the alert.
    for rank_index in range(top_n):
        for bucket, entries in groups:
            if count >= top_n:
                break
            if rank_index < len(entries):
                selected[bucket].append((rank_index + 1, entries[rank_index][1]))
                count += 1
    if count:
        lines.append("Sélections par famille ; aucun classement commun entre familles.")
    for bucket, entries in selected.items():
        if not entries:
            continue
        lines.extend(["", _BUCKET_LABELS[bucket]])
        for index, result in entries:
            phase = _mapping(result.get("phase"))
            symbol = _value_text(result.get("symbol")).replace("\n", " ").replace("\r", " ")[:40]
            name = _value_text(result.get("name")).replace("\n", " ").replace("\r", " ")[:90]
            phase_name = _value_text(phase.get("name")).replace("\n", " ").replace("\r", " ")[:90]
            lines.append(f"{index}. {symbol} — {name} : {_number_text(result.get('score'))}/100")
            lines.append(f"Phase : {phase_name} ; couverture : {_coverage_text(result.get('coverage_pct'))}.")
            lines.append(f"Comptes : {_value_text(result.get('financial_date'))[:50]}.")
    errors = _number(summary.get("error_count"))
    if errors is not None and errors > 0:
        lines.extend(["", f"Collecte : {_number_text(errors, 0)} erreur(s), à examiner dans le rapport."])
    return _bounded_alert(lines)
