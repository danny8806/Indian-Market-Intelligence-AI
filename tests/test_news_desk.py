"""Contract tests for model-free dashboard, direct signal API and paper trade lifecycle.

All prices and events are synthetic. The test touches no real brokerage,
exchange feed, shared deployment, or existing paper ledger.
"""
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from desk.app import create_desk_app
from desk.engine import PaperLedger, stop_level

IST=ZoneInfo("Asia/Kolkata")
TOKEN="test-signal-token-at-least-thirtytwo-characters"
PASSWORD="test-dashboard-password"
SECRET="dashboard-session-secret-more-than-32-characters"


class DummyDataClient:
    token="synthetic-test-only-token"


class NewsDeskTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        db=Path(self.tmp.name)
        self.clock=[datetime(2026,11,4,9,5,tzinfo=IST)]
        self.app=create_desk_app(
            database_url="sqlite:///"+(db/"api.db").as_posix(),
            bearer_token=TOKEN,
            dashboard_password=PASSWORD,
            session_secret=SECRET,
            ledger=PaperLedger(db/"paper.db"),
            clock=lambda:self.clock[0],
            data_client=DummyDataClient(),
            start_engine=False,
        )
        self.addCleanup(self.app.state.engine.dispose)
        self.client=TestClient(self.app)
        self.headers={"Authorization":"Bearer "+TOKEN,"Idempotency-Key":"2026-11-04-news-research-v1"}
        self.report={
            "schema_version":"1.0","status":"READY",
            "market":"NSE","timezone":"Asia/Kolkata","session_date":"2026-11-04",
            "news_cutoff_at":"2026-11-04T09:00:00+05:30",
            "generated_at":"2026-11-04T09:01:00+05:30",
            "execution_enabled":False,
            "signals":[{
                "symbol":"TESTA","side":"LONG","rank":1,
                "news_summary":"Synthetic strong contract announcement used for tests only.",
                "reason":"Synthetic event deliberately created for automated contract tests.",
                "first_available_at":"2026-11-04T08:00:00+05:30",
                "sources":[{"title":"Synthetic test source link; not a real filing",
                             "url":"https://www.nseindia.com/companies-listing/corporate-filings-announcements",
                             "published_at":"2026-11-04T08:00:00+05:30"}]
            }]
        }

    def login(self):
        with patch.dict("os.environ",{"DASHBOARD_COOKIE_SECURE":"false"}):
            r=self.client.post("/api/auth/login",json={"password":PASSWORD})
        self.assertEqual(r.status_code,200)
        return r

    def receive(self):
        r=self.client.post("/api/v1/signals/incoming",headers=self.headers,json=self.report)
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()["status"],"ACCEPTED")
        self.app.state.news_engine.refresh_report()
        return r

    def test_dashboard_auth_and_source_asset_present(self):
        self.assertEqual(self.client.get("/api/state").status_code,401)
        self.assertEqual(self.client.get("/",follow_redirects=False).status_code,303)
        self.assertEqual(self.client.get("/static/app.js").status_code,200)
        self.login()
        self.assertEqual(self.client.get("/").status_code,200)
        self.assertIn("NEWS SIGNAL",self.client.get("/").text)

    def test_no_incoming_signal_fails_closed(self):
        self.login()
        state=self.client.get("/api/state").json()
        self.assertEqual(state["symbols"],[])
        self.assertFalse(state["strategy"]["runtime_ready"])
        self.assertFalse(state["execution_enabled"])
        self.assertEqual(state["signal_status"],"UNAVAILABLE")
        self.assertEqual(self.client.post("/api/paper/toggle").status_code,409)

    def test_direct_api_supplies_dashboard_not_model(self):
        self.receive()
        self.login()
        st=self.client.get("/api/state").json()
        self.assertEqual([s["symbol"] for s in st["symbols"]],["TESTA"])
        self.assertEqual(st["symbols"][0]["signal"],"BUY")
        self.assertEqual(st["strategy"]["positions"][0]["side"],"LONG")
        self.assertEqual(st["strategy"]["positions"][0]["rank"],1)
        self.assertEqual(st["signal_status"],"READY")
        self.assertFalse(st["execution_enabled"])
        self.assertFalse(st["strategy"]["runtime_ready"]) # no Dhan mapping yet
        news=self.client.get("/api/news/signals").json()
        self.assertEqual(news["signals"][0]["sources"][0]["title"],
                         "Synthetic test source link; not a real filing")
        self.assertEqual(self.client.get("/api/trades").json()["total"],0)

    def test_paper_entry_and_2pct_stop_no_broker_calls(self):
        self.receive()
        paper=self.app.state.news_engine
        paper.mapping={"TESTA":"12345"}
        paper.mapping_date="2026-11-04"
        paper.auth.snapshot=lambda:{"state":"AUTHENTICATED","message":"Synthetic test auth"}
        self.login()
        self.assertTrue(self.client.post("/api/paper/toggle").json()["paper_enabled"])
        self.clock[0]=datetime(2026,11,4,9,16,tzinfo=IST)
        paper.on_tick({"symbol":"TESTA","ltp":100.0,"timestamp":self.clock[0],"source":"TEST"})
        paper.attempt_paper_entries()
        paper.attempt_paper_entries()
        rows=paper.store.rows()
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["side"],"LONG")
        self.assertEqual(rows[0]["quantity"],1000)
        self.assertEqual(rows[0]["stop_price"],98.0)
        self.clock[0]=datetime(2026,11,4,9,17,tzinfo=IST)
        paper.on_tick({"symbol":"TESTA","ltp":97.5,"timestamp":self.clock[0],"source":"TEST"})
        closed=paper.store.rows()[0]
        self.assertEqual(closed["status"],"CLOSED")
        self.assertEqual(closed["gross_pnl"],-2500.0)
        self.assertEqual(closed["exit_reason"],"PAPER_STOP_LTP")
        paper.attempt_paper_entries()
        self.assertEqual(len(paper.store.rows()),1)
        self.assertEqual(self.client.get("/api/trades").json()["total"],1)

    def test_short_paper_stop_uses_adverse_move(self):
        self.report["signals"][0]["side"] = "SHORT"
        self.receive()
        paper = self.app.state.news_engine
        paper.mapping = {"TESTA": "12345"}
        paper.mapping_date = "2026-11-04"
        paper.auth.snapshot = lambda: {"state": "AUTHENTICATED"}
        paper.store.toggle()
        self.clock[0] = datetime(2026,11,4,9,16,tzinfo=IST)
        paper.on_tick({"symbol":"TESTA","ltp":100.0,
                       "timestamp":self.clock[0],"source":"TEST"})
        paper.attempt_paper_entries()
        t=paper.store.rows()[0]
        self.assertEqual((t["side"],t["stop_price"]),("SHORT",102.0))
        self.clock[0] = datetime(2026,11,4,9,17,tzinfo=IST)
        paper.on_tick({"symbol":"TESTA","ltp":102.4,
                       "timestamp":self.clock[0],"source":"TEST"})
        t=paper.store.rows()[0]
        self.assertEqual(t["status"],"CLOSED")
        self.assertEqual(t["exit_reason"],"PAPER_STOP_LTP")
        self.assertAlmostEqual(t["gross_pnl"],-2400.0,places=3)

    def test_stale_tick_rejected_no_fill(self):
        self.receive()
        paper=self.app.state.news_engine
        paper.mapping={"TESTA":"12345"}
        paper.mapping_date="2026-11-04"
        paper.auth.snapshot=lambda:{"state":"AUTHENTICATED"}
        paper.store.toggle()
        self.clock[0]=datetime(2026,11,4,9,17,tzinfo=IST)
        paper.on_tick({"symbol":"TESTA","ltp":100.0,
                       "timestamp":datetime(2026,11,4,9,14,tzinfo=IST),"source":"TEST"})
        paper.attempt_paper_entries()
        self.assertEqual(len(paper.store.rows()),0)

    def test_directional_stop_levels(self):
        self.assertEqual(stop_level(100,"LONG",2),98)
        self.assertEqual(stop_level(100,"SHORT",2),102)


if __name__=="__main__":
    unittest.main()
