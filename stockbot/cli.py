"""Scans, normalized file inputs, and optional local analytical agents."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .engine import validate_config
from .inputs import load_companies, sample_companies
from .llm import LLMError
from .multiagent import agent_settings, analyse_research, expire_cached_research
from .provider import AccessDenied, BudgetExceeded, EODHDProvider, ProviderError
from .reporting import render_alert, write_reports
from .state import State, utc_now


ROOT = Path(__file__).resolve().parent.parent
DEMO_SYMBOLS = ["AAPL.US", "AMZN.US", "TSLA.US"]


def load_env(path: Path) -> None:
    """Petit lecteur .env : pas d'exécution, pas d'expansion de variables."""
    allowed = {"EODHD_API_TOKEN", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "STOCKBOT_OLLAMA_MODEL"}
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key, value = key.strip(), value.strip()
        if key in allowed and key not in os.environ:
            os.environ[key] = value.strip("\"'")


def load_config(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    positive = {
        "max_symbols_per_run": 3000, "api_units_per_run": 35000,
        "api_units_per_day": 90000, "cache_ttl_hours": 20,
        "refresh_universe_days": 7, "results_max_age_days": 7, "top_n": 20,
    }
    for key, default in positive.items():
        data.setdefault(key, default)
        if isinstance(data[key], bool) or not isinstance(data[key], int) or data[key] < 1:
            raise ValueError(f"Le paramètre {key} doit être un entier positif.")
    data.setdefault("min_request_interval", 0.3)
    if not isinstance(data["min_request_interval"], (float, int)) or data["min_request_interval"] < 0.1:
        raise ValueError("min_request_interval doit être au moins 0.1 seconde.")
    data.setdefault("daily_time", "23:15")
    data.setdefault("timezone", "Europe/Zurich")
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", data["daily_time"]):
        raise ValueError("daily_time doit suivre le format HH:MM, par exemple 23:15.")
    if data.get("exchanges") is not None and (
        not isinstance(data["exchanges"], list) or
        not all(isinstance(x, str) and re.fullmatch(r"[A-Za-z0-9_-]+", x) for x in data["exchanges"])
    ):
        raise ValueError("exchanges doit être null ou une liste de codes de places boursières.")
    priorities = data.get("priority_symbols", [])
    if not isinstance(priorities, list) or not all(isinstance(x, str) for x in priorities):
        raise ValueError("priority_symbols doit être une liste de symboles.")
    data.setdefault("scoring", {})
    venues = data.get("exclude_venues", [])
    if not isinstance(venues, list) or not all(isinstance(x, str) for x in venues):
        raise ValueError("exclude_venues doit être une liste de places exclues.")
    validate_config(data)
    agent_settings(data)
    return data


def valid_symbols(value: str) -> list[str]:
    items = [x.strip().upper() for x in value.split(",") if x.strip()]
    if not items or any(not re.fullmatch(r"[A-Z0-9^_-]+\.[A-Z0-9_-]+", x) for x in items):
        raise ValueError("Format attendu : CODE.BOURSE, par exemple AAPL.US,AMZN.US.")
    return list(dict.fromkeys(items))


def discovery_due(state: State, days: int) -> bool:
    value = state.get_meta("last_discovery")
    if not value or state.universe_count() == 0:
        return True
    try:
        return datetime.now(timezone.utc) - datetime.fromisoformat(value) >= timedelta(days=days)
    except ValueError:
        return True


def notify_telegram(message: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        raise ValueError("Configurer TELEGRAM_BOT_TOKEN et TELEGRAM_CHAT_ID localement pour les alertes.")
    if not re.fullmatch(r"\d+:[A-Za-z0-9_-]+", token):
        raise ValueError("Le format du jeton Telegram n'est pas valide.")
    payload = json.dumps({"chat_id": chat, "text": message[:3500],
                          "disable_web_page_preview": True}).encode("utf-8")
    request = urllib.request.Request(
        "https://api.telegram.org/bot" + token + "/sendMessage", data=payload,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            result = json.load(response)
        if not result.get("ok"):
            raise ValueError("Telegram n'a pas confirmé la remise du message.")
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        # Le texte brut de l'exception peut contenir le jeton dans une URL.
        raise ValueError("Échec de l'envoi Telegram. Vérifier la configuration et la connexion.") from None


def next_run(now: datetime, hhmm: str) -> datetime:
    hour, minute = (int(x) for x in hhmm.split(":"))
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target = (now + timedelta(days=1)).replace(hour=hour, minute=minute, second=0, microsecond=0)
    return target


def _today(config):
    try:
        return datetime.now(ZoneInfo(config["timezone"])).date()
    except ZoneInfoNotFoundError:
        raise ValueError("Fuseau horaire absent. Installer requirements.txt sur ce système.") from None


def _rules_config(config):
    data = copy.deepcopy(config)
    data.setdefault("agents", {})["backend"] = "rules"
    return data


def _apply_local_ai(results, companies, config, as_of):
    """Screen cheaply first, then run the local committee on a bounded subset."""
    settings = agent_settings(config)
    if settings["backend"] != "ollama":
        return results
    from .llm import OllamaClient
    client = OllamaClient(model=settings["model"], base_url=settings["base_url"],
                          timeout=settings["timeout_seconds"], max_calls=settings["max_calls_per_run"])
    eligible = [r for r in results if not any(not g["passed"] and g["severity"] == "block"
                                             for g in r["research"]["gates"])]
    eligible.sort(key=lambda r: (-(r.get("score") or 0), str(r.get("symbol"))))
    selected = {r["symbol"] for r in eligible[:settings["max_llm_companies"]]}
    output = []
    for result in results:
        if result["symbol"] in selected:
            print(f"Agents locaux : {result['symbol']} — analyses puis décision, jusqu'à huit appels.", flush=True)
            result = analyse_research(companies[result["symbol"]], config, as_of, llm_client=client)
        else:
            research = result["research"]
            research["backend_requested"] = "ollama"
            research["llm"].update(requested=True, model=settings["model"])
            research["decision"]["llm_status"] = "skipped"
            research["caveats"].append(
                "Analyse par règles uniquement : dossier bloqué ou hors du lot borné retenu pour les appels IA locaux.")
        output.append(result)
    return output


def _report_path(args, mode, run_id):
    chosen = getattr(args, "output", None)
    if chosen:
        return chosen / run_id if args.daemon else chosen
    return ROOT / "reports" / mode / run_id


def run_input_scan(config: dict, args: argparse.Namespace) -> int:
    as_of = _today(config)
    companies = sample_companies(as_of) if args.sample else load_companies(args.input)
    total = len(companies)
    companies = companies[:config["max_symbols_per_run"]]
    by_symbol = {c["symbol"]: c for c in companies}
    results, errors = [], []
    for company in companies:
        try:
            result = analyse_research(company, _rules_config(config), as_of)
            results.append(result)
            print(f"{company['symbol']} — {result['research']['decision']['summary']}", flush=True)
        except (ValueError, TypeError, KeyError, ArithmeticError):
            errors.append({"symbol": company["symbol"], "message": "Entrée financière incohérente : dossier non traité."})
    results = _apply_local_ai(results, by_symbol, config, as_of)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    mode = "synthetic" if all(c.get("is_synthetic") is True for c in companies) else "input"
    notes = ["Les dates du fichier restent inchangées ; la date de lecture ne rajeunit pas les comptes ou ratios.",
             "Les agents n'ouvrent pas les liens des pièces : ils analysent les extraits fournis."]
    if mode == "synthetic":
        notes.append("Exemple entièrement fictif : chiffres, sociétés et textes synthétiques, aucune sélection boursière réelle.")
    else:
        notes.append("Fichier fourni par l'utilisateur : sa provenance est décrite par ses champs et n'est pas auditée automatiquement.")
    summary = {"generated_at": utc_now(), "run_id": run_id, "mode": mode,
               "universe_total": total, "attempted_count": len(companies), "success_count": len(results),
               "error_count": len(errors), "remaining_count": total - len(companies),
               "units_used": 0, "errors": errors, "notes": notes, "top_n": config["top_n"],
               "stored_results_count": len(results), "budget_stopped": False, "access_stopped": False,
               "llm_calls": sum(r["research"]["llm"]["calls"] for r in results)}
    paths = write_reports(results, summary, _report_path(args, mode, run_id))
    for kind, path in paths.items():
        print(f"{kind.upper()} : {path}")
    if args.notify_telegram:
        notify_telegram(render_alert(results, summary))
        print("Synthèse Telegram envoyée.")
    return 0 if results else 1


def run_scan(config: dict, args: argparse.Namespace) -> int:
    if getattr(args, "sample", False) or getattr(args, "input", None):
        return run_input_scan(config, args)
    as_of = _today(config)
    mode = "demo" if args.demo else "live"
    token = "demo" if args.demo else os.environ.get("EODHD_API_TOKEN", "").strip()
    if not token:
        print("Aucune source réelle configurée. Tester les agents hors réseau : python run_bot.py --sample")
        print("Pour un scan réel, copier .env.example en .env et renseigner EODHD_API_TOKEN localement.")
        return 2
    if not args.demo and token.lower() == "demo":
        print("La clé publique demo ne permet pas une recherche mondiale. Utiliser --demo.")
        return 2
    state = State(ROOT / "data" / f"{mode}_state.sqlite")
    provider = EODHDProvider(
        token=token, cache_path=str(ROOT / "data" / f"{mode}_cache.sqlite"),
        max_units_per_run=config["api_units_per_run"],
        max_units_per_day=config["api_units_per_day"],
        min_request_interval=config["min_request_interval"],
    )
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    notes: list[str] = []
    errors: list[dict] = []
    fresh_results: list[dict] = []
    companies: dict[str, dict] = {}
    attempted = 0
    budget_stopped = False
    access_stopped = False
    requested_symbols: list[str] = []
    try:
        if args.demo:
            queue = DEMO_SYMBOLS
            state.upsert_universe([{"symbol": x} for x in queue], replace_active=True)
            notes.append("Démonstration technique sur trois sociétés américaines ; ce n'est pas une sélection mondiale.")
        elif args.symbols:
            requested_symbols = valid_symbols(args.symbols)
            state.upsert_universe([{"symbol": x} for x in requested_symbols])
            queue = state.queue_subset(requested_symbols, config["max_symbols_per_run"])
            notes.append("Univers limité aux symboles demandés explicitement pour cette exécution.")
            if len(queue) < len(requested_symbols):
                notes.append("La limite de ce cycle laisse des symboles demandés en attente ; ils sont conservés dans l'univers local.")
        else:
            scope = json.dumps({"exchanges": config.get("exchanges"), "exclude_venues": config.get("exclude_venues", [])}, sort_keys=True)
            scope_changed = state.get_meta("discovery_scope") != scope
            if args.refresh_universe or scope_changed or discovery_due(state, config["refresh_universe_days"]):
                print("Découverte des actions ordinaires sur les bourses accessibles…", flush=True)
                try:
                    universe = provider.discover(config.get("exchanges"))
                    excluded = [x.upper() for x in config.get("exclude_venues", []) if x]
                    universe = [item for item in universe if not any(
                        name in str(item.get("exchange") or "").upper() for name in excluded
                    )]
                    if not universe:
                        raise ProviderError("Aucun symbole reçu. Vérifier les droits d'accès aux données.")
                    complete = getattr(provider, "discovery_complete", False)
                    notes.extend(getattr(provider, "discovery_warnings", []))
                    state.upsert_universe(universe, replace_active=complete or scope_changed)
                    state.set_meta("discovery_scope", scope)
                    if complete:
                        state.set_meta("last_discovery", utc_now())
                except AccessDenied:
                    raise
                except ProviderError:
                    if scope_changed or state.universe_count() == 0:
                        raise
                    notes.append("Actualisation de l'univers indisponible ; reprise de la dernière liste enregistrée.")
            queue = state.queue(config["max_symbols_per_run"], config.get("priority_symbols", []))
            notes.append("Scan mondial par lots tournants ; la couverture réelle dépend des bourses accessibles et des quotas.")
        print(f"{len(queue)} titres prévus ; univers mémorisé : {state.universe_count()}.", flush=True)
        for symbol in queue:
            attempted += 1
            try:
                company = provider.fundamentals(symbol, ttl_hours=config["cache_ttl_hours"])
                result = analyse_research(company, _rules_config(config), as_of)
                companies[symbol] = company
                # Conserver les identifiants et horodatages même si le moteur s'abstient.
                for key in ("symbol", "name", "country", "sector", "source_url", "retrieved_at",
                            "financial_currency", "quote_currency", "provider_updated_at"):
                    result.setdefault(key, company.get(key))
                state.record(symbol, run_id, result)
                fresh_results.append(result)
                print(f"[{attempted}/{len(queue)}] {symbol} — {result.get('status', 'analyse enregistrée')}", flush=True)
            except AccessDenied:
                access_stopped = True
                message = "Accès aux données refusé : vérifier la clé et les droits du compte. Cycle interrompu."
                errors.append({"symbol": symbol, "message": message})
                notes.append(message)
                print(message, flush=True)
                break
            except BudgetExceeded:
                budget_stopped = True
                notes.append("Budget d'API atteint : les titres restants seront repris lors d'une prochaine exécution.")
                attempted -= 1  # Ce titre n'a pas pu être analysé.
                break
            except ProviderError:
                # Ne pas afficher corps/URL d'une réponse contenant potentiellement un jeton.
                message = "Données indisponibles, accès refusé ou réponse invalide."
                errors.append({"symbol": symbol, "message": message})
                state.fail(symbol, message)
                print(f"[{attempted}/{len(queue)}] {symbol} — {message}", flush=True)
            except (ValueError, TypeError, KeyError, ArithmeticError):
                message = "Données incohérentes ou incompatibles ; aucune note publiée pour ce titre."
                errors.append({"symbol": symbol, "message": message})
                state.fail(symbol, message)
                print(f"[{attempted}/{len(queue)}] {symbol} — {message}", flush=True)
        fresh_results = _apply_local_ai(fresh_results, companies, config, as_of)
        for result in fresh_results:
            if result["research"]["llm"]["calls"] or result["research"]["llm"]["failures"]:
                state.record(result["symbol"], run_id, result)
        results = fresh_results if args.demo or args.symbols else state.latest_results(config["results_max_age_days"])
        fresh_by_symbol = {r["symbol"]: r for r in fresh_results}
        results = [fresh_by_symbol.get(r.get("symbol"), r) for r in results]
        legacy_count = sum(not r.get("research") for r in results)
        results = [expire_cached_research(r, as_of) for r in results if r.get("research")]
        if legacy_count:
            notes.append("Des analyses antérieures sans agents sont exclues de cette synthèse ; elles seront reprises lors d'un scan.")
        summary = {
            "generated_at": utc_now(), "run_id": run_id, "mode": mode,
            "universe_total": len(DEMO_SYMBOLS) if args.demo else (len(requested_symbols) if args.symbols else state.universe_count()),
            "attempted_count": attempted, "success_count": len(fresh_results),
            "error_count": len(errors), "remaining_count": max(0, len(queue) - attempted),
            "units_used": provider.units_used, "errors": errors, "notes": notes,
            "top_n": config["top_n"], "stored_results_count": len(results),
            "budget_stopped": budget_stopped,
            "access_stopped": access_stopped,
            "results_max_age_days": config["results_max_age_days"],
        }
        if args.symbols:
            summary["remaining_count"] = max(0, len(requested_symbols) - attempted)
        if not args.demo and not args.symbols:
            summary["remaining_count"] = max(0, state.universe_count() - len(results))
            notes.append(f"Le rapport rassemble les dernières analyses récupérées depuis au plus {config['results_max_age_days']} jours ; chaque titre conserve sa date.")
        paths = write_reports(results, summary, _report_path(args, mode, run_id))
        state.set_meta("last_report", json.dumps(paths))
        for kind, path in paths.items():
            print(f"{kind.upper()} : {path}")
        if args.notify_telegram and not access_stopped:
            message = render_alert(results, summary)
            fingerprint = hashlib.sha256(message.encode("utf-8")).hexdigest()
            if fingerprint != state.get_meta("last_alert"):
                notify_telegram(message)
                state.set_meta("last_alert", fingerprint)
                print("Synthèse Telegram envoyée.")
        return 2 if access_stopped else (0 if fresh_results else 1)
    finally:
        state.close()
        close = getattr(provider, "close", None)
        if callable(close):
            close()


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description="Scanner fondamental mondial pour l'investissement à long terme.")
    mode = command.add_mutually_exclusive_group()
    mode.add_argument("--sample", action="store_true", help="Quatre dossiers fictifs, générés à la date du jour, sans source réseau.")
    mode.add_argument("--demo", action="store_true", help="Test réel sur Apple, Amazon et Tesla, sans clé personnelle.")
    mode.add_argument("--once", action="store_true", help="Un cycle de recherche réelle (option par défaut).")
    mode.add_argument("--daemon", action="store_true", help="Un scan immédiat, puis un scan quotidien à l'heure configurée.")
    command.add_argument("--config", type=Path, default=ROOT / "config.json")
    command.add_argument("--input", type=Path, help="Fichier JSON normalisé de sociétés et d'extraits datés, sans clé de données.")
    command.add_argument("--backend", choices=("rules", "ollama"), help="Analyses par règles ou modèle local Ollama.")
    command.add_argument("--model", help="Nom exact d'un modèle déjà installé dans le serveur Ollama local.")
    command.add_argument("--output", type=Path, help="Dossier des rapports ; en mode quotidien, un sous-dossier par cycle.")
    command.add_argument("--symbols", help="Univers explicite séparé par des virgules : AAPL.US,AMZN.US")
    command.add_argument("--refresh-universe", action="store_true", help="Actualiser la liste de bourses et de titres accessibles.")
    command.add_argument("--limit", type=int, help="Limiter le nombre de titres évalués pendant ce cycle.")
    command.add_argument("--notify-telegram", action="store_true", help="Activer volontairement les alertes avec les identifiants locaux.")
    return command


def main() -> int:
    args = parser().parse_args()
    load_env(ROOT / ".env")
    try:
        config = load_config(args.config)
        config.setdefault("agents", {})
        if args.backend:
            config["agents"]["backend"] = args.backend
        model = args.model or os.environ.get("STOCKBOT_OLLAMA_MODEL", "").strip()
        if model:
            config["agents"]["model"] = model
        settings = agent_settings(config)
        if settings["backend"] == "ollama":
            from .llm import OllamaClient
            # Constructor validates settings without connecting or installing anything.
            OllamaClient(model=settings["model"], base_url=settings["base_url"],
                         timeout=settings["timeout_seconds"], max_calls=settings["max_calls_per_run"])
        if args.input and (args.demo or args.sample or args.symbols or args.refresh_universe):
            raise ValueError("--input s'utilise sans --demo, --sample, --symbols ni --refresh-universe.")
        if args.sample and (args.symbols or args.refresh_universe):
            raise ValueError("--sample utilise uniquement les quatre sociétés fictives.")
        if args.demo and args.symbols:
            raise ValueError("--demo utilise uniquement les trois valeurs de démonstration.")
        if args.limit is not None:
            if args.limit < 1:
                raise ValueError("--limit doit être positif.")
            config["max_symbols_per_run"] = args.limit
        if not args.daemon:
            return run_scan(config, args)
        try:
            zone = ZoneInfo(config["timezone"])
        except ZoneInfoNotFoundError:
            raise ValueError("Fuseau horaire absent. Sur Windows : python -m pip install -r requirements.txt") from None
        if not args.input and not os.environ.get("EODHD_API_TOKEN", "").strip():
            print("Le mode autonome nécessite un fichier --input régulièrement actualisé ou une clé EODHD locale.")
            return 2
        print(f"Mode autonome : un scan maintenant, puis chaque jour à {config['daily_time']} ({config['timezone']}).")
        while True:
            try:
                run_scan(config, args)
            except (ProviderError, OSError):
                print("Le cycle n'a pas pu aboutir. Les résultats existants sont conservés.", flush=True)
            target = next_run(datetime.now(zone), config["daily_time"])
            print(f"Prochain scan : {target.isoformat()} ; Ctrl+C pour arrêter.", flush=True)
            while datetime.now(zone) < target:
                seconds = (target - datetime.now(zone)).total_seconds()
                time.sleep(min(30, max(0.1, seconds)))
    except KeyboardInterrupt:
        print("\nArrêt demandé. Historique conservé.")
        return 0
    except (ValueError, FileNotFoundError, LLMError) as exc:
        print(f"Configuration : {exc}", file=sys.stderr)
        return 2
    except ProviderError:
        print("L'accès aux données a échoué. Vérifier la connexion, la clé et les droits de l'abonnement.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
