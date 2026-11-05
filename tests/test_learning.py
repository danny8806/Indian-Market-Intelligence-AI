"""Local deterministic tests never call Yahoo or any broker."""
import csv
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from learning.feedback import append_csv, audit, evaluate
from learning.train import train

DAY = date(2026, 11, 5)
SRC = {"url": "https://example.org/filing", "title": "Real-file test fixture",
       "published_at": "2026-11-04T18:00:00+05:30"}


def make_signal(side="SHORT", symbol="TEST"):
    return {"symbol": symbol, "side": side, "rank": 1,
            "reason": "Strong negative quarterly earnings surprise",
            "news_summary": "Weak profitability with negative guidance and margins",
            "first_available_at": "2026-11-04T18:00:00+05:30", "sources": [SRC]}


def bars():
    return [{"date": "2026-11-04", "open": 100, "high": 102, "low": 97,
             "close": 100, "volume": 10000, "split": 0},
            {"date": "2026-11-05", "open": 105, "high": 108, "low": 90,
             "close": 95, "volume": 20000, "split": 0}]


class AuditTests(unittest.TestCase):
    def test_short_gain_and_long_loss(self):
        short = evaluate(make_signal("SHORT"), DAY, bars())
        long = evaluate(make_signal("LONG"), DAY, bars())
        self.assertAlmostEqual(short["trade_return_pct"], 9.52381, places=4)
        self.assertAlmostEqual(long["trade_return_pct"], -9.52381, places=4)
        self.assertAlmostEqual(short["opening_gap_pct"], 5.0)
        self.assertEqual(short["won"], 1)

    def test_invalid_split_and_bar_fail_closed(self):
        p = bars()
        p[1]["split"] = 2
        with self.assertRaisesRegex(ValueError, "split"):
            evaluate(make_signal(), DAY, p)
        p = bars()
        p[1]["high"] = 94
        with self.assertRaisesRegex(ValueError, "OHLC"):
            evaluate(make_signal(), DAY, p)

    def test_append_idempotent_no_rewrite(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / "trades.csv"
            x = evaluate(make_signal(), DAY, bars())
            self.assertEqual(append_csv(p, [x]), 1)
            self.assertEqual(append_csv(p, [x]), 0)
            y = dict(x)
            y["trade_return_pct"] = 23.2
            with self.assertRaisesRegex(ValueError, "Historical price changed"):
                append_csv(p, [y])
            z = dict(x)
            z["source_hash"] = "changed"
            with self.assertRaisesRegex(ValueError, "Morning signal changed"):
                append_csv(p, [z])
            with p.open(newline="") as f:
                self.assertEqual(len(list(csv.DictReader(f))), 1)

    def test_daily_audit_and_missing_prices(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            d = root / "signals/incoming"
            d.mkdir(parents=True)
            signals = [make_signal("SHORT", "TEST"), make_signal("LONG", "TEST2")]
            payload = {"schema_version": "1.0", "status": "READY", "market": "NSE",
                       "timezone": "Asia/Kolkata", "session_date": DAY.isoformat(),
                       "news_cutoff_at": "2026-11-05T09:00:00+05:30",
                       "generated_at": "2026-11-05T09:01:00+05:30",
                       "execution_enabled": False, "signals": signals}
            (d / f"{DAY}.json").write_text(json.dumps(payload))
            def price(sym, day):
                if sym == "TEST2":
                    raise RuntimeError("rate limited")
                return bars()
            result = audit(DAY, root, price)
            self.assertEqual(result["data_status"], "PARTIAL_NOT_A_PORTFOLIO_RESULT")
            self.assertIsNone(result["daily_equal_weight_return_pct"])
            self.assertEqual(result["priced"], 1)
            good = audit(DAY, root, lambda sym, day: bars())
            self.assertEqual(good["data_status"], "COMPLETE_YAHOO_ONLY")
            self.assertAlmostEqual(good["daily_equal_weight_return_pct"], 0)
            self.assertEqual(good["wins"], 1)
            self.assertEqual(good["losses"], 1)

    def test_no_training_without_data(self):
        with tempfile.TemporaryDirectory() as temp:
            result = train(Path(temp) / "missing.csv", Path(temp) / "out")
            self.assertEqual(result["status"], "INSUFFICIENT_DATA")


if __name__ == "__main__":
    unittest.main()
