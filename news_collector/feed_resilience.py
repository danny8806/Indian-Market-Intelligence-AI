"""Bounded RSS repair and transient-error retry, adapted from the sibling
Indian-Market-Intelligence feed collector. No access-control bypass.
"""
from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import re
import time
import xml.etree.ElementTree as ET

import requests

MAX_TAIL_BYTES = 64_000
_XML_CONTROLS = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f]")
RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504})


def _clean_xml_controls(raw: bytes) -> bytes:
    """Strip XML-forbidden controls only when source text is valid UTF-8."""
    try:
        decoded = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw
    if not _XML_CONTROLS.search(decoded):
        return raw
    return _XML_CONTROLS.sub("", decoded).encode("utf-8")


def _recover_prefix(raw: bytes, err: ET.ParseError) -> ET.Element | None:
    """Recover complete RSS items ONLY when source ended in a truncated token."""
    if not str(err).startswith((
        "no element found:", "unclosed token:", "unclosed CDATA section:",
    )):
        return None
    if not (re.search(rb"<rss\b", raw[:4096], flags=re.I)
            and re.search(rb"<channel\b", raw[:4096], flags=re.I)):
        return None
    ends = list(re.finditer(rb"</item\s*>", raw, flags=re.I))
    if not ends:
        return None
    last = ends[-1].end()
    if len(raw) - last > MAX_TAIL_BYTES:
        return None
    try:
        recovered = ET.fromstring(raw[:last] + b"</channel></rss>")
    except ET.ParseError:
        return None
    if recovered.tag.lower() != "rss" or recovered.find("channel") is None:
        return None
    return recovered


def rss_root(raw: bytes, *, allow_truncated: bool = False) -> ET.Element:
    """Never silently repair arbitrary malformed XML or non-RSS documents."""
    raw = _clean_xml_controls(raw)
    try:
        return ET.fromstring(raw)
    except ET.ParseError as exc:
        if not allow_truncated:
            raise
        root = _recover_prefix(raw, exc)
        if root is None:
            raise
        return root


def _retry_after(value: str) -> float | None:
    value = value.strip()
    if value.isascii() and value.isdecimal():
        return float(value)
    try:
        until = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if until.tzinfo is None:
        until = until.replace(tzinfo=timezone.utc)
    return max(0, (until - datetime.now(timezone.utc)).total_seconds())


def read_with_retry(url: str, read, *, max_attempts: int = 1, sleep=time.sleep):
    """Retry only network failures and 408/429/5xx HTTP errors, max three tries."""
    if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or not 1 <= max_attempts <= 3:
        raise ValueError("max_attempts must be an integer 1..3")
    for attempt in range(max_attempts):
        try:
            return read(url)
        except (requests.Timeout, requests.ConnectionError, requests.HTTPError) as exc:
            response = getattr(exc, "response", None)
            status = getattr(response, "status_code", None)
            if isinstance(exc, requests.HTTPError) and status not in RETRYABLE_STATUS:
                raise
            if attempt + 1 == max_attempts:
                raise
            delay = min(2 ** attempt, 3)
            if status in {429, 503}:
                retry_after = _retry_after(response.headers.get("Retry-After", ""))
                if retry_after is None and status == 429:
                    raise
                if retry_after is not None:
                    delay = max(delay, retry_after)
                if delay > 3:
                    raise
            sleep(delay)
    raise AssertionError("unreachable")
