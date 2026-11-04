#!/usr/bin/env python3
"""Read a current research watchlist from GitHub; deliberately never place orders."""
import argparse
import json
import sys
from datetime import datetime, time
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from validate_signals import validate  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")
DEFAULT_URL = (
    "https://raw.githubusercontent.com/danny8806/"
    "Indian-Market-Intelligence-AI/main/signals/latest.json"
)


def read_payload(url: str, local_file: str | None) -> dict:
    if local_file:
        return json.loads(Path(local_file).read_text(encoding="utf-8"))
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "Cache-Control": "no-cache",
            "User-Agent": "IndianMarketIntelligenceDashboard/1.0"
        }
    )
    with urlopen(request, timeout=12) as response:
        return json.loads(response.read().decode("utf-8"))


def research_watchlist(payload: dict, now: datetime | None = None) -> dict:
    payload = validate(payload)
    now = now or datetime.now(IST)
    today = now.astimezone(IST).date().isoformat()
    if payload["session_date"] != today:
        raise ValueError(f"Stale session: expected {today}; received {payload['session_date']}")
    if now.astimezone(IST).time() < time(9, 0):
        raise ValueError("Before morning 09:00 IST cutoff")
    if payload["status"] == "NO_TRADE":
        return {"status": "NO_TRADE", "session_date": today,
                "long": [], "short": [], "execution_enabled": False,
                "reason": payload.get("reason", "No candidates selected")}
    if payload["status"] != "READY":
        raise ValueError(f"No verified research signals: {payload.get('reason', 'Unavailable')}")
    return {
        "status": "RESEARCH_ONLY",
        "session_date": today,
        "news_cutoff_at": payload["news_cutoff_at"],
        "generated_at": payload["generated_at"],
        "execution_enabled": False,
        "long": sorted(
            [x for x in payload["signals"] if x["side"] == "LONG"],
            key=lambda x: x["rank"]
        ),
        "short": sorted(
            [x for x in payload["signals"] if x["side"] == "SHORT"],
            key=lambda x: x["rank"]
        )
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--file", help="Read from local JSON for development")
    args = parser.parse_args()
    try:
        result = research_watchlist(read_payload(args.url, args.file))
    except Exception as exc:
        result = {"status": "REJECTED", "execution_enabled": False, "reason": str(exc)}
        print(json.dumps(result, indent=2))
        raise SystemExit(2) from exc
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
