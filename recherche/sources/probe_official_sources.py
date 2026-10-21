"""Four conservative, unauthenticated public-data probes; no retries/bypass."""
import csv
import io
import json
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
USER_AGENT = "StockResearchBot/0.1 (public-data evaluation; no contact address configured)"
ENDPOINTS = [
    ("sec_companyfacts_apple", "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json"),
    ("sec_submissions_apple", "https://data.sec.gov/submissions/CIK0000320193.json"),
    ("nasdaq_symbols", "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"),
    ("ecb_usd_chf", "https://data-api.ecb.europa.eu/service/data/EXR/D.USD+CHF.EUR.SP00.A?lastNObservations=2&format=csvdata"),
]
report = {"tested_at_utc": datetime.now(timezone.utc).isoformat(), "user_agent": USER_AGENT, "max_requests_per_second": 1.5, "results": []}
last_request = 0.0
blocked_hosts = set()
for name, url in ENDPOINTS:
    host = url.split("/")[2]
    result = {"name": name, "url": url}
    if host in blocked_hosts:
        result["skipped"] = "Host returned 403 on preceding probe; no repeated access or bypass."
        report["results"].append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
        continue
    pause = 0.67 - (time.monotonic() - last_request)
    if pause > 0:
        time.sleep(pause)
    last_request = time.monotonic()
    try:
        req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json,text/csv,text/plain,*/*"})
        with urlopen(req, timeout=25) as response:
            data = response.read(20 * 1024 * 1024 + 1)
            result.update(status=response.status, content_type=response.headers.get("Content-Type"), bytes=len(data), server_date=response.headers.get("Date"))
        if len(data) > 20 * 1024 * 1024:
            result["error"] = "Response exceeds 20 MiB local probe cap; not parsed."
        else:
            (ROOT / (name + (".json" if name.startswith("sec_") else ".txt"))).write_bytes(data)
            if name == "sec_companyfacts_apple":
                payload = json.loads(data)
                result.update(entity=payload.get("entityName"), namespaces=list(payload.get("facts", {})), tags={key: len(value) for key, value in payload.get("facts", {}).items()})
                selected = {}
                for taxonomy, key in [
                    ("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax"),
                    ("us-gaap", "NetIncomeLoss"),
                    ("us-gaap", "CommonStockSharesOutstanding"),
                    ("dei", "EntityCommonStockSharesOutstanding"),
                    ("us-gaap", "WeightedAverageNumberOfDilutedSharesOutstanding"),
                    ("us-gaap", "CommonStockDividendsPerShareCashPaid"),
                    ("us-gaap", "PaymentsOfDividendsCommonStock"),
                    ("us-gaap", "PaymentsOfDividends"),
                ]:
                    concept = payload.get("facts", {}).get(taxonomy, {}).get(key)
                    if not concept:
                        selected[taxonomy + ":" + key] = None
                        continue
                    units = concept.get("units", {})
                    picked = []
                    for unit, facts in units.items():
                        annual = [row for row in facts if row.get("form") in {"10-K", "20-F", "40-F"}]
                        # Retain the latest examples, with full period/filing dates.
                        ordered = sorted(annual, key=lambda row: (row.get("end", ""), row.get("filed", "")))
                        picked.append({"unit": unit, "annual_fact_count": len(annual), "latest_two": ordered[-2:]})
                    selected[taxonomy + ":" + key] = picked
                result["selected_concepts"] = selected
            elif name == "sec_submissions_apple":
                payload = json.loads(data)
                recent = payload.get("filings", {}).get("recent", {})
                result.update(entity=payload.get("name"), tickers=payload.get("tickers"), exchanges=payload.get("exchanges"), recent_forms=dict(Counter(recent.get("form", []))), recent_filing_count=len(recent.get("accessionNumber", [])), older_files=payload.get("filings", {}).get("files"))
            elif name == "nasdaq_symbols":
                text = data.decode("utf-8-sig")
                lines = text.splitlines()
                records = list(csv.DictReader([line for line in lines if not line.startswith("File Creation Time:")], delimiter="|"))
                result.update(rows=len(records), columns=list(records[0]) if records else [], etf_count=sum(row.get("ETF") == "Y" for row in records), test_issue_count=sum(row.get("Test Issue") == "Y" for row in records), timestamp=next((line for line in lines if line.startswith("File Creation Time:")), None), apple=next((row for row in records if row.get("Symbol") == "AAPL"), None))
            elif name == "ecb_usd_chf":
                records = list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))
                result["observations"] = [{key: row.get(key) for key in ("KEY", "TIME_PERIOD", "OBS_VALUE", "CURRENCY", "CURRENCY_DENOM", "UNIT", "UNIT_MULT")} for row in records]
                result["rows"] = len(records)
    except HTTPError as error:
        result.update(status=error.code, error="HTTP refusal/error; no retry.")
        if error.code == 403:
            blocked_hosts.add(host)
    except (URLError, OSError, ValueError) as error:
        result.update(error_type=type(error).__name__, error=str(error)[:250])
    result["elapsed_seconds"] = round(time.monotonic() - last_request, 3)
    report["results"].append(result)
    print(json.dumps(result, ensure_ascii=False), flush=True)
(ROOT / "probe_results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
