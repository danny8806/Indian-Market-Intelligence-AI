"""Durable multi-stock Kotak order intents and broker-confirmed fills."""

from __future__ import annotations

import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path


class LiveLedger:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS intents (
                    id INTEGER PRIMARY KEY,
                    tag TEXT NOT NULL UNIQUE,
                    session_date TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    phase TEXT NOT NULL CHECK(phase IN ('ENTRY','EXIT')),
                    side TEXT NOT NULL CHECK(side IN ('BUY','SELL')),
                    quantity INTEGER NOT NULL CHECK(quantity > 0),
                    reference_price TEXT NOT NULL,
                    reserved_notional TEXT NOT NULL,
                    broker_order_id TEXT,
                    state TEXT NOT NULL,
                    filled_quantity INTEGER NOT NULL DEFAULT 0,
                    average_fill_price TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(session_date,symbol,phase)
                );
                CREATE TABLE IF NOT EXISTS intent_events (
                    id INTEGER PRIMARY KEY,
                    tag TEXT NOT NULL,
                    state TEXT NOT NULL,
                    details TEXT NOT NULL,
                    observed_at TEXT NOT NULL
                );
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=30000")
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        try:
            yield db
        finally:
            db.close()

    def reserve_entry(self, *, session_date: date, symbol: str, side: str,
                      quantity: int, reference_price: Decimal, at: datetime,
                      max_per_side: int, gross_cap: Decimal) -> dict | None:
        if side not in {"BUY", "SELL"} or type(quantity) is not int or quantity <= 0:
            raise ValueError("Invalid entry side or quantity")
        if not symbol or not reference_price.is_finite() or reference_price <= 0:
            raise ValueError("Invalid entry symbol or price")
        if at.tzinfo is None or at.utcoffset() is None:
            raise ValueError("Entry time must include timezone")
        day = session_date.isoformat()
        notional = reference_price * quantity
        if notional > gross_cap:
            return None
        with self.lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                existing = db.execute("SELECT 1 FROM intents WHERE session_date=? AND symbol=? AND phase='ENTRY'",
                                      (day, symbol)).fetchone()
                if existing:
                    db.execute("COMMIT")
                    return None
                rows = db.execute("SELECT side,reserved_notional FROM intents WHERE session_date=? AND phase='ENTRY'",
                                  (day,)).fetchall()
                if sum(row["side"] == side for row in rows) >= max_per_side:
                    db.execute("COMMIT")
                    return None
                if sum(Decimal(row["reserved_notional"]) for row in rows) + notional > gross_cap:
                    db.execute("COMMIT")
                    return None
                tag = uuid.uuid4().hex
                stamp = at.isoformat()
                db.execute("""INSERT INTO intents(tag,session_date,symbol,phase,side,quantity,
                    reference_price,reserved_notional,state,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (tag,day,symbol,"ENTRY",side,quantity,str(reference_price),str(notional),
                     "RESERVED",stamp,stamp))
                db.execute("INSERT INTO intent_events(tag,state,details,observed_at) VALUES(?,?,?,?)",
                           (tag,"RESERVED","Entry intent persisted",stamp))
                db.execute("COMMIT")
                return {"tag": tag, "symbol": symbol, "side": side, "quantity": quantity}
            except Exception:
                db.execute("ROLLBACK")
                raise

    def reserve_exit(self, *, session_date: date, symbol: str, at: datetime) -> dict | None:
        if at.tzinfo is None or at.utcoffset() is None:
            raise ValueError("Exit time must include timezone")
        day = session_date.isoformat()
        with self.lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                entry = db.execute("SELECT * FROM intents WHERE session_date=? AND symbol=? AND phase='ENTRY'",
                                   (day,symbol)).fetchone()
                prior = db.execute("SELECT * FROM intents WHERE session_date=? AND symbol=? AND phase='EXIT'",
                                   (day,symbol)).fetchone()
                if (not entry or prior or entry["filled_quantity"] <= 0 or
                    entry["state"] not in {"FILLED", "PARTIAL_CANCELLED"}):
                    db.execute("COMMIT")
                    return None
                tag = uuid.uuid4().hex
                side = "SELL" if entry["side"] == "BUY" else "BUY"
                qty = entry["filled_quantity"]
                stamp = at.isoformat()
                db.execute("""INSERT INTO intents(tag,session_date,symbol,phase,side,quantity,
                    reference_price,reserved_notional,state,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (tag,day,symbol,"EXIT",side,qty,entry["reference_price"],"0", "RESERVED",stamp,stamp))
                db.execute("INSERT INTO intent_events(tag,state,details,observed_at) VALUES(?,?,?,?)",
                           (tag,"RESERVED","Exit intent persisted",stamp))
                db.execute("COMMIT")
                return {"tag":tag,"symbol":symbol,"side":side,"quantity":qty}
            except Exception:
                db.execute("ROLLBACK")
                raise

    def mark_submission_unknown(self, tag: str, at: datetime) -> None:
        """Persist this before sending; never auto-retry an uncertain submission."""
        with self.lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT state FROM intents WHERE tag=?",(tag,)).fetchone()
            if not row or row["state"] != "RESERVED":
                db.execute("ROLLBACK")
                raise ValueError("Intent already submitted or unknown")
            stamp = at.isoformat()
            db.execute("UPDATE intents SET state='SUBMISSION_UNKNOWN',updated_at=? WHERE tag=?",(stamp,tag))
            db.execute("INSERT INTO intent_events(tag,state,details,observed_at) VALUES(?,?,?,?)",
                       (tag,"SUBMISSION_UNKNOWN","Broker call may have reached Kotak",stamp))
            db.execute("COMMIT")

    def apply_broker_report(self, report: dict, at: datetime) -> None:
        tag = report["tag"]
        filled = report["filled_quantity"]
        with self.lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM intents WHERE tag=?",(tag,)).fetchone()
            if not row or row["state"] == "RESERVED":
                db.execute("ROLLBACK")
                raise ValueError("Unknown or unsent intent")
            if (type(filled) is not int or not row["filled_quantity"] <= filled <= row["quantity"] or
                report["trading_symbol"] != f'{row["symbol"]}-EQ'):
                db.execute("ROLLBACK")
                raise ValueError("Broker report conflicts with intent")
            state = "FILLED" if filled == row["quantity"] else "PARTIAL" if filled else "ACKNOWLEDGED"
            if str(report["status"]).lower() in {"rejected","cancelled","canceled"}:
                state = "REJECTED" if not filled else "PARTIAL_CANCELLED"
            stamp = at.isoformat()
            db.execute("""UPDATE intents SET state=?,broker_order_id=?,filled_quantity=?,
                average_fill_price=?,updated_at=? WHERE tag=?""",
                (state,report["broker_order_id"],filled,report["average_fill_price"],stamp,tag))
            if filled != row["filled_quantity"] or state != row["state"]:
                db.execute("INSERT INTO intent_events(tag,state,details,observed_at) VALUES(?,?,?,?)",
                           (tag,state,"Kotak report reconciled",stamp))
            db.execute("COMMIT")

    def snapshot(self, session_date: date) -> list[dict]:
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM intents WHERE session_date=? ORDER BY id",
                                                    (session_date.isoformat(),))]
