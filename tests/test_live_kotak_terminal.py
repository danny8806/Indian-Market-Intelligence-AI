"""Live-only trading terminal safety tests.

All test data is mocked inside the test runner. No actual Kotak Neo order
is submitted and no research signals are published.
"""
from __future__ import annotations
import os
import tempfile
import unittest
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from bridge.app import create_app
from live_desk.app import create_live_app
from live_desk.broker_view import positions as parse_positions
from live_desk.kotak_instruments import KotakInstrument
from live_desk.ledger import LiveLedger
from live_desk.runtime import LiveRuntime
from live_desk.strategy import LivePolicy, candidate_entry
from live_desk.supervisor import LiveSupervisor

IST=ZoneInfo("Asia/Kolkata")
TODAY=datetime(2026,11,4,9,18,tzinfo=IST)
TOKEN="this-is-a-strong-bridge-test-secret-012345"
PASSWORD="TestPassword-Strong-2026"
SESSION="this-is-a-separate-session-key-more-than-thirtytwo"


class FakeBroker:
    def __init__(self):
        self.order_calls=0
    def positions(self):
        return {"stat":"Ok","data":[{"exSeg":"nse_cm","trdSym":"TESTA-EQ",
            "cfBuyQty":0,"flBuyQty":3,"cfSellQty":0,"flSellQty":0,
            "buyAmt":"300","cfBuyAmt":"0","sellAmt":"0","cfSellAmt":"0","prod":"MIS"}]}
    def order_report(self):
        return {"stat":"Ok","data":[]}
    def trade_report(self):
        return {"stat":"Ok","data":[]}
    def limits(self):
        # Official kotakneoapi v3 signature, no legacy filter arguments.
        return {"stat":"Ok","Net":"1500000"}
    def place_order(self, **kwargs):
        self.order_calls+=1
        raise AssertionError("Real order must never be submitted in this test")


class LiveTerminalTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env=patch.dict(os.environ,{"LIVE_ORDERS_ALLOWED":"NO",
             "DASHBOARD_COOKIE_SECURE":"false"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.broker=FakeBroker()
        self.clock=lambda:TODAY
        self.bridge=create_app(
            database_url="sqlite:///"+str(Path(self.tmp.name)/"news.db"),
            bearer_token=TOKEN,now_provider=self.clock)
        self.addCleanup(self.bridge.state.engine.dispose)
        self.supervisor=LiveSupervisor(self.bridge.state.engine,
            ledger_path=Path(self.tmp.name)/"orders.db",
            clock=self.clock,kotak_factory=lambda:self.broker)
        self.app=create_live_app(database_url="sqlite:///"+str(Path(self.tmp.name)/"news.db"),
            bearer_token=TOKEN,dashboard_password=PASSWORD,
            session_secret=SESSION,supervisor=self.supervisor,
            clock=self.clock,start_supervisor=False)
        self.addCleanup(self.app.state.engine.dispose)
        self.client=TestClient(self.app)

    def login(self):
        response=self.client.post("/api/auth/login",json={"password":PASSWORD})
        self.assertEqual(response.status_code,200,response.text)

    def test_login_required_for_broker_books(self):
        for path in ("/","/api/state","/api/live/orders","/api/live/positions","/api/live/fills"):
            with self.subTest(path=path):
                response=self.client.get(path,follow_redirects=False)
                self.assertIn(response.status_code,(303,401))
        self.assertEqual(self.client.get("/static/app.js").status_code,200)

    def test_login_and_real_only_dashboard(self):
        self.login()
        page=self.client.get("/")
        self.assertEqual(page.status_code,200)
        self.assertIn("LIVE Kotak positions",page.text)
        self.assertNotIn("Paper positions",page.text)
        self.assertNotIn("paper engine",page.text.lower())
        state=self.client.get("/api/state").json()
        self.assertEqual(state["mode"],"LIVE_KOTAK_NEO_ONLY")
        self.assertFalse(state["armed"])
        self.assertFalse(state["orders_permitted_by_server"])
        self.assertEqual(state["signal_status"],"UNAVAILABLE")

    def test_kotak_books_available_without_news_but_orders_blocked(self):
        self.supervisor.cycle()
        self.login()
        r=self.client.get("/api/live/positions")
        self.assertEqual(r.status_code,200)
        rows=r.json()["positions"]
        self.assertEqual(rows[0]["net_quantity"],3)
        self.assertIsNone(rows[0]["gross_mark_to_market"])
        self.assertFalse(self.client.get("/api/state").json()["armed"])
        self.assertEqual(self.broker.order_calls,0)

    def test_live_order_arming_rejected_by_default(self):
        self.supervisor.cycle()
        self.login()
        r=self.client.post("/api/live/arm",headers={"Origin":"http://testserver"},
            json={"acknowledgement":"I AUTHORIZE LIVE KOTAK ORDERS","totp":"123456"})
        self.assertIn(r.status_code,(403,409))
        self.assertEqual(self.broker.order_calls,0)

    def test_cross_origin_live_action_rejected(self):
        self.login()
        r=self.client.post("/api/live/disarm",headers={"Origin":"https://evil.example"})
        self.assertEqual(r.status_code,403)
        self.assertFalse(self.supervisor.armed)

    def test_websocket_rejects_cross_origin_even_with_login_cookie(self):
        self.login()
        with self.assertRaises(WebSocketDisconnect) as caught:
            with self.client.websocket_connect("/ws", headers={"Origin":"https://evil.example"}):
                pass
        self.assertEqual(caught.exception.code, 4403)

    def test_websocket_accepts_same_origin_after_login(self):
        self.login()
        with self.client.websocket_connect("/ws", headers={"Origin":"http://testserver"}) as ws:
            self.assertEqual(ws.receive_json()["mode"], "LIVE_KOTAK_NEO_ONLY")

    def test_missing_news_never_triggers_kotak_order(self):
        self.supervisor.cycle()
        self.assertIsNone(self.supervisor.runtime)
        self.assertEqual(self.broker.order_calls,0)

    def test_missing_kotak_configuration_is_quiet_and_disarmed(self):
        keys=("KOTAK_NEO_CONSUMER_KEY","KOTAK_NEO_MOBILE_NUMBER","KOTAK_NEO_UCC",
              "KOTAK_NEO_MPIN","KOTAK_NEO_TOTP_SECRET")
        with patch.dict(os.environ,{key:"" for key in keys}):
            desk=LiveSupervisor(self.bridge.state.engine,
                ledger_path=Path(self.tmp.name)/"unconfigured-orders.db",clock=self.clock)
            desk.cycle()
        self.assertEqual(desk.status,"NEEDS_KOTAK_CREDENTIALS")
        self.assertEqual(desk.snapshot()["supervisor_status"],"NEEDS_KOTAK_CREDENTIALS")
        self.assertIsNone(desk.error)
        self.assertIsNone(desk.broker)
        self.assertFalse(desk.armed)

    def test_operator_disarm_clears_entry_gate(self):
        self.supervisor.armed=True
        self.supervisor.disarm("Test")
        self.assertFalse(self.supervisor.armed)
        self.assertEqual(self.broker.order_calls,0)

    def test_market_position_parse_without_price_does_not_fabricate_mtm(self):
        result=parse_positions(self.broker,{})
        self.assertEqual(result[0]["side"],"LONG")
        self.assertIsNone(result[0]["gross_mark_to_market"])

    def test_live_policy_has_no_implicit_daily_loss_limit(self):
        self.assertFalse(hasattr(self.supervisor,"loss_cap"))

    def test_old_dhan_quote_never_generates_live_mtm(self):
        self.supervisor.session_date=TODAY.date().isoformat()
        self.supervisor.broker=self.broker
        self.supervisor.quote_data={"TESTA":{
            "ltp":125,"tick_at":"2026-11-04T09:00:00+05:30"}}
        self.supervisor.refresh_broker()
        self.assertEqual(len(self.supervisor.broker_positions),1)
        self.assertIsNone(self.supervisor.broker_positions[0]["gross_mark_to_market"])
        self.assertEqual(self.broker.order_calls,0)

    def test_broker_status_includes_real_books_only(self):
        self.supervisor.cycle()
        snapshot=self.supervisor.snapshot()
        self.assertEqual(snapshot["positions"][0]["symbol"],"TESTA")
        self.assertEqual(snapshot["orders"],[])
        self.assertEqual(snapshot["fills"],[])
        self.assertFalse(snapshot["armed"])

    def test_unarmed_exit_at_eod_cannot_call_broker(self):
        class Guard:
            def exit_due(self,at):
                raise AssertionError("Unarmed exit must not submit orders")
        self.supervisor.allowed=True
        self.supervisor.runtime=Guard()
        self.supervisor.session_authorized=False
        self.supervisor._manage_authorized_exits(TODAY.replace(hour=15,minute=20))
        self.assertEqual(self.broker.order_calls,0)


class KotakOrderSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ledger=LiveLedger(Path(self.tmp.name)/"live.db")
        self.policy=LivePolicy(time(10),time(15,15),5,5,
            Decimal("100000"),Decimal("1000000"),"start")

    def runtime(self,enabled=False):
        return LiveRuntime(
            session_date=date(2026,11,4),
            signals=[{"symbol":"TESTA","side":"LONG"}],
            dhan_ids={"TESTA":"123"},
            kotak_instruments={"TESTA":KotakInstrument("TESTA","TESTA-EQ","456")},
            opening_ranges={"TESTA":(Decimal("100"),Decimal("95"))},
            policy=self.policy,ledger=self.ledger,
            broker=FakeBroker(),enabled=enabled,clock=lambda:TODAY)

    def test_disabled_runtime_never_calls_broker(self):
        runtime=self.runtime(False)
        self.assertIsNone(runtime.on_tick({"symbol":"TESTA","ltp":100,"timestamp":TODAY}))
        self.assertIsNone(runtime.on_tick({"symbol":"TESTA","ltp":101,"timestamp":TODAY}))
        self.assertEqual(runtime.broker.order_calls,0)
        self.assertEqual(self.ledger.snapshot(TODAY.date()),[])

    def test_invalid_or_stale_tick_ignored(self):
        runtime=self.runtime(False)
        for bad in ({"symbol":"TESTA","ltp":-1,"timestamp":TODAY},
                    {"symbol":"TESTA","ltp":100,"timestamp":TODAY.replace(minute=10)},
                    {"symbol":"WRONG","ltp":100,"timestamp":TODAY}):
            self.assertIsNone(runtime.on_tick(bad))
        self.assertEqual(runtime.broker.order_calls,0)

    def test_long_breakout_uses_real_ticks_and_notional_cap(self):
        args=dict(side="LONG",previous_price=Decimal("100"),price=Decimal("101"),
             orb_high=Decimal("100"),orb_low=Decimal("95"),tick_at=TODAY,
             policy=self.policy,open_long=0,open_short=0,reserved_gross=Decimal(0))
        self.assertEqual(candidate_entry(**args),990)
        self.assertIsNone(candidate_entry(**{**args,"open_long":5}))
        self.assertIsNone(candidate_entry(**{**args,"tick_at":TODAY.replace(hour=10)}))

    def test_direct_cross_requires_price_to_move_through_orb_edge(self):
        base=dict(orb_high=Decimal("100"),orb_low=Decimal("95"),tick_at=TODAY,
            policy=self.policy,open_long=0,open_short=0,reserved_gross=Decimal(0))
        long={**base,"side":"LONG"}
        self.assertIsNone(candidate_entry(**{**long,"previous_price":Decimal("99"),"price":Decimal("100")}))
        self.assertIsNotNone(candidate_entry(**{**long,"previous_price":Decimal("100"),"price":Decimal("100.01")}))
        short={**base,"side":"SHORT"}
        self.assertIsNone(candidate_entry(**{**short,"previous_price":Decimal("96"),"price":Decimal("95")}))
        self.assertIsNotNone(candidate_entry(**{**short,"previous_price":Decimal("95"),"price":Decimal("94.99")}))

    def test_durable_intent_rejects_duplicate_entry(self):
        args=dict(session_date=TODAY.date(),symbol="TESTA",side="BUY",
                  quantity=10,reference_price=Decimal("100"),at=TODAY,
                  max_per_side=5,gross_cap=Decimal("100000"))
        first=self.ledger.reserve_entry(**args)
        self.assertTrue(first)
        self.assertIsNone(self.ledger.reserve_entry(**args))
        self.ledger.mark_submission_unknown(first["tag"],TODAY)
        with self.assertRaises(ValueError):
            self.ledger.mark_submission_unknown(first["tag"],TODAY)


if __name__=="__main__":
    unittest.main()
