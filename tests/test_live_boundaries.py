import unittest
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from live.kotak_orders import LiveOrderIntent, submit_live_order
from live.orb import direct_cross, opening_range_from_response


class LiveBoundaryTests(unittest.TestCase):
    def test_dhan_opening_range_requires_audited_timestamp_mode(self):
        epoch = int(datetime(2026, 11, 5, 9, 15, tzinfo=ZoneInfo("Asia/Kolkata")).timestamp())
        data = {"timestamp": [epoch], "open": [100], "high": [102], "low": [99],
                "close": [101], "volume": [1000]}
        with self.assertRaises(ValueError):
            opening_range_from_response(data, "123", date(2026, 11, 5), timestamp_mode="unknown")
        opening = opening_range_from_response(data, "123", date(2026, 11, 5), timestamp_mode="start")
        self.assertEqual(opening.high, Decimal("102"))
        self.assertTrue(direct_cross(Decimal("102"), Decimal("102.05"), opening, "LONG"))
        self.assertFalse(direct_cross(Decimal("102.01"), Decimal("102.05"), opening, "LONG"))

    def test_kotak_submission_requires_risk_gate(self):
        class Client:
            def place_order(self, **kwargs):
                return kwargs
        intent = LiveOrderIntent("ABC-EQ", "LONG", 10, Decimal("100"), "session-unique-tag")
        with self.assertRaises(PermissionError):
            submit_live_order(Client(), intent, risk_approved=False)
        result = submit_live_order(Client(), intent, risk_approved=True)
        self.assertEqual(result["trading_symbol"], "ABC-EQ")
        self.assertEqual(result["transaction_type"], "B")


if __name__ == "__main__":
    unittest.main()
