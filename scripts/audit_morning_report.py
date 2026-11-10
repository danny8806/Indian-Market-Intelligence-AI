"""Score a frozen morning report against official NSE open-to-close prices.

Research-only. Reads a report JSON captured from PostgreSQL and never writes a
trade signal or touches a broker. Fails closed on missing or invalid prices.
Run after the session has closed (>=16:00 IST). The report JSON can be captured
with ``ops/news-stack/verify-morning-report.sh`` on the VPS.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from learning.feedback import evaluate  # noqa: E402
from scripts.validate_signals import validate  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("--session-date", required=True)
    parser.add_argument("--prices-csv", type=Path,
                        help="Optional local OHLCV CSV; default is official NSE EOD")
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    day = date.fromisoformat(args.session_date)
    now = datetime.now(IST)
    if now.date() == day and now.hour < 16:
        print(json.dumps({"status": "SESSION_NOT_CLOSED"}))
        return 2
    report = json.loads(args.report.read_text(encoding="utf-8-sig"))
    validate(report, expected_date=day.isoformat())
    if report["status"] != "READY":
        print(json.dumps({"status": "NOT_READY", "report_status": report["status"]}))
        return 0

    if args.prices_csv:
        from learning.candidate_outcomes import price_csv_reader
        reader = price_csv_reader(args.prices_csv)
        source = "USER_SUPPLIED_CSV_NOT_EXCHANGE_VERIFIED"
    else:
        from learning.nse_bhavcopy import session_reader
        reader, official_url = session_reader(day)
        source = f"NSE_EOD_OFFICIAL_CSV:{official_url}; corporate actions NOT verified"

    rows, errors = [], {}
    for signal in report["signals"]:
        try:
            rows.append(evaluate(signal, day, reader(signal["symbol"], day)))
        except Exception as exc:
            errors[signal["symbol"]] = f"{type(exc).__name__}: {str(exc)[:180]}"
    result = {
        "session": day.isoformat(),
        "status": "COMPLETE" if len(rows) == len(report["signals"]) else "PARTIAL",
        "price_source": source,
        "signals_expected": len(report["signals"]),
        "priced": len(rows),
        "errors": errors,
        "note": ("Research audit only. Open-price execution is hypothetical and "
                 "open-to-close movement is not executable P&L."),
    }
    if rows:
        result["per_signal"] = [
            {"symbol": r["symbol"], "side": r["side"], "rank": r["rank"],
             "open_to_close_pct": r["open_to_close_pct"],
             "side_adjusted_pct": r["trade_return_pct"], "won": r["won"]}
            for r in sorted(rows, key=lambda r: (r["side"], r["rank"]))
        ]
        result["wins"] = sum(r["won"] for r in rows)
        result["losses"] = sum(r["trade_return_pct"] < 0 for r in rows)
        result["equal_weight_side_adjusted_pct"] = round(
            sum(r["trade_return_pct"] for r in rows) / len(rows), 5)
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    print(text, end="")
    if args.json_out:
        args.json_out.write_text(text, encoding="utf-8")
    return 0 if result["status"] == "COMPLETE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
