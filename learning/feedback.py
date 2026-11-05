"""Evaluate immutable 09:00 IST research selections against daily market OHLC.

Research-only: no order API, no sizing, no signal publication. Fails closed on
missing Yahoo data, timing errors, conflicting snapshots, or split anomalies.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import sys
import tempfile
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from validate_signals import validate  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")
FIELDS = ["date", "symbol", "side", "rank", "first_available_at",
          "source_count", "news_age_hours", "reason", "news_summary", "source_hash",
          "previous_close", "open", "high", "low", "close", "volume",
          "opening_gap_pct", "open_to_close_pct", "trade_return_pct", "won"]


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix=".tmp-", delete=False) as f:
        name = f.name
        f.write(content)
    os.replace(name, path)


def json_report(path: Path, obj: dict) -> None:
    _atomic_text(path, json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def read_frozen_signals(root: Path, day: date) -> dict | None:
    candidates = [root / "signals" / p / f"{day.isoformat()}.json"
                  for p in ("archive", "incoming")]
    payloads = []
    for path in candidates:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            validate(data, expected_date=day.isoformat())
            payloads.append((path, data))
    if not payloads:
        return None
    if len(payloads) == 2 and payloads[0][1] != payloads[1][1]:
        raise ValueError("Conflicting archived and incoming morning signal snapshots")
    return payloads[0][1]


def _to_float(row: dict, key: str) -> float:
    value = float(row[key])
    if not math.isfinite(value):
        raise ValueError(f"Nonfinite {key}")
    return value


def evaluate(signal: dict, session: date, bars: list[dict]) -> dict:
    """Pure evaluation: price bars are date + OHLCV + split; oldest to newest."""
    actual = [b for b in bars if b["date"] == session.isoformat()]
    previous = [b for b in bars if b["date"] < session.isoformat()]
    if len(actual) != 1 or not previous:
        raise ValueError("Missing or duplicate session/previous price bar")
    today = actual[0]
    prior = max(previous, key=lambda x: x["date"])
    prev_close = _to_float(prior, "close")
    o, h, l, c = (_to_float(today, x) for x in ("open", "high", "low", "close"))
    vol = _to_float(today, "volume")
    if prev_close <= 0 or l <= 0 or vol <= 0 or o <= 0 or c <= 0:
        raise ValueError("Invalid zero/negative price or volume")
    if h < max(o, c) - 0.001 or l > min(o, c) + 0.001 or l > h:
        raise ValueError("Inconsistent OHLC")
    if float(today.get("split", 0) or 0) or float(prior.get("split", 0) or 0):
        raise ValueError("Stock split on session/previous bar; requires manual verification")
    gap = (o / prev_close - 1) * 100
    long_ret = (c / o - 1) * 100
    if abs(gap) > 35 or abs(long_ret) > 35:
        raise ValueError("Extreme daily return/gap; requires NSE corporate-action audit")
    r = long_ret if signal["side"] == "LONG" else -long_ret
    cutoff = datetime.combine(session, time(9), IST)
    first = datetime.fromisoformat(signal["first_available_at"].replace("Z", "+00:00")).astimezone(IST)
    news_age = (cutoff - first).total_seconds() / 3600
    if news_age < 0 or news_age > 7*24:
        raise ValueError("Publication time not plausible for overnight news; inspect manually")
    digest = hashlib.sha256(json.dumps(signal, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {
        "date": session.isoformat(), "symbol": signal["symbol"], "side": signal["side"],
        "rank": int(signal["rank"]), "first_available_at": signal["first_available_at"],
        "source_count": len(signal["sources"]), "news_age_hours": round(news_age, 4),
        "reason": signal["reason"], "news_summary": signal["news_summary"], "source_hash": digest,
        "previous_close": round(prev_close, 4), "open": round(o, 4), "high": round(h, 4),
        "low": round(l, 4), "close": round(c, 4), "volume": int(vol),
        "opening_gap_pct": round(gap, 5), "open_to_close_pct": round(long_ret, 5),
        "trade_return_pct": round(r, 5), "won": int(r > 0),
    }


def yahoo_bars(symbol: str, day: date) -> list[dict]:
    """Download unadjusted Yahoo OHLC, preserving split flags. One NSE ticker."""
    import yfinance as yf
    start = day - timedelta(days=11)
    end = day + timedelta(days=1)
    df = yf.Ticker(f"{symbol}.NS").history(start=start.isoformat(), end=end.isoformat(),
                                           interval="1d", auto_adjust=False,
                                           actions=True, repair=False, timeout=20)
    if df is None or df.empty:
        raise ValueError("Yahoo returned no bars")
    result = []
    for index, row in df.iterrows():
        ts = index.to_pydatetime()
        local_day = ts.astimezone(IST).date() if ts.tzinfo else ts.date()
        result.append({"date": local_day.isoformat(), "open": row.get("Open"),
                       "high": row.get("High"), "low": row.get("Low"),
                       "close": row.get("Close"), "volume": row.get("Volume"),
                       "split": row.get("Stock Splits", 0)})
    return result


def append_csv(path: Path, rows: list[dict]) -> int:
    existing = {}
    if path.exists():
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames != FIELDS:
                raise ValueError("Existing audit CSV columns mismatch")
            for row in reader:
                key = (row["date"], row["symbol"])
                if key in existing:
                    raise ValueError("Duplicate existing audit record")
                existing[key] = row
    new_count = 0
    for row in rows:
        key = (row["date"], row["symbol"])
        if key in existing:
            old = existing[key]
            if old["source_hash"] != row["source_hash"]:
                raise ValueError(f"Morning signal changed after publication for {key}")
            if abs(float(old["trade_return_pct"]) - row["trade_return_pct"]) > 0.00002:
                raise ValueError(f"Historical price changed for {key}; requires audit")
        else:
            existing[key] = {x: str(row[x]) for x in FIELDS}
            new_count += 1
    if new_count:
        import io
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(existing[key] for key in sorted(existing))
        _atomic_text(path, out.getvalue())
    return new_count


def audit(day: date, root: Path = ROOT, price_reader=yahoo_bars) -> dict:
    payload = read_frozen_signals(root, day)
    base = {"date": day.isoformat(), "source": "Yahoo Finance unadjusted daily OHLC (not NSE-verified)",
            "data_status": "UNAVAILABLE", "signals_expected": 0, "priced": 0,
            "errors": {}, "daily_equal_weight_return_pct": None,
            "note": "Research audit only. Open-price execution is hypothetical. No live orders."}
    if payload is None:
        base["reason"] = "No immutable 09:00 signal snapshot in repository."
    elif payload["status"] != "READY":
        base["reason"] = f"Morning report status {payload['status']}; nothing to score."
    else:
        base["signals_expected"] = len(payload["signals"])
        scored = []
        for signal in payload["signals"]:
            try:
                scored.append(evaluate(signal, day, price_reader(signal["symbol"], day)))
            except Exception as exc:
                base["errors"][signal["symbol"]] = f"{type(exc).__name__}: {exc}"
        base["priced"] = len(scored)
        if len(scored) == len(payload["signals"]):
            # Train only on days with 100% price coverage.
            append_csv(root / "learning/data/trades.csv", scored)
            base["data_status"] = "COMPLETE_YAHOO_ONLY"
            base["daily_equal_weight_return_pct"] = round(
                sum(r["trade_return_pct"] for r in scored) / len(scored), 5)
            base["wins"] = sum(r["won"] for r in scored)
            base["losses"] = sum(r["trade_return_pct"] < 0 for r in scored)
        else:
            base["data_status"] = "PARTIAL_NOT_A_PORTFOLIO_RESULT"
            base["reason"] = "Missing/invalid price records; do not report portfolio performance."
    json_report(root / "learning/data/reports" / f"{day.isoformat()}.json", base)
    return base


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--session-date", default=datetime.now(IST).date().isoformat())
    p.add_argument("--root", type=Path, default=ROOT)
    args = p.parse_args()
    result = audit(date.fromisoformat(args.session_date), args.root)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
