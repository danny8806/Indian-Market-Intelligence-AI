"""Dhan one-minute opening range, kept separate from Kotak execution."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
DHAN_INTRADAY_URL = "https://api.dhan.co/v2/charts/intraday"


@dataclass(frozen=True)
class OpeningRange:
    security_id: str
    session_date: date
    high: Decimal
    low: Decimal
    timestamp_ist: datetime


def opening_range_from_response(data: dict, security_id: str, session_date: date,
                                *, timestamp_mode: str) -> OpeningRange:
    """Require an audited Dhan epoch convention: `start` or `end`."""
    if timestamp_mode not in {"start", "end"}:
        raise ValueError("Dhan candle timestamp convention has not been audited")
    columns = ("timestamp", "open", "high", "low", "close", "volume")
    if any(not isinstance(data.get(key), list) for key in columns):
        raise ValueError("Incomplete Dhan candle response")
    count = len(data["timestamp"])
    if not count or any(len(data[key]) != count for key in columns):
        raise ValueError("Dhan candle arrays have different lengths")
    expected = datetime.combine(session_date, time(9, 15), IST)
    if timestamp_mode == "end":
        expected += timedelta(minutes=1)
    matches = []
    for index, epoch in enumerate(data["timestamp"]):
        if type(epoch) not in (int, float):
            raise ValueError("Invalid Dhan candle timestamp")
        observed = datetime.fromtimestamp(epoch, timezone.utc).astimezone(IST)
        if observed == expected:
            matches.append(index)
    if len(matches) != 1:
        raise ValueError("Exactly one 09:15 opening candle is required")
    index = matches[0]
    high = Decimal(str(data["high"][index]))
    low = Decimal(str(data["low"][index]))
    opened = Decimal(str(data["open"][index]))
    closed = Decimal(str(data["close"][index]))
    if not all(value.is_finite() and value > 0 for value in (high, low, opened, closed)):
        raise ValueError("Invalid Dhan candle price")
    if low > min(opened, closed) or high < max(opened, closed) or high < low:
        raise ValueError("Inconsistent Dhan OHLC")
    return OpeningRange(security_id, session_date, high, low, expected)


def fetch_dhan_opening_range(access_token: str, security_id: str, session_date: date,
                             *, timestamp_mode: str) -> OpeningRange:
    if not access_token or not security_id.isdecimal():
        raise ValueError("Dhan access token and numeric security ID are required")
    day = session_date.isoformat()
    body = json.dumps({"securityId": security_id, "exchangeSegment": "NSE_EQ",
                       "instrument": "EQUITY", "interval": "1", "oi": False,
                       "fromDate": f"{day} 09:15:00", "toDate": f"{day} 09:17:00"}).encode()
    request = Request(DHAN_INTRADAY_URL, data=body, method="POST",
                      headers={"Accept": "application/json", "Content-Type": "application/json",
                               "access-token": access_token})
    with urlopen(request, timeout=10) as response:
        if response.status != 200:
            raise RuntimeError("Dhan intraday request failed")
        payload = response.read(1_000_001)
    if len(payload) > 1_000_000:
        raise ValueError("Dhan candle response exceeds limit")
    return opening_range_from_response(json.loads(payload), security_id, session_date,
                                       timestamp_mode=timestamp_mode)


def direct_cross(previous_price: Decimal, price: Decimal, opening: OpeningRange,
                 side: str) -> bool:
    if side == "LONG":
        return previous_price <= opening.high < price
    if side == "SHORT":
        return previous_price >= opening.low > price
    raise ValueError("Unknown trading side")
