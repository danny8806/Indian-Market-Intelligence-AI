"""Live-only Kotak Neo session supervisor.

REAL broker reports are authoritative for fills, orders, and net quantities.
Never imports a prediction model or simulates trade fills. Actual order
submission requires authenticated broker access, validated research,
live Dhan prices, and an explicit per-session arming operation.
"""
from __future__ import annotations
import json, logging, os, threading
from datetime import datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo
from sqlalchemy import select
from bridge.app import reports
from scripts.validate_signals import validate
from live_desk.dhan_data import DhanDataClient, IST
from live_desk.dhan_instruments import fetch_dhan_symbols
from live_desk.kotak_gateway import KotakCredentials, login_kotak
from live_desk.kotak_instruments import lookup_kotak_equity
from live_desk.ledger import LiveLedger
from live_desk.strategy import load_policy
from live_desk.orb import opening_range
from live_desk.runtime import LiveRuntime
from live_desk.ticker import LiveTicker
from live_desk import broker_view

LOG=logging.getLogger("news-kotak-live")
START=time(9,17)
BOOK_REFRESH=timedelta(seconds=15)
PRICE_EXPIRY=timedelta(seconds=8)

class LiveSupervisor:
    def __init__(self,signal_engine,*,ledger_path=None,policy_path=None,clock=None,
                 dhan_factory=None,kotak_factory=None,master_fetch=None,ticker_factory=None):
        self.database=signal_engine
        self.clock=clock or (lambda:datetime.now(IST))
        self.policy=load_policy(Path(policy_path or Path(__file__).with_name("policy.json")))
        self.ledger=LiveLedger(Path(ledger_path or os.getenv("LIVE_KOTAK_LEDGER_DB",
                                                       "/data/live_kotak_orders.sqlite3")))
        self.dhan_factory=dhan_factory or DhanDataClient.from_environment
        self.kotak_factory=kotak_factory or (lambda:login_kotak(KotakCredentials.from_environment()))
        self.master_fetch=master_fetch or fetch_dhan_symbols
        self.ticker_factory=ticker_factory or LiveTicker
        self.allowed=os.getenv("LIVE_ORDERS_ALLOWED","").strip()=="YES"
        self.arm_secret=os.getenv("LIVE_ARM_TOTP_SECRET","")
        self.loss_cap=Decimal(os.getenv("LIVE_MAX_DAILY_GROSS_LOSS_INR","10000"))
        self.stop_pct=Decimal(os.getenv("LIVE_TICK_STOP_PCT","2.0"))
        if self.loss_cap<=0 or not Decimal("0")<self.stop_pct<=Decimal("5"):
            raise ValueError("Live stop and loss limits must be positive")
        self.lock=threading.RLock()
        self.armed=False
        self.session_authorized=False
        self.status="NEEDS_SETUP"
        self.error=None
        self.report=None
        self.report_sha=None
        self.session_date=None
        self.dhan=None
        self.broker=None
        self.ticker=None
        self.runtime=None
        self.dhan_ids={}
        self.kotak_ids={}
        self.quote_data={}
        self.last_quote_at=None
        self.last_book_at=None
        self.last_ohlc_at=None
        self.broker_positions=[]
        self.broker_orders=[]
        self.broker_fills=[]
        self.available_cash=None
        self.completed_exit=False
        self.thread=None
        self.stop_event=threading.Event()
        self.refresh_after=None

    def now(self):
        return self.clock().astimezone(IST)

    def today_report(self):
        now=self.now()
        with self.database.connect() as conn:
            record=conn.execute(select(reports).where(
                reports.c.session_date==now.date().isoformat())).mappings().first()
        if not record:return None,None
        data=json.loads(record["original_json"])
        validate(data,expected_date=now.date().isoformat())
        return data,record["sha256"]

    def _new_day(self,day):
        with self.lock:
            self.armed=False
            self.session_authorized=False
            if self.runtime:self.runtime.enabled=False
            if self.ticker:self.ticker.stop()
            self.ticker=None
            self.runtime=None
            self.dhan=None
            self.broker=None
            self.report=None
            self.report_sha=None
            self.dhan_ids={}
            self.kotak_ids={}
            self.quote_data={}
            self.last_book_at=None
            self.last_quote_at=None
            self.last_ohlc_at=None
            self.broker_orders=[]
            self.broker_positions=[]
            self.broker_fills=[]
            self.available_cash=None
            self.completed_exit=False
            self.status="WAITING_FOR_SIGNALS"
            self.error=None
            self.session_date=day

    def _load_report(self):
        report,sha=self.today_report()
        if not report or report["status"]!="READY":
            with self.lock:
                self.status="NO_ELIGIBLE_SIGNALS"
                self.report=report
            return False
        if self.report_sha and self.report_sha!=sha:
            raise RuntimeError("Immutable session research report unexpectedly changed")
        with self.lock:
            self.report=report
            self.report_sha=sha
            self.status="SIGNALS_VERIFIED"
        return True

    def _authenticate(self):
        if self.broker is None:self.broker=self.kotak_factory()
        if self.dhan is None:
            self.dhan=self.dhan_factory()
            self.dhan.login()

    def _build_runtime(self):
        now=self.now()
        if now.weekday()>=5 or now.time()<START:
            return
        if self.runtime:return
        if self.policy.timestamp_mode not in {"start","end"}:
            raise RuntimeError("Dhan 09:15 candle timestamp mode not yet verified")
        candidates=self.report["signals"]
        wanted={item["symbol"] for item in candidates}
        dhan=self.master_fetch(wanted,now=now)
        if dhan.session_date!=now.date().isoformat() or set(dhan.security_ids)!=wanted:
            raise RuntimeError("NSE EQ Dhan symbol master incomplete")
        kotak={s:lookup_kotak_equity(self.broker,s) for s in wanted}
        opening={}
        for symbol,id_ in dhan.security_ids.items():
            opening[symbol]=opening_range(self.dhan,id_,now.date(),
                                           timestamp_mode=self.policy.timestamp_mode)
        runtime=LiveRuntime(
            session_date=now.date(),signals=candidates,dhan_ids=dhan.security_ids,
            kotak_instruments=kotak,opening_ranges=opening,
            policy=self.policy,ledger=self.ledger,broker=self.broker,
            enabled=False,clock=self.now)
        ticker=self.ticker_factory(self.dhan,dhan.security_ids,self.on_tick)
        with self.lock:
            self.runtime=runtime
            self.ticker=ticker
            self.dhan_ids=dhan.security_ids
            self.kotak_ids=kotak
            self.status="MONITORING_LIVE"
        ticker.start()

    def _broker_cash(self):
        response=self.broker.limits(segment="CASH",exchange="NSE",product="MIS")
        if not isinstance(response,dict) or str(response.get("stat","")).lower()!="ok":
            raise RuntimeError("Kotak cash/margin limits unavailable")
        amount=Decimal(str(response.get("Net","NaN")))
        if not amount.is_finite() or amount<0:
            raise RuntimeError("Kotak available cash not verifiable")
        return amount

    def refresh_broker(self):
        if self.broker is None:return
        with self.lock:
            current_quotes=dict(self.quote_data)
        position=broker_view.positions(self.broker,current_quotes)
        orders=broker_view.orders(self.broker)
        fills=broker_view.fills(self.broker)
        cash=self._broker_cash()
        now=self.now()
        if self.runtime:self.runtime.reconcile_pending(now)
        with self.lock:
            self.broker_positions=position
            self.broker_orders=orders
            self.broker_fills=fills
            self.available_cash=str(cash)
            self.last_book_at=now
            if self.status!="MONITORING_LIVE":self.status="BROKER_CONNECTED"

    def poll_ohlc(self):
        now=self.now()
        if not self.dhan or not self.dhan_ids or now.weekday()>=5:
            return
        if not time(9,15)<=now.time()<time(15,30):return
        if self.last_ohlc_at and now-self.last_ohlc_at<timedelta(seconds=20):
            return
        result=self.dhan.get_ohlc(self.dhan_ids)
        with self.lock:
            for symbol,quote in result.items():
                old=self.quote_data.get(symbol,{})
                self.quote_data[symbol]={**old,**quote}
            self.last_ohlc_at=now

    def on_tick(self,tick):
        now=self.now()
        ts=tick.get("timestamp")
        if not isinstance(ts,datetime) or ts.tzinfo is None:return
        delta=now-ts.astimezone(IST)
        if delta<timedelta(seconds=-2) or delta>PRICE_EXPIRY:
            return
        symbol=str(tick.get("symbol") or "")
        if symbol not in self.dhan_ids:return
        value=Decimal(str(tick.get("ltp")))
        if not value.is_finite() or value<=0:return
        with self.lock:
            previous=self.quote_data.get(symbol,{})
            self.quote_data[symbol]={**previous,"ltp":float(value),
                                     "tick_at":ts.astimezone(IST).isoformat()}
            self.last_quote_at=now
            ready=self.armed and self._health_check_locked(now)
            if self.runtime:self.runtime.enabled=ready
            runtime=self.runtime
        if runtime and ready:
            # Real orders can be submitted only by the separately armed runtime.
            runtime.on_tick(tick)
        if runtime:
            self._monitor_adverse_move(symbol,value,now)

    def _monitor_adverse_move(self,symbol,price,now):
        if not self.allowed or not self.session_authorized or not self.runtime or self.broker is None:
            return
        if self.last_book_at is None or now-self.last_book_at>BOOK_REFRESH:
            self.disarm("Broker position data stale; cannot safely manage stop")
            return
        with self.lock:
            rows=list(self.broker_positions)
        for position in rows:
            if position["symbol"]!=symbol or position["net_quantity"]==0:
                continue
            intent=next((x for x in self.ledger.snapshot(now.date())
                         if x["symbol"]==symbol and x["phase"]=="ENTRY"
                         and x["state"]=="FILLED" and x.get("average_fill_price")),None)
            if intent is None:continue
            expected=intent["filled_quantity"] if intent["side"]=="BUY" else -intent["filled_quantity"]
            if int(position["net_quantity"])!=expected:
                self.disarm("Kotak position differs from filled entry; human reconciliation required")
                continue
            avg=Decimal(str(intent["average_fill_price"]))
            if avg<=0:continue
            level=avg*(1-self.stop_pct/100) if intent["side"]=="BUY" else avg*(1+self.stop_pct/100)
            hit=price<=level if intent["side"]=="BUY" else price>=level
            if not hit:continue
            with self.runtime.lock:
                exit_intent=self.ledger.reserve_exit(session_date=now.date(),symbol=symbol,at=now)
                if exit_intent:
                    # Tick-based exit: there is no broker-native protective stop.
                    self.runtime._submit_and_reconcile(exit_intent,now)
                    self.disarm("Loss threshold exit; check broker confirmation")

    def _health_check_locked(self,now):
        if not self.allowed or not self.report or self.report["status"]!="READY":
            return False
        if not self.broker or not self.dhan or not self.runtime:
            return False
        if not self.ticker or self.ticker.snapshot().get("state")!="CONNECTED":
            return False
        if self.last_quote_at is None or now-self.last_quote_at>PRICE_EXPIRY:
            return False
        if self.last_book_at is None or now-self.last_book_at>BOOK_REFRESH:
            return False
        if not time(9,17)<=now.time()<self.policy.entry_cutoff or now.weekday()>=5:
            return False
        if not self.available_cash or Decimal(self.available_cash)<self.policy.gross_cap:
            return False
        if self.error:return False
        if self.runtime.errors:return False
        # Fail closed if broker book shows a daily loss at or past the cap,
        # or if the market mark for any nonflat position is unavailable.
        pnl=Decimal("0")
        for position in self.broker_positions:
            if int(position["net_quantity"])!=0 and position["gross_mark_to_market"] is None:
                return False
            value=position["gross_mark_to_market"]
            if value is not None:
                pnl+=Decimal(str(value))
        if pnl<=-self.loss_cap:return False
        return True

    def ready(self):
        with self.lock:return self._health_check_locked(self.now())

    def arm(self):
        now=self.now()
        with self.lock:
            if not self._health_check_locked(now):
                raise RuntimeError("Live orders cannot arm: feeds, broker, funds or session not verified")
            if any(x["net_quantity"]!=0 and x["symbol"] in self.dhan_ids
                   for x in self.broker_positions):
                raise RuntimeError("Existing Kotak holdings/positions overlap selected symbols")
            unresolved={"RESERVED","SUBMISSION_UNKNOWN","ACKNOWLEDGED","PARTIAL"}
            if any(x["state"] in unresolved for x in self.ledger.snapshot(now.date())):
                raise RuntimeError("Unreconciled Kotak intent exists")
            self.armed=True
            self.session_authorized=True
            self.runtime.enabled=True
            self.status="LIVE_ARMED"
        return {"armed":True,"day":now.date().isoformat()}

    def disarm(self,reason="Operator disarmed new orders"):
        with self.lock:
            self.armed=False
            if self.runtime:self.runtime.enabled=False
            self.status="DISARMED"
        LOG.warning("%s",reason)

    def _manage_authorized_exits(self,now):
        """Only broker-confirmed positions entered by an authorized session can exit."""
        if (not self.allowed or not self.session_authorized or not self.runtime or
            now.time()<self.policy.exit_time or now.weekday()>=5):
            return
        if not self.last_book_at or now-self.last_book_at>BOOK_REFRESH:
            raise RuntimeError("Broker position book stale; cannot safely submit exit orders")
        intent_rows=self.ledger.snapshot(now.date())
        existing_exits={r["symbol"] for r in intent_rows if r["phase"]=="EXIT"}
        entries={r["symbol"]:r for r in intent_rows
                 if r["phase"]=="ENTRY" and r["state"] in ("FILLED","PARTIAL_CANCELLED")
                 and r["symbol"] not in existing_exits}
        positions={p["symbol"]:p for p in self.broker_positions}
        for symbol,entry in entries.items():
            position=positions.get(symbol)
            expected=entry["filled_quantity"] if entry["side"]=="BUY" else -entry["filled_quantity"]
            if position is None or int(position["net_quantity"])!=expected:
                raise RuntimeError("Kotak position reconciliation failed; exit blocked")
        self.runtime.exit_due(now)

    def cycle(self):
        now=self.now()
        if self.session_date!=now.date().isoformat():
            self._new_day(now.date().isoformat())
        if now.weekday()>=5:return
        # Monitor the actual Kotak brokerage account even when news is missing.
        # No signals must NEVER be interpreted as fabricated positions.
        if self.broker is None:self.broker=self.kotak_factory()
        if self.last_book_at is None or now-self.last_book_at>=BOOK_REFRESH:
            self.refresh_broker()
        has_report=self._load_report()
        if has_report:
            if self.dhan is None:
                self.dhan=self.dhan_factory()
                self.dhan.login()
            self._build_runtime()
            self.poll_ohlc()
        else:
            self.disarm("No qualified current-session signals")
        self._manage_authorized_exits(now)
        if self.armed and not self.ready():
            self.disarm("Broker or market data health degraded")
        # Entries cannot be recreated after restart without manual arming.

    def start(self):
        if self.thread and self.thread.is_alive():return
        self.stop_event.clear()
        self.thread=threading.Thread(target=self._run,name="live-kotak-supervisor",daemon=True)
        self.thread.start()

    def _run(self):
        while not self.stop_event.is_set():
            try:
                self.cycle()
                with self.lock:self.error=None
            except Exception as exc:
                with self.lock:
                    self.error=f"Live supervisor failed ({type(exc).__name__})"
                self.disarm("Live supervisor safety halt")
                LOG.exception("Supervisor error; new orders disarmed")
            self.stop_event.wait(3)

    def stop(self):
        self.stop_event.set()
        self.disarm("Service stopped")
        if self.ticker:self.ticker.stop()
        if self.thread and self.thread.is_alive() and self.thread!=threading.current_thread():
            self.thread.join(timeout=8)

    def snapshot(self):
        now=self.now()
        with self.lock:
            signals=self.report["signals"] if self.report and self.report["status"]=="READY" else []
            quotes=dict(self.quote_data)
            positions=list(self.broker_positions)
            orders=list(self.broker_orders)
            fills=list(self.broker_fills)
            ticker=self.ticker.snapshot() if self.ticker else {"state":"NOT_STARTED"}
            monitoring=self._health_check_locked(now)
            result={
                "mode":"LIVE_KOTAK_NEO_ONLY","server_time":now.isoformat(),
                "session_date":now.date().isoformat(),
                "signal_status":self.report["status"] if self.report else "UNAVAILABLE",
                "signals":signals,
                "research_cutoff_at":self.report.get("news_cutoff_at") if self.report else None,
                "report_hash":self.report_sha,"armed":self.armed,
                "session_authorized":self.session_authorized,
                "orders_permitted_by_server":self.allowed,
                "market_feed":ticker,"broker_connected":self.broker is not None and self.last_book_at is not None,
                "broker_books_updated_at":self.last_book_at.isoformat() if self.last_book_at else None,
                "available_cash":self.available_cash,
                "readiness":monitoring,
                "strategy":{"opening_range":"09:15 one-minute candle","entry_cutoff":self.policy.entry_cutoff.isoformat(),
                            "exit_time":self.policy.exit_time.isoformat(),
                            "allocation_per_position":str(self.policy.per_position),
                            "gross_cap":str(self.policy.gross_cap),
                            "max_long":self.policy.max_long,"max_short":self.policy.max_short,
                            "tick_stop_pct":str(self.stop_pct)},
                "positions":positions,"orders":orders[-70:],"fills":fills[-70:],
                "intents":self.ledger.snapshot(now.date()),
                "error":self.error,"runtime_errors":self.runtime.errors[-10:] if self.runtime else [],
                "quotes":{symbol:{**q,"fresh":bool(q.get("tick_at") and
                    now-datetime.fromisoformat(q["tick_at"])<=PRICE_EXPIRY)}
                         for symbol,q in quotes.items()}
            }
        return result
