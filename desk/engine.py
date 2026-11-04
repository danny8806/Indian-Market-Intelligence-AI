"""News-signal-driven, Dhan-data-backed paper desk.

Only verified current-session bridge reports can select stocks. No prediction model,
broker SDK, or live order methods are imported. All trade fills are simulated at
fresh observed prices and stored separately from real broker accounts.
"""
from __future__ import annotations

import json
import logging
import math
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, time as walltime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select
from bridge.app import reports
from desk.dhan_data import DhanDataClient, DhanLiveTickerFeed, DhanTokenSupervisor
from desk.dhan_instruments import fetch_dhan_symbols

LOG = logging.getLogger("news-paper-desk")
IST = ZoneInfo("Asia/Kolkata")


def now_ist():
    return datetime.now(IST)


def finite_price(value):
    try:
        x = float(value)
        return x if math.isfinite(x) and x > 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def stop_level(entry, side, pct):
    if side not in ("LONG", "SHORT") or not 0 <= pct <= 10:
        raise ValueError("Bad paper stop")
    raw = entry * (1 - pct / 100 if side == "LONG" else 1 + pct / 100)
    steps = math.floor(raw / 0.05 + 1e-9) if side == "LONG" else math.ceil(raw / 0.05 - 1e-9)
    return round(steps * 0.05, 2)


class PaperLedger:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        with self.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS trades(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_date TEXT NOT NULL, symbol TEXT NOT NULL,
                side TEXT NOT NULL CHECK(side IN ('LONG','SHORT')),
                signal_rank INTEGER NOT NULL, entry_time TEXT NOT NULL,
                entry_price REAL NOT NULL, quantity INTEGER NOT NULL,
                stop_price REAL NOT NULL, exit_time TEXT, exit_price REAL,
                exit_reason TEXT, gross_pnl REAL, status TEXT NOT NULL,
                UNIQUE(session_date,symbol)
            );
            CREATE TABLE IF NOT EXISTS activity(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                time TEXT NOT NULL, kind TEXT NOT NULL,
                symbol TEXT, message TEXT NOT NULL, price REAL
            );
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            """)

    @contextmanager
    def connect(self):
        with sqlite3.connect(self.path,timeout=20) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA busy_timeout=20000")
            db.execute("PRAGMA journal_mode=WAL")
            yield db

    def paper_enabled(self):
        with self.lock, self.connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key='paper_enabled'").fetchone()
            return row is not None and row[0] == "true"

    def toggle(self):
        with self.lock, self.connect() as db:
            value = not self.paper_enabled()
            db.execute("INSERT INTO settings VALUES('paper_enabled',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                       ("true" if value else "false",))
            self.event("SYSTEM", "Paper entries resumed" if value else "Paper entries paused")
            return value

    def event(self, kind, message, symbol=None, price=None):
        with self.lock, self.connect() as db:
            db.execute("INSERT INTO activity(time,kind,symbol,message,price) VALUES(?,?,?,?,?)",
                       (now_ist().isoformat(timespec="seconds"),kind,symbol,message,price))

    def events(self, limit=75):
        with self.lock, self.connect() as db:
            return [dict(x) for x in db.execute("SELECT time,kind,symbol,message,price FROM activity ORDER BY id DESC LIMIT ?",(limit,))]

    def rows(self):
        with self.lock, self.connect() as db:
            return [dict(x) for x in db.execute("SELECT * FROM trades ORDER BY id DESC")]

    def open_rows(self):
        return [x for x in self.rows() if x["status"] == "OPEN"]

    def entry(self, *, session_date, symbol, side, rank, price, at, capital, stop_pct):
        qty = int(capital // price)
        if qty <= 0: return False
        with self.lock, self.connect() as db:
            if db.execute("SELECT 1 FROM trades WHERE symbol=? AND status='OPEN'",(symbol,)).fetchone():
                return False
            cur = db.execute("""INSERT OR IGNORE INTO trades(
                session_date,symbol,side,signal_rank,entry_time,entry_price,quantity,stop_price,status)
                VALUES(?,?,?,?,?,?,?,?, 'OPEN')""",
                (session_date,symbol,side,rank,at.isoformat(timespec="seconds"),price,
                 qty,stop_level(price,side,stop_pct)))
            return bool(cur.rowcount)

    def close(self, trade_id, price, when, reason):
        with self.lock, self.connect() as db:
            trade = db.execute("SELECT * FROM trades WHERE id=? AND status='OPEN'",(trade_id,)).fetchone()
            if trade is None: return None
            multiplier = 1 if trade["side"] == "LONG" else -1
            pnl = round(multiplier * (price - trade["entry_price"]) * trade["quantity"],2)
            cur = db.execute("""UPDATE trades SET status='CLOSED',exit_time=?,exit_price=?,
                exit_reason=?,gross_pnl=? WHERE id=? AND status='OPEN'""",
                (when.isoformat(timespec="seconds"),price,reason,pnl,trade_id))
            return pnl if cur.rowcount else None


class NewsPaperEngine:
    def __init__(self, signal_database_engine, *, ledger=None, data_client=None,
                 clock=now_ist, master_resolver=fetch_dhan_symbols,
                 capital=1_000_000.0, per_stock=100_000.0,
                 stop_pct=2.0, entry_cutoff="09:20", exit_at="15:25",
                 paper_feed_enabled=True):
        self.signal_database_engine = signal_database_engine
        self.store = ledger or PaperLedger(os.getenv("PAPER_DESK_DB","/data/news_paper.sqlite3"))
        self.clock = clock
        self.master_resolver = master_resolver
        self.capital = float(capital)
        self.per_stock = float(per_stock)
        self.stop_pct = float(stop_pct)
        self.entry_cutoff = walltime.fromisoformat(entry_cutoff)
        self.exit_at = walltime.fromisoformat(exit_at)
        if self.capital < self.per_stock or self.per_stock <= 0 or not 0 < self.stop_pct <= 10:
            raise ValueError("Invalid paper capital or stop")
        if self.entry_cutoff > walltime(10,0) or self.exit_at >= walltime(15,30):
            raise ValueError("Entry/exit outside supported strategy window")
        if not (walltime(9,15) < self.entry_cutoff < self.exit_at):
            raise ValueError("Bad entry/exit ordering")
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self.thread = None
        self.client = data_client
        if data_client is None:
            try:
                self.client = DhanDataClient.from_environment()
            except ValueError:
                self.client = None
        self.auth = DhanTokenSupervisor(self.client)
        self.feed = None
        self.feed_enabled = paper_feed_enabled
        self.feed_fingerprint = None
        self.map_fingerprint = None
        self.mapping = {}
        self.mapping_date = None
        self.ohlc = {}
        self.quotes = {}
        self.candles = {}
        self.last_rest = None
        self.last_candles = None
        self.last_error = None
        self.last_report_hash = None
        self.report = None
        self.report_date = None
        self.last_signal_event = None

    def _now(self):
        return self.clock().astimezone(IST)

    def report_today(self):
        now = self._now()
        day = now.date().isoformat()
        with self.signal_database_engine.connect() as db:
            row = db.execute(select(reports).where(reports.c.session_date == day)).mappings().first()
        if row is None:
            return None, None
        payload = json.loads(row["original_json"])
        from scripts.validate_signals import validate
        validate(payload, expected_date=day)
        return payload, row["sha256"]

    def refresh_report(self):
        now = self._now()
        try:
            report, digest = self.report_today()
        except Exception as exc:
            self.last_error = f"Invalid signal report ({type(exc).__name__})"
            report, digest = None, None
        with self._lock:
            if self.report_date != now.date().isoformat():
                self.report = None
                self.last_report_hash = None
                self.map_fingerprint = None
                self.mapping = {}
                self.mapping_date = None
                self.report_date = now.date().isoformat()
            if digest != self.last_report_hash:
                self.report = report
                self.last_report_hash = digest
                self.map_fingerprint = None
                if report and report["status"] == "READY":
                    for item in report["signals"]:
                        self.store.event("SIGNAL",f"{item['side']} #{item['rank']}: {item['news_summary']}",item["symbol"])
                elif report:
                    self.store.event("SYSTEM",f"Research status: {report['status']}")
        return report

    def resolve_mapping(self):
        report = self.report
        if not report or report["status"] != "READY": return
        today = self._now().date().isoformat()
        wanted = {s["symbol"] for s in report["signals"]}
        fingerprint = (today, tuple(sorted(wanted)))
        if self.map_fingerprint == fingerprint and set(self.mapping)==wanted:
            return
        if not self.client or self.auth.snapshot().get("state") != "AUTHENTICATED":
            return
        snapshot = self.master_resolver(wanted,now=self._now())
        if set(snapshot.security_ids) != wanted or snapshot.session_date != today:
            raise ValueError("Dhan symbol master is missing current-session mappings")
        with self._lock:
            self.mapping = snapshot.security_ids
            self.mapping_date = today
            self.map_fingerprint = fingerprint
            self.ohlc = {}
            if self.feed:
                self.feed.stop()
            self.feed = None
            self.feed_fingerprint = None

    def ensure_feed(self):
        if not self.feed_enabled or not self.client or not self.mapping:
            return
        if self.feed is None:
            self.feed = DhanLiveTickerFeed(self.client,dict(self.mapping),self.on_tick)
            self.feed.start()

    def _fresh(self, symbol, moment):
        q = self.quotes.get(symbol)
        if not q: return None
        stamp = q.get("stamp")
        if not isinstance(stamp,datetime) or stamp.date()!=moment.date():
            return None
        age = (moment-stamp).total_seconds()
        if not 0 <= age <= 90:return None
        return finite_price(q.get("ltp"))

    def poll_quotes(self):
        now = self._now()
        if now.weekday()>4 or not walltime(9,15)<=now.time()<walltime(15,30):
            return
        if not self.client or not self.mapping or not self.client.token:
            return
        if self.last_rest and (now-self.last_rest).total_seconds()<20:
            return
        self.last_rest = now
        values = self.client.get_ohlc(dict(self.mapping))
        for symbol,raw in values.items():
            if symbol not in self.mapping: continue
            self.ohlc[symbol] = raw
            price = finite_price(raw.get("ltp"))
            if price is not None:
                self.on_tick({"symbol":symbol,"ltp":price,"timestamp":now,"source":"REST_LTP"})

    def poll_candles(self):
        now=self._now()
        if not self.client or not self.mapping or not self.client.token:
            return
        if not walltime(9,30)<=now.time()<=walltime(15,45):
            return
        if self.last_candles and (now-self.last_candles).total_seconds()<900:
            return
        self.last_candles=now
        for symbol,secid in list(self.mapping.items()):
            try:
                day=now.replace(hour=9,minute=15,second=0,microsecond=0)
                values=self.client.get_intraday(secid,day,now,exchange_segment="NSE_EQ",instrument="EQUITY")
                rows=[]
                stamps=values.get("timestamp") or []
                for i,ts in enumerate(stamps):
                    stamp=datetime.fromtimestamp(float(ts),IST)
                    if stamp.date()!=now.date(): continue
                    bar={k:float(values[k][i]) for k in ("open","high","low","close","volume")}
                    if not all(math.isfinite(v) for v in bar.values()):continue
                    rows.append({"time":stamp.isoformat(timespec="seconds"),**bar})
                self.candles[symbol]=rows[-96:]
            except Exception as exc:
                LOG.info("Dhan chart history unavailable for %s: %s",symbol,type(exc).__name__)

    def on_tick(self,tick):
        symbol=str(tick.get("symbol",""))
        price=finite_price(tick.get("ltp"))
        stamp=tick.get("timestamp")
        if price is None or not isinstance(stamp,datetime) or stamp.utcoffset() is None:
            return
        stamp=stamp.astimezone(IST)
        now=self._now()
        if (stamp>now+timedelta(seconds=10) or (now-stamp).total_seconds()>90
            or stamp.date()!=now.date()):
            return
        with self._lock:
            if symbol not in self.mapping: return
            old=self.quotes.get(symbol)
            if old and stamp<old["stamp"]: return
            self.quotes[symbol]={"ltp":price,"stamp":stamp,"source":str(tick.get("source","Dhan"))}
        if now.weekday() >= 5 or stamp.time() < walltime(9,15) or stamp.time()>=walltime(15,30):
            return
        for trade in self.store.open_rows():
            if trade["symbol"]!=symbol or trade["session_date"]!=now.date().isoformat():
                continue
            stop_hit=(trade["side"]=="LONG" and price<=trade["stop_price"]) or (trade["side"]=="SHORT" and price>=trade["stop_price"])
            if stop_hit or stamp.time()>=self.exit_at:
                reason="PAPER_STOP_LTP" if stop_hit else "PAPER_EOD_LTP"
                pnl=self.store.close(trade["id"],price,stamp,reason)
                if pnl is not None:self.store.event("EXIT",f"Paper {reason} at ₹{price:.2f}; P&L ₹{pnl:.2f}",symbol,price)

    def attempt_paper_entries(self):
        now=self._now()
        if (now.weekday()>=5 or not walltime(9,15)<=now.time()<self.entry_cutoff
            or not self.store.paper_enabled()):
            return
        report=self.report
        if not report or report["status"]!="READY" or report["session_date"]!=now.date().isoformat():
            return
        if not self.client or self.auth.snapshot().get("state")!="AUTHENTICATED" or self.mapping_date!=now.date().isoformat():
            return
        if set(self.mapping)!={x["symbol"] for x in report["signals"]}:return
        for s in report["signals"]:
            symbol=s["symbol"]
            price=self._fresh(symbol,now)
            if price is None:continue
            if self.store.entry(session_date=now.date().isoformat(),symbol=symbol,
                                side=s["side"],rank=s["rank"],price=price,
                                at=now,capital=self.per_stock,stop_pct=self.stop_pct):
                self.store.event("ENTRY",f"Paper {s['side']} entry at fresh Dhan LTP ₹{price:.2f}",symbol,price)

    def start(self):
        if self.thread and self.thread.is_alive():return
        self._stop.clear()
        self.auth.start()
        self.thread=threading.Thread(target=self._run,name="news-paper-runtime",daemon=True)
        self.thread.start()

    def stop(self):
        self._stop.set()
        if self.feed:self.feed.stop()
        self.auth.stop()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=5)

    def _run(self):
        while not self._stop.is_set():
            try:
                self.refresh_report()
                if self.report and self.report["status"]=="READY":
                    self.resolve_mapping()
                    self.ensure_feed()
                self.poll_quotes()
                self.attempt_paper_entries()
                self.poll_candles()
                self.last_error=None
            except Exception as exc:
                LOG.exception("Paper desk loop failed")
                self.last_error=f"{type(exc).__name__}: runtime unavailable"
            self._stop.wait(3)

    def toggle_entries(self):
        if not self.report or self.report["status"]!="READY" or self.mapping_date!=self._now().date().isoformat():
            raise RuntimeError("Cannot enable entries without a verified current signal and mapped Dhan securities")
        if not self.client or self.auth.snapshot().get("state")!="AUTHENTICATED":
            raise RuntimeError("Dhan data authentication is not ready")
        return self.store.toggle()

    def _trade_json(self,row):
        out=dict(row)
        direction="UP" if row["side"]=="LONG" else "DOWN"
        entry_notional=row["entry_price"]*row["quantity"]
        pnl=row["gross_pnl"] if row["status"]=="CLOSED" else None
        out.update({"direction":direction,"signal_date":row["session_date"],"label":row["symbol"],
                    "opened_at":row["entry_time"],"closed_at":row["exit_time"],
                    "exit_date":str(row["exit_time"] or "")[:10],
                    "net_pnl":pnl,"notional":round(entry_notional,2),
                    "return_pct":100*pnl/entry_notional if pnl is not None else 0,
                    "estimated_fees":None})
        return out

    def all_trades(self):
        return [self._trade_json(t) for t in self.store.rows()]

    def snapshot(self):
        now=self._now()
        report=self.report if self.report_date==now.date().isoformat() else None
        ready=bool(report and report["status"]=="READY")
        items=report["signals"] if ready else []
        trades=self.all_trades()
        opens={t["symbol"]:t for t in trades if t["status"]=="OPEN"}
        closed=[t for t in trades if t["status"]=="CLOSED"]
        today=now.date().isoformat()
        closed_today=[t for t in closed if t["exit_date"]==today]
        realized_today=round(sum(t["gross_pnl"] or 0 for t in closed_today),2)
        with self._lock:
            quote=dict(self.quotes)
            ohlc=dict(self.ohlc)
            candles=dict(self.candles)
        market_now=now.weekday()<5 and walltime(9,15)<=now.time()<walltime(15,30)
        symbols=[];open_pnl=0.
        for signal in items:
            symbol=signal["symbol"]
            q=quote.get(symbol,{})
            price=q.get("ltp") if q and (now-q["stamp"]).total_seconds()<=90 else None
            last_tick=q["stamp"].isoformat(timespec="seconds") if q else None
            old=opens.get(symbol)
            pnl=None
            if old and price is not None:
                pnl=round((1 if old["side"]=="LONG" else -1)*(price-old["entry_price"])*old["quantity"],2)
                open_pnl+=pnl
            oc=ohlc.get(symbol,{})
            close_ref=finite_price(oc.get("close"))
            change=price-close_ref if price is not None and close_ref else None
            change_pct=100*change/close_ref if change is not None else None
            symbols.append({
                "symbol":symbol,"label":symbol,"signal":"BUY" if signal["side"]=="LONG" else "SELL",
                "prediction":"UP" if signal["side"]=="LONG" else "DOWN",
                "p_up":None,"signal_time":signal["first_available_at"],
                "signal_note":signal["reason"],"news_summary":signal["news_summary"],
                "sources":signal["sources"],"rank":signal["rank"],
                "ltp":price,"prev_close":close_ref,"open":finite_price(oc.get("open")),
                "change":change,"change_pct":change_pct,"volume":None,
                "last_tick":last_tick,"history_ready":bool(candles.get(symbol)),
                "data_error":None if price is not None else ("Dhan price unavailable" if market_now else None),
                "position":old,"mark":{"net":pnl,"gross":pnl} if pnl is not None else None,
                "candles":candles.get(symbol,[]),"entered_today":any(t["symbol"]==symbol and t["session_date"]==today for t in trades),
                "stop_price":old["stop_price"] if old else None
            })
        all_daily={}
        for t in closed:
            all_daily[t["exit_date"]]=all_daily.get(t["exit_date"],0.)+(t["gross_pnl"] or 0)
        equity=self.capital; peak=equity;dd=0.;curve=[]
        for day,day_pnl in sorted(all_daily.items()):
            equity+=day_pnl;peak=max(equity,peak);delta=equity-peak;dd=min(dd,delta)
            curve.append({"date":day,"daily_pnl":round(day_pnl,2),"equity":round(equity,2),"drawdown":round(delta,2)})
        winners=[t["gross_pnl"] for t in closed if (t["gross_pnl"] or 0)>0]
        losers=[t["gross_pnl"] for t in closed if (t["gross_pnl"] or 0)<0]
        total=sum(t["gross_pnl"] or 0 for t in closed)
        gross_profit=sum(winners)
        gross_loss=abs(sum(losers))
        perf={
            "net_profit":round(total,2),"total_return_pct":100*total/self.capital,
            "win_rate":100*len(winners)/len(closed) if closed else 0,
            "wins":len(winners),"losses":len(losers),"breakeven":len(closed)-len(winners)-len(losers),
            "trade_count":len(closed),"profit_factor":round(gross_profit/gross_loss,3) if gross_loss else None,
            "max_drawdown":abs(dd),"max_drawdown_pct":100*abs(dd)/self.capital,
            "gross_profit":round(gross_profit,2),"gross_loss":round(gross_loss,2),
            "estimated_fees":None,"average_win":sum(winners)/len(winners) if winners else 0,
            "average_loss":sum(losers)/len(losers) if losers else 0,
            "open_pnl":round(open_pnl,2),"equity_return_pct":100*(total+open_pnl)/self.capital,
            "equity_curve":curve,"by_symbol":[{"symbol":s["symbol"],
                "trades":sum(t["symbol"]==s["symbol"] for t in closed),
                "win_rate":100*sum(t["symbol"]==s["symbol"] and (t["gross_pnl"] or 0)>0 for t in closed)/
                    max(1,sum(t["symbol"]==s["symbol"] for t in closed)),
                "net_pnl":sum(t["gross_pnl"] or 0 for t in closed if t["symbol"]==s["symbol"])}
                for s in items],
        }
        data_enabled=bool(self.client and self.auth.snapshot().get("state")=="AUTHENTICATED")
        runtime_ready=ready and data_enabled and self.mapping_date==today
        feed_state=self.feed.snapshot() if self.feed else {"state":"NOT_STARTED","message":"No verified signal subscription or credentials"}
        mapped=set(self.mapping)
        return {
            "server_time":now.isoformat(timespec="seconds"),
            "paper_enabled":self.store.paper_enabled(),"symbols":symbols,
            "open_positions":list(opens.values()),"closed_trades":closed[:30],
            "activity":self.store.events(),"storage":{"ok":True,"dirty":False,"message":"Durable SQLite paper-only ledger"},
            "dhan_auth":self.auth.snapshot(),"feed":feed_state,
            "connection":{"status":"Connected" if feed_state.get("state")=="CONNECTED" else "Waiting",
                          "message":feed_state.get("message") or "Read-only Dhan market feed"},
            "metrics":{"capital":self.capital,"deployed":sum(t["notional"] for t in opens.values()),
                       "open_pnl":round(open_pnl,2),"realized_today":realized_today,
                       "day_pnl":round(open_pnl+realized_today,2),"open_count":len(opens),
                       "trade_count":sum(t["session_date"]==today for t in trades),
                       "max_positions":10,"max_notional":self.capital},
            "performance":perf,
            "strategy":{"name":"Verified 09:00 News Signals · Paper Desk",
                        "runtime_ready":runtime_ready,"provider":"Dhan Read-Only",
                        "capital_per_stock":self.per_stock,"starting_capital":self.capital,
                        "entry_rule":f"Fresh Dhan LTP between 09:15 and {self.entry_cutoff.strftime('%H:%M')} IST",
                        "exit_rule":f"{self.stop_pct:.1f}% stop or {self.exit_at.strftime('%H:%M')} IST EOD",
                        "positions":[{"symbol":s["symbol"],"side":s["side"],"rank":s["rank"],
                                      "stop_loss_pct":self.stop_pct,"reason":s["reason"],
                                      "news_summary":s["news_summary"]}
                                     for s in items],
                        "research_warning":"Research watchlist only. All fills are paper simulations; no broker orders.",
                        "simulated_only":True},
            "engine":{"status":"READY" if runtime_ready else "BLOCKED",
                      "signal_status":report["status"] if report else "UNAVAILABLE",
                      "report_hash":self.last_report_hash,"mapped_symbols":len(mapped),
                      "error":self.last_error},
            "signal_status":report["status"] if report else "UNAVAILABLE",
            "signal_cutoff":report.get("news_cutoff_at") if report else None,
            "signal_generated_at":report.get("generated_at") if report else None,
            "paper_only":True,"execution_enabled":False
        }
