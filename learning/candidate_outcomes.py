"""Label entire frozen pre-market candidate universe with actual open-to-close moves.

Research-only, does NOT place trades, simulate fills, or promote any model.
Requires a real immutable before-09:00 snapshot; missing prices fail closed.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import tempfile
from collections import defaultdict
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from learning.feedback import evaluate, yahoo_bars
from news_collector.candidates import SCHEMA as SNAPSHOT_SCHEMA, aware

ROOT = Path(__file__).resolve().parents[1]
IST = ZoneInfo("Asia/Kolkata")
FIELDS = [
    "date", "symbol", "snapshot_sha256", "snapshot_as_of", "first_seen_at",
    "articles", "official_filing_count", "material_event_count", "review_priority",
    "positive_yoy_metrics", "negative_yoy_metrics", "conflicting_metrics",
    "categories_json", "headlines_json", "news_age_hours",
    "price_source", "previous_close", "open", "high", "low", "close", "volume",
    "open_to_close_pct", "up", "direction",
]


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix=".out-", delete=False) as f:
        name = f.name
        f.write(content)
    os.replace(name, path)


def load_snapshot(path: Path, session: date) -> tuple[dict, str]:
    raw = path.read_bytes()
    data = json.loads(raw)
    cutoff = aware(data.get("cutoff_exclusive"))
    first = aware(data.get("as_of"))
    if (data.get("schema_version") != SNAPSHOT_SCHEMA
            or data.get("session_date") != session.isoformat()
            or data.get("data_mode") != "FROZEN_PREMARKET"
            or data.get("execution_enabled") is not False or not first or not cutoff
            or first >= cutoff or first.date() != session
            or first.time() < time(8, 50)
            or data.get("company_count") != len(data.get("candidates", []))
            or not data.get("universe_status", "").startswith("OFFICIAL_FETCH:")):
        raise ValueError("Snapshot is not a validated immutable premarket candidate pool")
    symbols = [c["symbol"] for c in data["candidates"]]
    if not symbols or len(set(symbols)) != len(symbols):
        raise ValueError("Duplicate or empty frozen candidate universe")
    return data, hashlib.sha256(raw).hexdigest()


def candidate_outcome(candidate: dict, *, session: date, snapshot: dict, snap_hash: str,
                      price_reader, price_source: str) -> dict:
    probe = {
        "symbol": candidate["symbol"], "side": "LONG",
        "rank": 1, "reason": "Point-in-time full-candidate universe audit",
        "news_summary": "Automatic candidate outcome labeling, never a trade signal",
        "first_available_at": candidate["first_seen_at"],
        "sources": [{"url": u, "title": "Research source", "published_at": candidate["first_seen_at"]}
                    for u in candidate.get("source_urls", [])[:1]],
    }
    observation = evaluate(probe, session, price_reader(candidate["symbol"], session))
    features = candidate.get("evidence_summary") or {}
    actual = observation["open_to_close_pct"]
    return {
        "date": session.isoformat(), "symbol": candidate["symbol"],
        "snapshot_sha256": snap_hash, "snapshot_as_of": snapshot["as_of"],
        "first_seen_at": candidate["first_seen_at"],
        "articles": int(candidate["articles"]),
        "official_filing_count": int(candidate["official_filing_count"]),
        "material_event_count": int(candidate["material_event_count"]),
        "review_priority": int(candidate["review_priority"]),
        "positive_yoy_metrics": len(features.get("positive_metrics") or []),
        "negative_yoy_metrics": len(features.get("negative_metrics") or []),
        "conflicting_metrics": len(features.get("conflicting_metrics") or []),
        "categories_json": json.dumps(candidate.get("categories") or [], separators=(",", ":")),
        "headlines_json": json.dumps(candidate.get("headline_samples") or [], separators=(",", ":")),
        "news_age_hours": observation["news_age_hours"],
        "price_source": price_source,
        "previous_close": observation["previous_close"],
        "open": observation["open"], "high": observation["high"], "low": observation["low"],
        "close": observation["close"], "volume": observation["volume"],
        "open_to_close_pct": actual,
        "up": int(actual > 0),
        "direction": "UP" if actual > 0 else "DOWN" if actual < 0 else "FLAT",
    }


def append_immutable_rows(path: Path, rows: list[dict]) -> int:
    previous = {}
    if path.exists():
        with path.open(newline="", encoding="utf-8") as f:
            rd = csv.DictReader(f)
            if rd.fieldnames != FIELDS:
                raise ValueError("Candidate training schema changed; migration required")
            for row in rd:
                key = (row["date"], row["symbol"])
                if key in previous:
                    raise ValueError("Duplicate historical candidate row")
                previous[key] = row
    inserted = 0
    for row in rows:
        key = (row["date"], row["symbol"])
        encoded = {field: str(row[field]) for field in FIELDS}
        if key in previous:
            if previous[key] != encoded:
                raise ValueError(f"Immutable candidate training row changed: {key}")
        else:
            previous[key] = encoded
            inserted += 1
    if inserted:
        buf = io.StringIO()
        wr = csv.DictWriter(buf, fieldnames=FIELDS, lineterminator="\n")
        wr.writeheader()
        wr.writerows(previous[k] for k in sorted(previous))
        atomic_write(path, buf.getvalue())
    return inserted


def price_csv_reader(csv_path: Path):
    bars = defaultdict(list)
    with csv_path.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if not {"symbol", "date", "open", "high", "low", "close", "volume"}.issubset(r):
                raise ValueError("Price CSV missing required OHLCV columns")
            bars[r["symbol"]].append({key: r[key] for key in
                                     ("date", "open", "high", "low", "close", "volume")
                                     } | {"split": r.get("split") or 0})
    def read(symbol: str, session: date):
        if symbol not in bars:
            raise ValueError("Symbol absent from supplied OHLCV CSV")
        return bars[symbol]
    return read


def audit(session: date, *, root: Path = ROOT,
          price_reader=None, price_source: str = "Yahoo Finance unadjusted OHLC (NOT NSE-verified)",
          as_of: datetime | None = None) -> dict:
    now = (as_of or datetime.now(IST)).astimezone(IST)
    path = root / "news_collector/data" / session.isoformat() / "candidate_snapshot.json"
    report_path = root / "learning/data/candidate_reports" / f"{session.isoformat()}.json"
    report = {"session": session.isoformat(), "status": "UNAVAILABLE", "priced": 0,
              "candidate_count": 0, "errors": {}, "price_source": price_source,
              "note": "Research labeling only; theoretical open-to-close price movement, not executable P&L."}
    if now.date() < session or (now.date() == session and now.time() < time(16, 0)):
        report["reason"] = "Session has not completed; never use intraday prices as EOD labels."
    elif not path.exists():
        report["reason"] = "No immutable pre-09:00 candidate snapshot. No retroactive reconstruction."
    else:
        try:
            snapshot, digest = load_snapshot(path, session)
            report["candidate_count"] = len(snapshot["candidates"])
            report["snapshot_sha256"] = digest
            loader = price_reader or yahoo_bars
            rows = []
            for candidate in snapshot["candidates"]:
                try:
                    rows.append(candidate_outcome(candidate, session=session, snapshot=snapshot,
                                                  snap_hash=digest, price_reader=loader,
                                                  price_source=price_source))
                except Exception as e:
                    report["errors"][candidate["symbol"]] = f"{type(e).__name__}: {str(e)[:180]}"
            report["priced"] = len(rows)
            if len(rows) == len(snapshot["candidates"]):
                added = append_immutable_rows(root / "learning/data/candidate_outcomes.csv", rows)
                report.update({"status": "COMPLETE_NOT_NSE_VERIFIED",
                               "new_labeled_candidates": added,
                               "mean_market_open_close_pct": round(
                                   sum(r["open_to_close_pct"] for r in rows) / len(rows), 5),
                               "positive_count": sum(r["up"] for r in rows)})
            else:
                report.update({"status": "PARTIAL_NO_TRAINING_ROWS",
                               "reason": "Incomplete OHLCV; fail closed instead of selecting only priced stocks."})
        except Exception as e:
            report["reason"] = f"{type(e).__name__}: {str(e)[:180]}"
    atomic_write(report_path, json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--session-date", required=True)
    p.add_argument("--prices-csv", type=Path,
                   help="Optional supplied unadjusted OHLCV CSV with prior close day bars.")
    args = p.parse_args()
    reader = price_csv_reader(args.prices_csv) if args.prices_csv else None
    source = "USER_SUPPLIED_CSV_NOT_EXCHANGE_VERIFIED" if reader else \
             "Yahoo Finance unadjusted OHLC (NOT NSE-verified)"
    print(json.dumps(audit(date.fromisoformat(args.session_date),
                           price_reader=reader, price_source=source), indent=2))


if __name__ == "__main__":
    main()
