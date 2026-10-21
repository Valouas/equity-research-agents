# Publication validation — 22 October 2026

The existing V0.2 source was prepared for GitHub without changing financial,
provider, model, reporting or scheduling logic.

## Checks performed

| Check | Result |
| --- | --- |
| Runtime | Python 3.12.14. Other Python versions were not executed. |
| Existing unit tests | 167 run, zero failures, zero errors, zero skipped. |
| Synthetic command | `python run_bot.py --sample --backend rules --output <temporary directory>` completed. |
| Output | HTML, CSV and JSON files produced; all four research statuses represented. |
| Network isolation | Socket connection entry points were blocked during tests and the synthetic command. |
| Source compilation | All retained Python source and test files compiled successfully without execution. |

The Ollama tests exercise the client and orchestration with simulated responses.
They are not real model inferences. No external provider calls, Telegram messages,
live scans or orders were sent.

## Packaging changes

- Added an English overview and kept the complete French guide.
- Preserved empty credential placeholders and expanded `.gitignore`.
- Removed the nested V0.1 ZIP and the source-archive checksum manifest, which would
  no longer describe the prepared tree.
- Removed the generated research workbook and raw SEC, Nasdaq, ECB and Nestlé
  snapshots. Retained catalogue sources and historical access observations.
- Kept clearly identified synthetic inputs and example reports.
- Preserved the absence of a license file; no license was selected.

The original archive remains unchanged. `VALIDATION.txt` records the earlier
6 October 2026 validation and is retained as historical documentation.

## Not established by these checks

No claim is made about live data availability, an installed local model,
worldwide fundamental coverage, investment performance or production deployment.
