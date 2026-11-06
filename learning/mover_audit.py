"""Post-market NIFTY 500 mover-coverage audit (research only).

Measures how often large *open-to-close* movers appeared in the genuine frozen
pre-09:00 news candidate pool. Unmatched movers are NOT proof of missing news;
some have no premarket catalyst and others are lost to unavailable data.
No automatic trade selection, no broker orders and no use of future inputs
for morning predictions.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from learning.candidate_outcomes import load_snapshot, atomic_write
from learning.nse_bhavcopy import fetch_bhavcopy
from news_collector.engine import ROOT as NEWS_ROOT, parse_universe_csv, read_jsonl
from news_collector.candidates import aware

IST = ZoneInfo("Asia/Kolkata")
PROJECT = NEWS_ROOT.parent
THRESHOLDS = (2.0, 3.0, 5.0)
MAX_OC_MOVE = 35.0


def signed_evidence(candidate: dict) -> str:
    """Only label explicitly one-sided financial evidence; never guess a trade."""
    e = candidate.get("evidence_summary", {})
    pos = e.get("positive_metrics") or []
    neg = e.get("negative_metrics") or []
    conflicting = e.get("conflicting_metrics") or []
    if conflicting or (pos and neg):
        return "MIXED"
    return "POSITIVE" if pos else "NEGATIVE" if neg else "NONE"


def review_market_day(day: date, prices: dict[str, dict],
                      universe: dict[str, str],
                      *, snapshot: dict | None,
                      snapshot_status: str,
                      official_price_url: str,
                      min_volume: int = 1) -> dict:
    """Deterministic, tested: rank market movers and compare with frozen news pool."""
    if len(universe) < 450:
        raise ValueError("Unverified NIFTY 500 constituent universe: cannot audit")
    screened = []
    missing = []
    anomalous = []
    candidates = None if snapshot is None else {
        item["symbol"]: item for item in snapshot["candidates"]
    }
    for symbol in sorted(universe):
        p = prices.get(symbol)
        if p is None:
            missing.append(symbol)
            continue
        try:
            op = float(p["OPEN_PRICE"])
            hi = float(p["HIGH_PRICE"])
            lo = float(p["LOW_PRICE"])
            cl = float(p["CLOSE_PRICE"])
            prev = float(p["PREV_CLOSE"])
            qty = float(p["TTL_TRD_QNTY"])
            if (not all(math.isfinite(x) for x in (op, hi, lo, cl, prev, qty))
                    or min(op, hi, lo, cl, prev) <= 0 or qty < min_volume
                    or hi < max(op, cl) or lo > min(op, cl)):
                raise ValueError("invalid official OHLCV / insufficient volume")
            intraday = 100 * (cl / op - 1)
            gap = 100 * (op / prev - 1)
            if abs(intraday) > MAX_OC_MOVE or abs(gap) > MAX_OC_MOVE:
                raise ValueError("extreme return; corporate-action check required")
        except (ValueError, TypeError, KeyError, ZeroDivisionError) as e:
            anomalous.append({"symbol": symbol, "reason": str(e)[:110]})
            continue
        c = (candidates or {}).get(symbol)
        screened.append({
            "symbol": symbol, "company": universe[symbol],
            "open": round(op, 4), "close": round(cl, 4),
            "volume": int(qty),
            "open_to_close_pct": round(intraday, 5),
            "gap_pct": round(gap, 5),
            "has_frozen_preopen_news_candidate": None if candidates is None else c is not None,
            "news_evidence": signed_evidence(c) if c else None,
            "review_priority": c.get("review_priority") if c else None,
            "source_urls": (c.get("source_urls") or [])[:2] if c else [],
        })
    if not screened:
        raise ValueError("No eligible official NSE NIFTY 500 daily prices")
    ups = sorted(screened, key=lambda r: (-r["open_to_close_pct"], r["symbol"]))
    downs = sorted(screened, key=lambda r: (r["open_to_close_pct"], r["symbol"]))
    selected = set(candidates) if candidates is not None else set()
    known_priced = [r for r in screened if r["symbol"] in selected]
    directional_agreement = []
    for row in known_priced:
        e = row["news_evidence"]
        ret = row["open_to_close_pct"]
        if e not in ("POSITIVE", "NEGATIVE") or ret == 0:
            continue
        directional_agreement.append(
            (e == "POSITIVE" and ret > 0) or (e == "NEGATIVE" and ret < 0))
    captures = {}
    for threshold in THRESHOLDS:
        movers = [r for r in screened if abs(r["open_to_close_pct"]) >= threshold]
        found = [r for r in movers if r["symbol"] in selected]
        captures[str(threshold)] = {
            "threshold_abs_open_close_pct": threshold,
            "movers_in_priced_universe": len(movers),
            "in_frozen_candidate_pool": len(found) if candidates is not None else None,
            "without_frozen_candidate": len(movers) - len(found) if candidates is not None else None,
            "candidate_coverage_pct": (round(100 * len(found) / len(movers), 2)
                                       if candidates is not None and movers else None),
            "uncovered_symbol_examples": ([r["symbol"] for r in movers if r["symbol"] not in selected][:30]
                                          if candidates is not None else []),
        }
    top_n = 10
    abs_sorted = sorted(screened, key=lambda r: (-abs(r["open_to_close_pct"]), r["symbol"]))
    top_news = sorted(known_priced, key=lambda r: (-int(r["review_priority"] or 0), r["symbol"]))[:10]
    result = {
        "schema_version": "mover-coverage-audit/1.0",
        "session_date": day.isoformat(),
        "generated_at": datetime.now(IST).isoformat(),
        "status": "COMPARED_TO_FROZEN_NEWS_POOL" if candidates is not None
                  else "MARKET_ONLY_NO_VERIFIABLE_PREOPEN_BASELINE",
        "news_pool_status": snapshot_status,
        "official_price_source": official_price_url,
        "nifty500_constituent_count": len(universe),
        "priced_count": len(screened),
        "missing_prices": missing, "excluded_anomalies": anomalous,
        "snapshot_candidate_count": len(selected) if candidates is not None else None,
        "snapshot_candidates_with_valid_prices": len(known_priced) if candidates is not None else None,
        "headline_only_market_top_10_gainers": ups[:top_n],
        "headline_only_market_top_10_losers": downs[:top_n],
        "top_10_by_absolute_intraday_move": abs_sorted[:top_n],
        "top_10_preopen_review_priority_actual_returns": top_news if candidates is not None else [],
        "mover_capture_by_threshold": captures,
        "evidence_direction_diagnostic": {
            "assessable_one_sided_evidence_count": len(directional_agreement) if candidates is not None else None,
            "one_sided_evidence_agreed_with_intraday_move": sum(directional_agreement)
                                                        if candidates is not None else None,
            "agreement_pct": (round(100 * sum(directional_agreement) / len(directional_agreement), 2)
                              if directional_agreement else None),
            "disclaimer": "Not a forecast hit-rate. Positive/negative facts are NOT trading predictions.",
        },
        "limitations": [
            "Without an immutable timestamped pre-09:00 snapshot, the report cannot measure missed-news coverage.",
            "An uncovered large mover does NOT imply missed premarket news; it may have no relevant preopen catalyst.",
            "Candidate coverage is market-move overlap, not recall against a complete licensed news ground truth.",
            "Official NSE daily OHLCV can reflect corporate actions and trading halts; anomalies require manual review.",
            "All returns are theoretical open-to-close percentages, not realistic entry fills or short-trade P&L.",
            "If there is no premarket frozen constituent list, current cached membership is not historically point-in-time.",
            "Research-only: no trade recommendation, prediction or automatic broker order.",
        ],
    }
    return result



def potential_cause_of_uncovered_movers(
    report: dict, archive_events: list[dict], frozen: dict | None
) -> dict:
    """Observability diagnostic, not causal attribution or complete missed-news count."""
    if frozen is None:
        return {"status": "NOT_AVAILABLE_NO_FROZEN_PREOPEN_POOL", "rows": []}
    cutoff = aware(frozen.get("cutoff_exclusive"))
    freeze_time = aware(frozen.get("as_of"))
    start = aware(frozen.get("news_window_start"))
    if not cutoff or not freeze_time:
        return {"status": "INVALID_SNAPSHOT_TIMESTAMPS", "rows": []}
    by_symbol: dict[str, list[dict]] = {}
    for event in archive_events:
        pub = aware(event.get("published_at"))
        discovered = aware(event.get("first_seen_at"))
        if not pub or not discovered or not (start is None or start <= pub) or pub >= cutoff:
            continue
        for symbol in event.get("symbols", []):
            by_symbol.setdefault(symbol, []).append({
                "url": event.get("url"),
                "published_at": pub.isoformat(),
                "first_seen_at": discovered.isoformat(),
            })
    all_movers = report["top_10_by_absolute_intraday_move"]
    # Also investigate threshold-qualified names outside top-ten if supplied.
    # Caller supplies top-ten significant movers; not exhaustive classification.
    rows = []
    for mover in all_movers:
        if mover["has_frozen_preopen_news_candidate"] is not False:
            continue
        symbol = mover["symbol"]
        matches = by_symbol.get(symbol, [])
        if not matches:
            reason = "NO_MATCHED_ARCHIVED_PREOPEN_DISCLOSURE"
        elif any(aware(x["first_seen_at"]) <= freeze_time for x in matches):
            reason = "ARCHIVED_BEFORE_FREEZE_BUT_ABSENT_IN_FROZEN_POOL"
        elif any(aware(x["first_seen_at"]) < cutoff for x in matches):
            reason = "FIRST_DISCOVERED_AFTER_FREEZE_BEFORE_9AM"
        else:
            reason = "FIRST_DISCOVERED_AFTER_9AM"
        rows.append({
            "symbol": symbol, "open_to_close_pct": mover["open_to_close_pct"],
            "potential_collection_gap": reason, "matched_archive_records": len(matches),
            "source_examples": matches[:3],
        })
    return {
        "status": "POTENTIAL_GAPS_IN_TOP_10_ABSOLUTE_MOVERS",
        "rows": rows,
        "warning": (
            "Timestamp/URL observations are not a complete news ground truth. "
            "A large price move may occur without premarket news; do not infer causation. "
            "Diagnostic is limited to top 10 absolute movers."
        ),
    }


def markdown_report(report: dict) -> str:
    """Human-readable post-market scorecard; source-of-truth remains JSON."""
    def clean(x):
        return str(x).replace("|", "/").replace("\n", " ")[:100]
    lines = [
        "# NIFTY 500 daily news coverage & market movers",
        "",
        f"Session: **{report.get('session_date')}**",
        f"Status: **{report.get('status')}**",
        f"Official price source: {report.get('official_price_source','unavailable')}",
        "",
    ]
    if report.get("status") == "MARKET_ONLY_NO_VERIFIABLE_PREOPEN_BASELINE":
        lines += [
            "**No genuine frozen pre-9 AM candidate snapshot exists.** "
            "This report cannot measure news capture rates or identify missed news.",
            "",
        ]
    lines += [
        f"Priced constituents: **{report.get('priced_count', 0)}** / "
        f"{report.get('nifty500_constituent_count', '?')}",
        "",
        "## Open-to-close movement versus pre-market news pool",
        "",
        "| Absolute move | Movers | In frozen pool | Coverage |",
        "|---|---:|---:|---:|",
    ]
    for k, v in (report.get("mover_capture_by_threshold") or {}).items():
        found = v.get("in_frozen_candidate_pool")
        rate = v.get("candidate_coverage_pct")
        lines.append(f"| ≥{k}% | {v['movers_in_priced_universe']} | "
                     f"{found if found is not None else 'N/A'} | "
                     f"{str(rate)+'%' if rate is not None else 'N/A'} |")
    for label, key in [
        ("Top 10 gainers", "headline_only_market_top_10_gainers"),
        ("Top 10 losers", "headline_only_market_top_10_losers"),
    ]:
        lines.extend(["", f"## {label}", "", "| Symbol | Open→close | In frozen news pool |",
                      "|---|---:|---|"])
        for x in report.get(key, []):
            match = x["has_frozen_preopen_news_candidate"]
            shown = "N/A" if match is None else "Yes" if match else "No matching candidate"
            lines.append(f"| {clean(x['symbol'])} | {x['open_to_close_pct']:+.2f}% | {shown} |")
    diagnostics = (report.get("possible_omission_diagnostics") or {}).get("rows") or []
    if diagnostics:
        lines.extend(["", "## Potential collection-gap diagnostics (not proof of missed news)", "",
                      "| Symbol | Potential reason |", "|---|---|"])
        for x in diagnostics:
            lines.append(f"| {clean(x['symbol'])} | {clean(x['potential_collection_gap'])} |")
    lines += [
        "",
        "**Interpretation:** Open-to-close movements are not realized profits. "
        "Unmatched movers do not establish missed premarket news or news-driven causation. "
        "Historical completeness needs a genuinely frozen before-09:00 dataset.",
        "",
    ]
    return "\n".join(lines)

def run(day: date, *, root: Path = PROJECT, price_loader=fetch_bhavcopy,
        universe_path: Path | None = None, now: datetime | None = None) -> dict:
    now = (now or datetime.now(IST)).astimezone(IST)
    if day > now.date() or (day == now.date() and now.time() < time(16, 0)):
        return {"session_date": day.isoformat(), "status": "NOT_AFTER_MARKET_CLOSE"}
    output = root / "learning/data/mover_reports" / (day.isoformat() + ".json")
    cache = universe_path or root / "news_collector/data/universe_snapshot.csv"
    if not cache.exists():
        report = {"session_date": day.isoformat(),
                  "status": "NO_OFFICIAL_NIFTY500_MEMBERSHIP_SNAPSHOT"}
        atomic_write(output, json.dumps(report, indent=2) + "\n")
        return report
    try:
        universe = parse_universe_csv(cache.read_text(encoding="utf-8-sig"))
    except (ValueError, UnicodeError) as e:
        report = {"session_date": day.isoformat(),
                  "status": "INVALID_OFFICIAL_CONSTITUENT_SNAPSHOT",
                  "error": str(e)[:180]}
        atomic_write(output, json.dumps(report, indent=2) + "\n")
        return report
    frozen = root / "news_collector/data" / day.isoformat() / "candidate_snapshot.json"
    snapshot = None
    frozen_status = "NO_FROZEN_09AM_SNAPSHOT"
    if frozen.exists():
        try:
            from learning.candidate_outcomes import load_snapshot
            snapshot, _ = load_snapshot(frozen, day)
            frozen_status = "VALIDATED_FROZEN_09AM_SNAPSHOT"
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
            frozen_status = "INVALID_FROZEN_SNAPSHOT: " + str(e)[:130]
    # Prefer the issuer universe captured *at the actual premarket freeze*,
    # rather than applying today's changed membership to historical snapshots.
    universe_kind = "LATEST_COLLECTOR_CACHE_NOT_HISTORICAL_POINT_IN_TIME"
    if snapshot is not None and isinstance(snapshot.get("frozen_universe_membership"), dict):
        membership = snapshot["frozen_universe_membership"]
        if 450 <= len(membership) <= 550:
            universe = membership
            universe_kind = "FROZEN_PREMARKET_CONSTITUENT_MEMBERSHIP"
    try:
        prices, url = price_loader(day)
    except Exception as e:
        report = {"session_date": day.isoformat(), "status": "NSE_EOD_UNAVAILABLE",
                  "error": f"{type(e).__name__}: {str(e)[:250]}",
                  "news_pool_status": frozen_status}
        atomic_write(output, json.dumps(report, indent=2) + "\n")
        return report
    report = review_market_day(day, prices, universe, snapshot=snapshot,
                               snapshot_status=frozen_status, official_price_url=url)
    report["generated_at"] = now.isoformat()
    report["universe_basis"] = universe_kind
    archive_path = root / "news_collector/data" / day.isoformat() / "events.jsonl"
    archive_events = list(read_jsonl(archive_path).values()) if archive_path.exists() else []
    report["possible_omission_diagnostics"] = potential_cause_of_uncovered_movers(
        report, archive_events, snapshot)
    atomic_write(output, json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    atomic_write(output.with_suffix(".md"), markdown_report(report))
    return report


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--session-date", required=True)
    args = p.parse_args()
    report = run(date.fromisoformat(args.session_date))
    print(json.dumps({
        k: v for k, v in report.items() if k not in (
            "headline_only_market_top_10_gainers", "headline_only_market_top_10_losers",
            "top_10_by_absolute_intraday_move", "top_10_preopen_review_priority_actual_returns",
            "missing_prices", "excluded_anomalies", "limitations",
        )
    }, indent=2))


if __name__ == "__main__":
    main()
