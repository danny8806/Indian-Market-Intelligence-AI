"""Kotak Neo live submission boundary; caller owns reconciliation and risk checks."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class LiveOrderIntent:
    trading_symbol: str  # Exact pTrdSymbol from the current Kotak NSE CM master.
    side: str
    quantity: int
    reference_price: Decimal
    client_tag: str


def submit_live_order(client, intent: LiveOrderIntent, *, risk_approved: bool) -> object:
    """Submit only after external idempotency, funds and position checks pass.

    Never retry an ambiguous response here: reconcile with Kotak order/trade reports.
    """
    if not risk_approved:
        raise PermissionError("Live risk gate is closed")
    if not intent.trading_symbol or not intent.client_tag:
        raise ValueError("Mapped Kotak trading symbol and unique tag are required")
    if intent.side not in {"LONG", "SHORT"} or type(intent.quantity) is not int or intent.quantity <= 0:
        raise ValueError("Invalid order side or whole-share quantity")
    if not intent.reference_price.is_finite() or intent.reference_price <= 0:
        raise ValueError("Invalid live reference price")
    return client.place_order(exchange_segment="nse_cm", product="MIS", price="0",
                              order_type="MKT", quantity=str(intent.quantity),
                              validity="DAY", trading_symbol=intent.trading_symbol,
                              transaction_type="B" if intent.side == "LONG" else "S",
                              amo="NO", tag=intent.client_tag)
