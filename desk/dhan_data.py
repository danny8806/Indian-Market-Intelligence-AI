"""DhanHQ data-only adapter for the paper dashboard. Contains no order methods."""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import threading
import time
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import requests

LOG = logging.getLogger("sniper-paper.dhan")
IST = ZoneInfo("Asia/Kolkata")
AUTH_ROOT = "https://auth.dhan.co"
API_ROOT = "https://api.dhan.co/v2"


def totp_now(secret: str, *, at: float | None = None) -> str:
    """RFC 6238 SHA-1 TOTP implementation; secret stays in process memory."""
    key = base64.b32decode(secret.strip().replace(" ", "").upper() + "=" * ((8 - len(secret.strip().replace(" ", "")) % 8) % 8))
    counter = int((time.time() if at is None else at) // 30)
    digest = hmac.new(key, counter.to_bytes(8, "big"), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (int.from_bytes(digest[offset:offset + 4], "big") & 0x7FFFFFFF) % 1_000_000
    return f"{code:06d}"


class DhanDataClient:
    """Only authenticates and reads profile, quotes, and historical candles."""

    def __init__(self, client_id: str, pin: str, totp_secret: str, *, session: requests.Session | None = None):
        if not client_id or not pin or not totp_secret:
            raise ValueError("DHAN_CLIENT_ID, DHAN_PIN and DHAN_TOTP_SECRET are required")
        self.client_id = client_id.strip()
        self.pin = pin.strip()
        self.totp_secret = totp_secret.strip()
        self.session = session or requests.Session()
        self._lock = threading.RLock()
        self._history_lock = threading.Lock()
        self._quote_lock = threading.Lock()
        self._history_last_call = 0.0
        self._quote_last_call = 0.0
        self.token = ""
        self.token_expiry: datetime | None = None

    @classmethod
    def from_environment(cls) -> "DhanDataClient":
        return cls(
            os.getenv("DHAN_CLIENT_ID", ""),
            os.getenv("DHAN_PIN", ""),
            os.getenv("DHAN_TOTP_SECRET", ""),
        )

    def login(self) -> dict[str, Any]:
        """Generate a fresh 24-hour TOTP token and verify it before use."""
        url = f"{AUTH_ROOT}/app/generateAccessToken"
        params = {"dhanClientId": self.client_id, "pin": self.pin, "totp": totp_now(self.totp_secret)}
        response = self.session.post(url, params=params, timeout=20)
        if response.status_code >= 400:
            LOG.error("Dhan token generation failed (HTTP %s)", response.status_code)
            raise RuntimeError(f"Dhan token generation failed (HTTP {response.status_code})")
        data = response.json()
        token = str(data.get("accessToken") or "")
        if not token or str(data.get("dhanClientId", "")) != self.client_id:
            message=str(data.get("message", "")).lower()
            if "once every 2 minutes" in message:
                raise RuntimeError("Dhan token-generation cooldown")
            raise RuntimeError("Dhan rejected TOTP/PIN authentication")
        with self._lock:
            self.token = token
            raw_expiry = data.get("expiryTime")
            self.token_expiry = datetime.fromisoformat(raw_expiry).replace(tzinfo=IST) if raw_expiry else None
        return self.profile()

    def profile(self) -> dict[str, Any]:
        response = self._request("GET", f"{API_ROOT}/profile")
        data = response.json()
        if str(data.get("dhanClientId", "")) != self.client_id:
            raise RuntimeError("Dhan profile did not match the configured client ID")
        # Keep credential-like fields out of status/API responses.
        return {key: value for key, value in data.items() if key.lower() not in {"accesstoken", "token", "pin", "totp"}}

    def _request(self, method: str, url: str, *, json_body: dict[str, Any] | None = None) -> requests.Response:
        with self._lock:
            token = self.token
        if not token:
            raise RuntimeError("Dhan data access is disabled until authentication succeeds")
        headers = {"access-token": token, "client-id": self.client_id, "Accept": "application/json"}
        response = self.session.request(method, url, headers=headers, json=json_body, timeout=25)
        if response.status_code in (401, 403):
            with self._lock:
                self.token = ""
            raise RuntimeError("Dhan access token was rejected; data requests are paused")
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            # Dhan's error body can explain a bad request. Keep diagnostics
            # bounded and redact auth values before they enter logs or status.
            detail=""
            try:
                body=response.json()
                if isinstance(body,dict):
                    detail=str(body.get("remarks") or body.get("message") or body.get("errorMessage") or body.get("error") or "")
            except (ValueError,requests.RequestException):
                pass
            for secret in (self.token,self.pin,self.totp_secret):
                if secret:
                    detail=detail.replace(secret,"[redacted]")
            detail=detail[:240]
            suffix=f": {detail}" if detail else ""
            raise requests.HTTPError(f"Dhan API {url.removeprefix(API_ROOT)} returned HTTP {response.status_code}{suffix}",response=response) from exc
        return response

    def get_ltp(self, securities: dict[str, str]) -> dict[str, float]:
        """Fetch all portfolio LTPs in one quote request, at most 1 req/sec."""
        if not securities:
            return {}
        with self._quote_lock:
            delay = 1.05 - (time.monotonic() - self._quote_last_call)
            if delay > 0:
                time.sleep(delay)
            self._quote_last_call = time.monotonic()
            # Market Quote APIs expect numeric security IDs (unlike charts APIs,
            # whose securityId field is a string). String IDs return HTTP 400.
            payload = {"NSE_EQ": list(dict.fromkeys(int(value) for value in securities.values()))}
            response = self._request("POST", f"{API_ROOT}/marketfeed/ltp", json_body=payload)
        data = response.json().get("data", {}).get("NSE_EQ", {})
        out = {}
        reverse = {str(sid): symbol for symbol, sid in securities.items()}
        for sid, item in data.items():
            price = item.get("last_price") if isinstance(item, dict) else None
            if price is not None:
                out[reverse[str(sid)]] = float(price)
        return out

    def get_ohlc(self, securities: dict[str, str]) -> dict[str, dict[str, float]]:
        """Fetch current-session OHLC and LTP for all listed NSE equities."""
        if not securities:
            return {}
        with self._quote_lock:
            delay = 1.05 - (time.monotonic() - self._quote_last_call)
            if delay > 0:
                time.sleep(delay)
            self._quote_last_call = time.monotonic()
            payload = {"NSE_EQ": list(dict.fromkeys(int(value) for value in securities.values()))}
            response = self._request("POST", f"{API_ROOT}/marketfeed/ohlc", json_body=payload)
        data = response.json().get("data", {}).get("NSE_EQ", {})
        reverse = {str(sid): symbol for symbol, sid in securities.items()}
        out: dict[str, dict[str, float]] = {}
        for sid, item in data.items():
            if not isinstance(item, dict):
                continue
            ohlc = item.get("ohlc") or {}
            values = {key: float(ohlc[key]) for key in ("open", "high", "low", "close") if ohlc.get(key) is not None}
            if item.get("last_price") is not None:
                values["ltp"] = float(item["last_price"])
            if len(values) == 5:
                out[reverse[str(sid)]] = values
        return out

    def get_intraday(
        self,
        security_id: str,
        start: datetime,
        end: datetime,
        *,
        exchange_segment: str = "NSE_EQ",
        instrument: str = "EQUITY",
        interval: str = "15",
    ) -> dict[str, Any]:
        """Fetch a supported NSE equity interval, respecting the five-req/sec ceiling."""
        if interval not in {"1", "5", "15", "25", "60"}:
            raise ValueError("Unsupported Dhan intraday interval")
        if start.tzinfo is None or end.tzinfo is None or end <= start:
            raise ValueError("Historical request needs ordered timezone-aware timestamps")
        if (end - start).total_seconds() > 90 * 24 * 60 * 60:
            raise ValueError("Dhan intraday requests are limited to 90 days per call")
        body = {
            "securityId": str(security_id),
            "exchangeSegment": exchange_segment,
            "instrument": instrument,
            "interval": interval,
            "oi": False,
            "fromDate": start.astimezone(IST).strftime("%Y-%m-%d %H:%M:%S"),
            "toDate": end.astimezone(IST).strftime("%Y-%m-%d %H:%M:%S"),
        }
        with self._history_lock:
            delay = 0.22 - (time.monotonic() - self._history_last_call)
            if delay > 0:
                time.sleep(delay)
            self._history_last_call = time.monotonic()
            response = self._request("POST", f"{API_ROOT}/charts/intraday", json_body=body)
        data = response.json()
        lengths = [len(data.get(key, [])) for key in ("timestamp", "open", "high", "low", "close")]
        if len(set(lengths)) != 1:
            raise RuntimeError("Dhan returned misaligned historical candle fields")
        count=lengths[0]
        if len(data.get("volume", [])) != count:
            data["volume"]=[0]*count
        return data

    def websocket_url(self) -> str:
        """Build the Dhan v2 live-feed URL without logging or returning it to UI."""
        with self._lock:
            token = self.token
        if not token:
            raise RuntimeError("Dhan live feed is disabled until authentication succeeds")
        return "wss://api-feed.dhan.co/?" + urlencode({
            "version": "2", "token": token, "clientId": self.client_id, "authType": "2"
        })


def parse_dhan_ticker_packet(packet: bytes) -> dict[str, Any] | None:
    """Decode the documented Dhan v2 ticker response packet (little endian)."""
    import struct

    if len(packet) < 16:
        return None
    response_code = packet[0]
    message_length = struct.unpack_from("<h", packet, 1)[0]
    if message_length > len(packet) or message_length < 16 or response_code != 2:
        return None
    segment_code = packet[3]
    security_id = struct.unpack_from("<i", packet, 4)[0]
    ltp = struct.unpack_from("<f", packet, 8)[0]
    last_trade_epoch = struct.unpack_from("<i", packet, 12)[0]
    if security_id <= 0 or not (ltp > 0):
        return None
    return {
        "segment_code": segment_code,
        "security_id": str(security_id),
        "ltp": float(ltp),
        "timestamp": datetime.fromtimestamp(last_trade_epoch, IST),
    }


def parse_dhan_disconnect_code(packet: bytes) -> int | None:
    """Read the documented int16 reason from a Dhan feed-disconnect packet."""
    import struct
    if len(packet)<10 or packet[0]!=50:
        return None
    return int(struct.unpack_from("<h",packet,8)[0])


class DhanLiveTickerFeed:
    """Reconnectable Dhan ticker websocket for live paper stop monitoring."""

    def __init__(self, client: DhanDataClient, securities: dict[str, str], on_tick):
        self.client = client
        self.securities = {str(security_id): symbol for symbol, security_id in securities.items()}
        self.on_tick = on_tick
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._app = None
        self._lock = threading.RLock()
        self.status: dict[str, Any] = {"state": "NOT_STARTED", "message": "Live feed is not started", "last_tick": None}

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return dict(self.status)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="dhan-live-ticker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            app = self._app
        if app is not None:
            try:
                app.close()
            except Exception:
                pass
        thread=self._thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=5)

    def _set(self, **values: Any) -> None:
        with self._lock:
            self.status.update(values)

    def _run(self) -> None:
        import json
        import websocket

        retry = 1
        while not self._stop.is_set():
            try:
                url = self.client.websocket_url()

                def on_open(app):
                    request = {
                        "RequestCode": 15,
                        "InstrumentCount": len(self.securities),
                        "InstrumentList": [
                            {"ExchangeSegment": "NSE_EQ", "SecurityId": security_id}
                            for security_id in self.securities
                        ],
                    }
                    app.send(json.dumps(request))
                    self._set(state="CONNECTED", message="Dhan live ticker subscribed",last_error=None)

                def on_message(_app, message):
                    nonlocal retry
                    retry = 1
                    if isinstance(message, str):
                        return
                    disconnect_code=parse_dhan_disconnect_code(message)
                    if disconnect_code is not None:
                        reasons={805:"Dhan feed limit reached (805): too many requests or active connections",
                                 806:"Dhan Data APIs are not subscribed (806)",
                                 807:"Dhan access token expired (807)",
                                 808:"Dhan rejected the feed authentication (808)",
                                 809:"Dhan feed token is invalid (809)",
                                 810:"Dhan client ID is invalid (810)"}
                        reason=reasons.get(disconnect_code,f"Dhan feed disconnected (code {disconnect_code})")
                        self._set(last_error=reason,state="RECONNECTING",message=reason)
                        app.close()
                        return
                    tick = parse_dhan_ticker_packet(message)
                    if not tick:
                        return
                    symbol = self.securities.get(tick["security_id"])
                    if not symbol:
                        return
                    tick["symbol"] = symbol
                    exchange_time=tick["timestamp"]
                    received_at=datetime.now(IST)
                    # Dhan's packet labels this field EPOCH, but observed live
                    # values may be ahead of the dashboard clock. Use receipt
                    # time for session/stop decisions and retain provider time
                    # separately for diagnostics.
                    tick["exchange_timestamp"]=exchange_time.isoformat(timespec="seconds")
                    tick["timestamp"]=received_at
                    self.on_tick(tick)
                    self._set(last_tick=received_at.isoformat(timespec="seconds"),
                              last_exchange_trade_time=tick["exchange_timestamp"])

                def on_error(_app, error):
                    # Report only safe metadata; exception text may include the
                    # token-bearing WebSocket URL and must never reach the UI.
                    status = getattr(error, "status_code", None)
                    detail = f"Dhan WebSocket rejected connection (HTTP {status})" if status else f"Dhan WebSocket transport error ({type(error).__name__})"
                    self._set(last_error=detail, state="RECONNECTING", message="Dhan live feed interrupted; reconnecting")

                def on_close(_app, _code, _message):
                    if not self._stop.is_set():
                        status=self.snapshot()
                        if not status.get("last_error"):
                            self._set(last_error=f"Dhan websocket closed (code {_code})",state="RECONNECTING", message="Dhan live feed disconnected; reconnecting")
                        else:
                            self._set(state="RECONNECTING")

                app = websocket.WebSocketApp(
                    url, on_open=on_open, on_message=on_message,
                    on_error=on_error, on_close=on_close,
                )
                with self._lock:
                    self._app = app
                self._set(state="CONNECTING", message="Connecting to Dhan live ticker")
                app.run_forever(ping_interval=20, ping_timeout=10)
                if not self._stop.is_set():
                    status=self.snapshot()
                    if not status.get("last_error"):
                        self._set(last_error="Dhan websocket closed",state="RECONNECTING", message="Dhan live feed closed; reconnecting")
                    else:
                        self._set(state="RECONNECTING")
                    retry = min(retry * 2, 60)
            except Exception as exc:
                self._set(state="RECONNECTING", message=f"Dhan live feed unavailable ({type(exc).__name__}); retrying")
                retry = min(retry * 2, 60)
            finally:
                with self._lock:
                    self._app = None
            self._stop.wait(retry)


class DhanTokenSupervisor:
    """Refresh on process start and at 07:00 IST, retrying failures safely."""

    def __init__(self, client: DhanDataClient | None = None):
        self.client = client
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self.status: dict[str, Any] = {
            "state": "NOT_STARTED",
            "message": "Dhan token scheduler has not started",
            "last_success": None,
            "expires_at": None,
            "next_refresh": None,
        }

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="dhan-token-supervisor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return dict(self.status)

    def disable(self, message: str = "Dhan token scheduler is disabled") -> None:
        self._set_status(state="DISABLED", message=message)

    @staticmethod
    def next_7am(now: datetime) -> datetime:
        scheduled = now.replace(hour=7, minute=0, second=0, microsecond=0)
        return scheduled if now < scheduled else scheduled + timedelta(days=1)

    def _set_status(self, **values: Any) -> None:
        with self._lock:
            self.status.update(values)

    def _run(self) -> None:
        from_environment = False
        if self.client is None:
            try:
                self.client = DhanDataClient.from_environment()
            except ValueError:
                self._set_status(state="NEEDS_SETUP", message="Dhan login settings are not configured")
                while not self._stop.wait(60):
                    try:
                        self.client = DhanDataClient.from_environment()
                    except ValueError:
                        continue
                    from_environment = True
                    break
        if from_environment:
            LOG.info("Dhan login settings detected; starting token scheduler")

        last_refresh_date = None
        retry_seconds = 60
        while not self._stop.is_set():
            now = datetime.now(IST)
            due = (last_refresh_date is None or not self.client.token or
                   (now.time() >= datetime.min.time().replace(hour=7) and last_refresh_date != now.date()))
            if due:
                self._set_status(state="AUTHENTICATING", message="Refreshing Dhan data token")
                try:
                    profile = self.client.login()
                    last_refresh_date = now.date()
                    retry_seconds = 60
                    expiry = self.client.token_expiry
                    self._set_status(
                        state="AUTHENTICATED",
                        message="Dhan token verified; data-only access is ready",
                        last_success=datetime.now(IST).isoformat(timespec="seconds"),
                        expires_at=expiry.isoformat(timespec="seconds") if expiry else profile.get("tokenValidity"),
                        next_refresh=self.next_7am(datetime.now(IST)).isoformat(timespec="seconds"),
                    )
                except Exception as exc:
                    # Exception text from HTTP libraries can include request URLs;
                    # store only its type so PIN/TOTP/query data cannot leak.
                    cooldown="cooldown" in str(exc).lower()
                    delay=125 if cooldown else retry_seconds
                    message="Dhan token cooldown; retrying shortly" if cooldown else f"Dhan login failed ({type(exc).__name__}); retrying"
                    self._set_status(state="AUTH_ERROR", message=message)
                    self._stop.wait(delay)
                    retry_seconds = 125 if cooldown else min(retry_seconds * 2, 300)
                    continue
            next_run = self.next_7am(datetime.now(IST))
            self._set_status(next_refresh=next_run.isoformat(timespec="seconds"))
            wait_seconds = max(1.0, min(60.0, (next_run - datetime.now(IST)).total_seconds()))
            self._stop.wait(wait_seconds)
