"""One-request NSE public end-of-day price feed for whole candidate universe.

Uses NSE's 'Full Bhavcopy and Security Deliverable data' CSV.
No order APIs, no fabricated prices, no login/CAPTCHA bypass. May be blocked.
NOTE: This file does not verify stock splits, corporate-action adjustments, or
executable opening fills. Labels remain research-only.
"""
from __future__ import annotations

import csv
import io
from datetime import date, timedelta, datetime
from urllib.parse import urlsplit

import requests

MAX_BYTES = 5_000_000
BASES = (
    "https://nsearchives.nseindia.com/products/content/",
    "https://archives.nseindia.com/products/content/",
)


def parse_bhavcopy(payload: bytes, day: date) -> dict[str, dict]:
    if len(payload) > MAX_BYTES:
        raise ValueError("NSE bhavcopy exceeds maximum size")
    body = payload.decode("utf-8-sig")
    if "<html" in body[:300].lower():
        raise ValueError("NSE returned HTML instead of official CSV")
    reader = csv.DictReader(io.StringIO(body))
    if not reader.fieldnames:
        raise ValueError("Empty NSE bhavcopy")
    keys = {x.strip().upper(): x for x in reader.fieldnames}
    required = {"SYMBOL", "SERIES", "DATE1", "PREV_CLOSE", "OPEN_PRICE", "HIGH_PRICE",
                "LOW_PRICE", "CLOSE_PRICE", "TTL_TRD_QNTY"}
    if not required.issubset(keys):
        raise ValueError("NSE bhavcopy schema incomplete; cannot infer market prices")
    result = {}
    for r in reader:
        series = (r[keys["SERIES"]] or "").strip().upper()
        if series != "EQ":
            continue
        symbol = (r[keys["SYMBOL"]] or "").strip().upper()
        d = (r[keys["DATE1"]] or "").strip()
        try:
            dt = datetime.strptime(d, "%d-%b-%Y").date()
        except ValueError:
            raise ValueError("NSE bhavcopy invalid date format")
        if dt != day:
            raise ValueError("NSE bhavcopy date mismatch")
        if symbol in result:
            raise ValueError("Duplicate EQ symbol in NSE bhavcopy")
        def numeric(field):
            return float((r[keys[field]] or "").replace(",", "").strip())
        vals = {k: numeric(k) for k in
                ("PREV_CLOSE", "OPEN_PRICE", "HIGH_PRICE", "LOW_PRICE", "CLOSE_PRICE",
                 "TTL_TRD_QNTY")}
        pre, op, hi, lo, cl, volume = (
            vals["PREV_CLOSE"], vals["OPEN_PRICE"], vals["HIGH_PRICE"],
            vals["LOW_PRICE"], vals["CLOSE_PRICE"], vals["TTL_TRD_QNTY"])
        if min(pre, op, hi, lo, cl, volume) <= 0 or hi < max(op, cl) or lo > min(op, cl):
            raise ValueError(f"Invalid NSE OHLCV for {symbol}")
        result[symbol] = vals
    if len(result) < 300:
        raise ValueError(f"Unexpectedly few NSE EQ securities ({len(result)})")
    return result


def fetch_bhavcopy(day: date) -> tuple[dict[str, dict], str]:
    filename = "sec_bhavdata_full_" + day.strftime("%d%m%Y") + ".csv"
    errors = []
    for base in BASES:
        url = base + filename
        try:
            with requests.get(url, headers={
                "User-Agent": "IndianMarketResearchCollector/1.0",
                "Accept": "text/csv,text/plain,*/*"}, allow_redirects=False,
                stream=True, timeout=(7, 20)) as response:
                response.raise_for_status()
                if response.status_code != 200:
                    raise ValueError("Unexpected NSE response status")
                if int(response.headers.get("Content-Length") or 0) > MAX_BYTES:
                    raise ValueError("NSE price payload too large")
                chunks, count = [], 0
                for b in response.iter_content(65536):
                    count += len(b)
                    if count > MAX_BYTES:
                        raise ValueError("NSE price payload exceeds limit")
                    chunks.append(b)
                records = parse_bhavcopy(b"".join(chunks), day)
                return records, url
        except (requests.RequestException, ValueError, UnicodeError) as error:
            errors.append(f"{url}: {type(error).__name__}: {str(error)[:90]}")
    raise RuntimeError("Official NSE EOD CSV unavailable: " + "; ".join(errors))


def session_reader(day: date):
    """Construct daily validation bars from today's NSE price and PREV_CLOSE.

    The earlier bar is only a minimal placeholder for checking yesterday's
    official previous-close field; it is not a downloaded historical candle.
    """
    records, url = fetch_bhavcopy(day)
    def read(symbol: str, queried_day: date):
        if queried_day != day:
            raise ValueError("Session mismatch against fetched EOD report")
        if symbol not in records:
            raise ValueError(f"No EQ cash-price record for {symbol}")
        v = records[symbol]
        prev = v["PREV_CLOSE"]
        p = (day - timedelta(days=1)).isoformat()
        return [
            {"date": p, "open": prev, "high": prev, "low": prev, "close": prev,
             "volume": 1, "split": 0},
            {"date": day.isoformat(), "open": v["OPEN_PRICE"], "high": v["HIGH_PRICE"],
             "low": v["LOW_PRICE"], "close": v["CLOSE_PRICE"],
             "volume": v["TTL_TRD_QNTY"], "split": 0},
        ]
    return read, url
