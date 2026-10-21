# Equity Research Agents

**A Python research assistant that turns dated company data into explainable research priorities.**

Seven specialist roles examine each company. A research coordinator combines their evidence, keeps unresolved objections visible, and applies deterministic eligibility checks. The output is a research status: `shortlist`, `watch`, `avoid`, or `abstain`.

The default mode uses rules and runs offline with synthetic examples. An optional local Ollama backend can produce structured analyst reports. Decisions remain `research_only`: the project has no brokerage integration or order execution.

[Guide complet en français](README.fr.md) · [Validation](docs/VALIDATION_GITHUB.md) · [Development notes](docs/REPRISE_CODEX.md)

## What is implemented

| Component | Current behavior |
| --- | --- |
| Financial engine | Annual development phases, financial metrics, explicit scoring rules and eligibility checks. |
| Seven research roles | Data quality, fundamentals, growth, valuation, risk, supplied documents and counter-analysis. |
| Research coordinator | Preserves evidence and objections, applies mandatory controls, and can abstain. |
| Structured evidence | References are scoped to each company; dates, currencies, missing values and source provenance remain visible. |
| Input adapters | Normalized JSON, a synthetic scenario, and an optional EODHD provider with caching and request budgets. |
| Optional local model | Ollama client with loopback-only endpoints, structured-response validation and call budgets. |
| Reports and history | French HTML, CSV and JSON reports; SQLite state for provider scans; optional daily execution and Telegram notifications. |

The roles are deterministic in the default backend. When Ollama is enabled, they run sequentially and may share one model. Their agreement is not independent evidence or a probability of investment success.

## Quickstart: no data account required

Python 3.10 or newer is the intended target. Validation for this publication used **Python 3.12.14**.

```bash
python -m venv .venv
# Linux/macOS
source .venv/bin/activate
# Windows PowerShell: .\.venv\Scripts\Activate.ps1

python -m pip install -r requirements.txt
python run_bot.py --sample --backend rules --output reports/sample
```

Open `reports/sample/report.html`. The same directory contains CSV and JSON exports. After dependency installation, this command requires no network, API key or local model. It uses four fictitious companies and illustrates all four research statuses. The supplied [example report](example_report/report.html) also uses entirely synthetic data and rule-based analysis.

The core uses the Python standard library. `requirements.txt` installs time-zone data on Windows. The separate research-catalog builder optionally requires `openpyxl`.

## Analyze supplied company data

```bash
python run_bot.py --input examples/companies_synthetic.json --backend rules
```

The example JSON documents the expected company, annual-account, valuation and document fields. Its dates are fixed; running it later can correctly trigger freshness-related abstentions. `--sample` regenerates fictitious dates relative to the run date.

For real inputs, use the normalized schema described in the [French guide](README.fr.md), preserve source and publication dates, and represent unknown values as `null`. Document URLs are references; the program does not automatically download their contents.

## Optional integrations

Copy `.env.example` to `.env` and configure only the integrations you intend to use. The template contains no credentials.

| Integration | Activation and scope |
| --- | --- |
| EODHD | Set `EODHD_API_TOKEN`; a live scan requires network access and suitable data entitlements. Provider coverage and costs depend on the account. |
| Ollama | Install a suitable local model separately, configure the server for local use, then pass `--backend ollama --model YOUR_LOCAL_MODEL`. No model weights are bundled. |
| Telegram | Set the two Telegram variables and explicitly pass `--notify-telegram`. Notifications are off by default. |
| Daily execution | `--daemon` runs a first cycle, then follows `config.json`. The process must remain running. Re-reading an input file does not refresh its data. |

The detailed provider, model and scheduling instructions are in [README.fr.md](README.fr.md).

## Architecture

| Path | Responsibility |
| --- | --- |
| `stockbot/engine.py` | Financial metrics, phases, scoring and eligibility. |
| `stockbot/multiagent.py` | Evidence registry, analyst roles and research decisions. |
| `stockbot/llm.py` | Optional local model client and response validation. |
| `stockbot/inputs.py`, `stockbot/provider.py` | Normalized inputs and optional provider collection. |
| `stockbot/cli.py`, `stockbot/state.py` | Execution, budgets, scheduling and persistence. |
| `stockbot/reporting.py` | HTML, CSV and JSON exports. |
| `tests/` | Existing financial, input, protocol and reporting checks. |
| `recherche/` | Dated research catalogues and collection experiments, separate from production adapters. |

## Validation and current limits

```bash
python -m unittest discover -s tests
```

On 22 October 2026, **167 existing tests passed** and the synthetic CLI example completed with outbound connections blocked. The example produced HTML, CSV and JSON reports and all four expected research statuses. See [the validation record](docs/VALIDATION_GITHUB.md).

The Ollama tests use simulated responses; a real model's analytical quality has not been validated. No live provider scan, worldwide coverage assessment, investment-return backtest or real-money execution was performed for this publication. The free-data catalog is research material, not a collection of fully integrated adapters. Scores are heuristic; sector-specific models remain necessary for banks, insurers, REITs and other financial businesses.

## Provenance and licensing

This repository packages the existing V0.2 project. The financial phase rules cite [Stock Simplifier's written phase check](https://stocksimplifier.com/phase-check); the implementation and scoring are independent, and no affiliation is claimed. The original source archive contained no license file. No new license has been added.
