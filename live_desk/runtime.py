"""Live-only ORB candidate to Kotak order coordination.

Callers must supply authenticated Dhan/Kotak clients, today's validated signals,
same-day mappings and a verified completed opening candle before constructing.
No paper price or simulated fill path exists here.
"""

from __future__ import annotations

import threading
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from live_desk.dhan_data import IST
from live_desk.kotak_gateway import place_kotak_order, reconcile_kotak_tag
from live_desk.kotak_instruments import KotakInstrument
from live_desk.ledger import LiveLedger
from live_desk.strategy import LivePolicy, candidate_entry


class LiveRuntime:
    def __init__(self, *, session_date: date, signals: list[dict],
                 dhan_ids: dict[str, str], kotak_instruments: dict[str, KotakInstrument],
                 opening_ranges: dict[str, tuple[Decimal, Decimal]],
                 policy: LivePolicy, ledger: LiveLedger, broker,
                 enabled: bool, clock=None):
        symbols = {row["symbol"] for row in signals}
        if (not symbols or len(symbols) != len(signals) or
            symbols != set(dhan_ids) or symbols != set(kotak_instruments) or
            symbols != set(opening_ranges)):
            raise ValueError("Every signal needs exact Dhan/Kotak mapping and a completed ORB")
        if policy.timestamp_mode not in {"start", "end"}:
            raise ValueError("Dhan 09:15 timestamp convention is not verified")
        self.session_date = session_date
        self.signals = {row["symbol"]: row for row in signals}
        self.dhan_ids = dhan_ids
        self.kotak_instruments = kotak_instruments
        self.opening_ranges = opening_ranges
        self.policy = policy
        self.ledger = ledger
        self.broker = broker
        self.enabled = enabled
        self.clock = clock or (lambda: datetime.now(IST))
        self.lock = threading.RLock()
        self.previous: dict[str, Decimal] = {}
        self.last_tick_at: dict[str, datetime] = {}
        self.errors: list[str] = []

    def on_tick(self, tick: dict) -> dict | None:
        """Process a real Dhan ticker packet after receipt; never infer a fill."""
        symbol = tick.get("symbol")
        if symbol not in self.signals:
            return None
        at = tick.get("timestamp")
        if not isinstance(at, datetime) or at.tzinfo is None or at.utcoffset() is None:
            return None
        local = at.astimezone(IST)
        if local.date() != self.session_date or local.time() < time(9, 16):
            return None
        age = self.clock().astimezone(IST) - local
        if age < timedelta(seconds=-2) or age > timedelta(seconds=5):
            return None
        price = Decimal(str(tick.get("ltp")))
        if not price.is_finite() or price <= 0:
            return None
        with self.lock:
            prior_time = self.last_tick_at.get(symbol)
            if prior_time and at < prior_time:
                return None
            previous = self.previous.get(symbol)
            self.previous[symbol] = price
            self.last_tick_at[symbol] = at
            if not self.enabled or previous is None:
                return None
            side = self.signals[symbol]["side"]
            rows = self.ledger.snapshot(self.session_date)
            entries = [row for row in rows if row["phase"] == "ENTRY"]
            long_count = sum(row["side"] == "BUY" for row in entries)
            short_count = sum(row["side"] == "SELL" for row in entries)
            reserved = sum(Decimal(row["reserved_notional"]) for row in entries)
            high, low = self.opening_ranges[symbol]
            quantity = candidate_entry(
                side=side, previous_price=previous, price=price,
                orb_high=high, orb_low=low, tick_at=at, policy=self.policy,
                open_long=long_count, open_short=short_count, reserved_gross=reserved)
            if quantity is None:
                return None
            direction = "BUY" if side == "LONG" else "SELL"
            intent = self.ledger.reserve_entry(
                session_date=self.session_date, symbol=symbol, side=direction,
                quantity=quantity, reference_price=price, at=at,
                max_per_side=self.policy.max_long if side == "LONG" else self.policy.max_short,
                gross_cap=self.policy.gross_cap)
            if intent is None:
                return None
            return self._submit_and_reconcile(intent, at)

    def _submit_and_reconcile(self, intent: dict, at: datetime) -> dict:
        tag = intent["tag"]
        self.ledger.mark_submission_unknown(tag, at)
        try:
            result = place_kotak_order(self.broker, self.kotak_instruments[intent["symbol"]],
                                       intent["side"], intent["quantity"], tag)
            report = reconcile_kotak_tag(self.broker, tag)
            self.ledger.apply_broker_report(report, at)
            return {"tag": tag, "submission": result, "broker": report}
        except Exception as exc:
            # An exception may follow a successful network submission. Never retry.
            self.errors.append(f"{intent['symbol']}: {type(exc).__name__}; reconcile tag {tag}")
            return {"tag": tag, "state": "SUBMISSION_UNKNOWN"}

    def reconcile_pending(self, at: datetime) -> None:
        with self.lock:
            for row in self.ledger.snapshot(self.session_date):
                if row["state"] in {"SUBMISSION_UNKNOWN", "ACKNOWLEDGED", "PARTIAL"}:
                    try:
                        report = reconcile_kotak_tag(self.broker, row["tag"])
                        self.ledger.apply_broker_report(report, at)
                    except Exception:
                        self.errors.append(f"{row['symbol']}: broker reconciliation pending")

    def exit_due(self, at: datetime) -> list[dict]:
        if at.astimezone(IST).date() != self.session_date or at.astimezone(IST).time() < self.policy.exit_time:
            return []
        self.reconcile_pending(at)
        results = []
        with self.lock:
            for symbol in self.signals:
                intent = self.ledger.reserve_exit(session_date=self.session_date, symbol=symbol, at=at)
                if intent:
                    results.append(self._submit_and_reconcile(intent, at))
        return results
