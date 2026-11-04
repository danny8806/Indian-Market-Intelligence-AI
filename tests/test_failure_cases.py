"""Failure-injection tests for the news-signal data contract, dashboard, and publisher.

All candidate symbols and news claims here are synthetic, in memory, and must never
be written to the production signals directory.
"""
import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, time
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
from validate_signals import validate
import publish_signals

spec = importlib.util.spec_from_file_location('dashboard_signal_reader', ROOT / 'dashboard' / 'read_signals.py')
reader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reader)

IST = ZoneInfo('Asia/Kolkata')


def ready_fixture(day='2026-11-03'):
    return {
        'schema_version': '1.0', 'status': 'READY',
        'market': 'NSE', 'timezone': 'Asia/Kolkata',
        'session_date': day,
        'news_cutoff_at': day + 'T09:00:00+05:30',
        'generated_at': day + 'T09:01:00+05:30',
        'execution_enabled': False,
        'signals': [{
            'symbol': 'TESTA', 'side': 'LONG', 'rank': 1,
            'reason': 'Synthetic positive financial report for unit testing.',
            'news_summary': 'This is a fictional event used only in isolated unit tests.',
            'first_available_at': '2026-11-02T16:15:00+05:30',
            'sources': [{
                'url': 'https://www.nseindia.com/companies-listing/corporate-filings-announcements',
                'title': 'Test-only URL, no real event claim',
                'published_at': '2026-11-02T16:15:00+05:30'
            }],
            'confidence': None
        }]
    }


class ValidatorFailureCases(unittest.TestCase):
    def setUp(self):
        self.good = ready_fixture()

    def assert_rejected(self, mutator, message=None):
        payload = copy.deepcopy(self.good)
        mutator(payload)
        with self.assertRaises((ValueError, TypeError, KeyError, AttributeError)) as caught:
            validate(payload)
        if message:
            self.assertIn(message, str(caught.exception))

    def test_baseline_ready_passes_format_only(self):
        validate(copy.deepcopy(self.good))

    def test_reject_unsupported_schema(self):
        self.assert_rejected(lambda p: p.update(schema_version='2.0'), 'schema version')

    def test_reject_missing_fields(self):
        for field in ('schema_version', 'status', 'market', 'timezone',
                      'session_date', 'news_cutoff_at', 'generated_at',
                      'execution_enabled', 'signals'):
            with self.subTest(field=field):
                self.assert_rejected(lambda p: p.pop(field), 'Missing')

    def test_reject_extra_field(self):
        self.assert_rejected(lambda p: p.update(broker_api_key='abc'), 'Unexpected')

    def test_reject_wrong_market_timezone(self):
        for field, value in [('market', 'BSE'), ('timezone', 'UTC')]:
            with self.subTest(field=field):
                self.assert_rejected(lambda p: p.update({field: value}))

    def test_reject_unknown_status(self):
        self.assert_rejected(lambda p: p.update(status='ORDER_NOW'), 'Invalid status')

    def test_reject_live_execution(self):
        self.assert_rejected(lambda p: p.update(execution_enabled=True), 'Live execution')

    def test_reject_sample(self):
        self.assert_rejected(lambda p: p.update(sample=True), 'sample')

    def test_reject_missing_ready_candidates(self):
        self.assert_rejected(lambda p: p.update(signals=[]), 'READY requires')

    def test_reject_candidates_in_no_trade_or_unavailable(self):
        for status in ('NO_TRADE', 'UNAVAILABLE'):
            with self.subTest(status=status):
                self.assert_rejected(lambda p: p.update(status=status, reason='No qualifying candidates'))

    def test_nonready_requires_reason(self):
        self.assert_rejected(lambda p: p.update(status='NO_TRADE', signals=[]), 'reason')

    def test_valid_no_trade_passes(self):
        payload = copy.deepcopy(self.good)
        payload.update(status='NO_TRADE', signals=[], reason='Nothing qualifies today')
        validate(payload)

    def test_reject_wrong_session_when_publishing(self):
        with self.assertRaisesRegex(ValueError, 'differs'):
            validate(self.good, expected_date='2026-11-04')

    def test_reject_bad_session_date(self):
        self.assert_rejected(lambda p: p.update(session_date='2026-02-30'), 'Invalid session')

    def test_reject_wrong_cutoff(self):
        self.assert_rejected(lambda p: p.update(news_cutoff_at='2026-11-03T09:01:00+05:30'), '09:00')

    def test_reject_naive_timestamps(self):
        for field in ('news_cutoff_at', 'generated_at'):
            with self.subTest(field=field):
                self.assert_rejected(lambda p: p.update({field: '2026-11-03T09:00:00'}), 'timezone')

    def test_reject_generated_before_cutoff(self):
        self.assert_rejected(lambda p: p.update(generated_at='2026-11-03T08:59:00+05:30'), 'at or after')

    def test_reject_future_generated(self):
        future = (datetime.now(IST) + timedelta(days=2)).isoformat()
        self.assert_rejected(lambda p: p.update(generated_at=future), 'future')

    def test_reject_late_first_availability(self):
        self.assert_rejected(
            lambda p: p['signals'][0].update(first_available_at='2026-11-03T09:01:00+05:30'),
            'not available'
        )

    def test_reject_late_source_publication(self):
        self.assert_rejected(
            lambda p: p['signals'][0]['sources'][0].update(published_at='2026-11-03T09:01:00+05:30'),
            'after research cutoff'
        )

    def test_reject_no_source(self):
        self.assert_rejected(lambda p: p['signals'][0].update(sources=[]), 'requires a cited source')

    def test_reject_insecure_or_fake_source_url(self):
        for url in ('http://example.org', 'javascript:alert(1)', 'https://example.com/fake', 'https:///bad'):
            with self.subTest(url=url):
                self.assert_rejected(lambda p: p['signals'][0]['sources'][0].update(url=url))

    def test_reject_duplicate_stock_even_opposite_direction(self):
        def mutator(p):
            duplicate = copy.deepcopy(p['signals'][0])
            duplicate.update(side='SHORT', rank=1)
            p['signals'].append(duplicate)
        self.assert_rejected(mutator, 'Duplicate symbol')

    def test_reject_invalid_side(self):
        self.assert_rejected(lambda p: p['signals'][0].update(side='BUY_AND_SELL'), 'Invalid side')

    def test_reject_invalid_or_noncontiguous_rank(self):
        for rank in (0, 2, 6, True, 1.0):
            with self.subTest(rank=rank):
                self.assert_rejected(lambda p: p['signals'][0].update(rank=rank))

    def test_reject_more_than_five_long(self):
        def mutator(p):
            base = p['signals'][0]
            for rank in range(2, 7):
                signal = copy.deepcopy(base)
                signal.update(symbol='TEST' + str(rank), rank=rank)
                p['signals'].append(signal)
        self.assert_rejected(mutator)

    def test_reject_more_than_ten_candidates(self):
        def mutator(p):
            base = p['signals'][0]
            for i in range(2, 12):
                signal = copy.deepcopy(base)
                signal.update(symbol='TEST' + str(i), rank=1)
                p['signals'].append(signal)
        self.assert_rejected(mutator, 'Maximum ten')

    def test_reject_invalid_confidence(self):
        for score in (-0.01, 1.01, '99%', True):
            with self.subTest(score=score):
                self.assert_rejected(lambda p: p['signals'][0].update(confidence=score))

    def test_reject_bad_symbol_or_short_reason(self):
        self.assert_rejected(lambda p: p['signals'][0].update(symbol='INVALID SYMBOL'))
        self.assert_rejected(lambda p: p['signals'][0].update(reason='Good news'))

    def test_nonready_bootstrap_only_if_empty(self):
        p = copy.deepcopy(self.good)
        p.update(status='UNAVAILABLE', session_date=None,
                 news_cutoff_at=None, generated_at=None, signals=[],
                 reason='Awaiting first run')
        validate(p)
        p['signals'] = copy.deepcopy(self.good['signals'])
        with self.assertRaises(ValueError):
            validate(p)


class DashboardFailureCases(unittest.TestCase):
    def setUp(self):
        day = datetime.now(IST).date().isoformat()
        self.p = ready_fixture(day)
        self.p['signals'][0]['first_available_at'] = day + 'T08:00:00+05:30'
        self.p['signals'][0]['sources'][0]['published_at'] = day + 'T08:00:00+05:30'
        self.now = datetime.now(IST).replace(hour=10, minute=0, second=0, microsecond=0)
        self.p['generated_at'] = day + 'T09:01:00+05:30'

    def test_valid_research_only_watchlist(self):
        result = reader.research_watchlist(copy.deepcopy(self.p), now=self.now)
        self.assertEqual(result['status'], 'RESEARCH_ONLY')
        self.assertFalse(result['execution_enabled'])
        self.assertEqual([s['symbol'] for s in result['long']], ['TESTA'])
        self.assertEqual(result['short'], [])

    def test_reject_early_dashboard_access(self):
        early = self.now.replace(hour=8, minute=59)
        with self.assertRaisesRegex(ValueError, 'Before morning'):
            reader.research_watchlist(copy.deepcopy(self.p), now=early)

    def test_reject_previous_day_signal(self):
        stale = copy.deepcopy(self.p)
        old = (self.now.date() - timedelta(days=1)).isoformat()
        stale['session_date'] = old
        stale['news_cutoff_at'] = old + 'T09:00:00+05:30'
        stale['generated_at'] = old + 'T09:01:00+05:30'
        stale['signals'][0]['first_available_at'] = old + 'T08:00:00+05:30'
        stale['signals'][0]['sources'][0]['published_at'] = old + 'T08:00:00+05:30'
        with self.assertRaisesRegex(ValueError, 'Stale session'):
            reader.research_watchlist(stale, now=self.now)

    def test_reject_unavailable_feed(self):
        p = copy.deepcopy(self.p)
        p.update(status='UNAVAILABLE', signals=[], reason='Missing research')
        with self.assertRaisesRegex(ValueError, 'No verified'):
            reader.research_watchlist(p, now=self.now)

    def test_no_trade_remains_non_executable(self):
        p = copy.deepcopy(self.p)
        p.update(status='NO_TRADE', signals=[], reason='No qualifying candidates')
        result = reader.research_watchlist(p, now=self.now)
        self.assertEqual(result['status'], 'NO_TRADE')
        self.assertFalse(result['execution_enabled'])

    def test_reject_unsafe_dashboard_input(self):
        p = copy.deepcopy(self.p)
        p['execution_enabled'] = True
        with self.assertRaisesRegex(ValueError, 'Live execution'):
            reader.research_watchlist(p, now=self.now)

    def test_network_timeout_fails_closed(self):
        with patch.object(reader, 'urlopen', side_effect=URLError('simulated offline')):
            with self.assertRaises(URLError):
                reader.read_payload('https://example.org/test.json', None)


class PublisherFailureCases(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.day = datetime.now(IST).date()
        self.latest = self.root / 'signals' / 'latest.json'
        self.latest.parent.mkdir(parents=True)
        self.latest.write_text('PREVIOUS_GOOD_BYTES', encoding='utf-8')

    def run_publish(self):
        with patch.object(sys, 'argv', ['publish_signals.py', '--root', str(self.root),
                                        '--session-date', self.day.isoformat()]):
            publish_signals.main()

    def incoming(self, payload):
        path = self.root / 'signals' / 'incoming' / (self.day.isoformat() + '.json')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding='utf-8')
        return path

    def test_missing_source_creates_unavailable_not_fake_stock(self):
        self.run_publish()
        payload = json.loads(self.latest.read_text())
        self.assertEqual(payload['status'], 'UNAVAILABLE')
        self.assertEqual(payload['signals'], [])
        self.assertFalse(payload['execution_enabled'])
        archive = self.root / 'signals' / 'archive' / (self.day.isoformat() + '.json')
        self.assertTrue(archive.exists())

    def test_corrupt_json_does_not_replace_latest(self):
        incoming = self.incoming({'x': 1})
        incoming.write_text('{malformed json!!', encoding='utf-8')
        with self.assertRaises(json.JSONDecodeError):
            self.run_publish()
        self.assertEqual(self.latest.read_text(), 'PREVIOUS_GOOD_BYTES')

    def test_wrong_date_does_not_replace_latest(self):
        payload = ready_fixture()
        self.incoming(payload)
        with self.assertRaisesRegex(ValueError, 'differs'):
            self.run_publish()
        self.assertEqual(self.latest.read_text(), 'PREVIOUS_GOOD_BYTES')

    def test_unsafe_live_order_flag_does_not_replace_latest(self):
        p = ready_fixture(self.day.isoformat())
        p['signals'][0]['first_available_at'] = self.day.isoformat() + 'T08:00:00+05:30'
        p['signals'][0]['sources'][0]['published_at'] = self.day.isoformat() + 'T08:00:00+05:30'
        p['execution_enabled'] = True
        self.incoming(p)
        with self.assertRaisesRegex(ValueError, 'Live execution'):
            self.run_publish()
        self.assertEqual(self.latest.read_text(), 'PREVIOUS_GOOD_BYTES')

    def test_source_missing_does_not_replace_latest(self):
        p = ready_fixture(self.day.isoformat())
        p['signals'][0]['sources'] = []
        self.incoming(p)
        with self.assertRaises(ValueError):
            self.run_publish()
        self.assertEqual(self.latest.read_text(), 'PREVIOUS_GOOD_BYTES')

    def test_archive_write_error_preserves_latest(self):
        with patch.object(publish_signals, 'atomic_json', side_effect=OSError('simulated disk failure')):
            with self.assertRaisesRegex(OSError, 'simulated disk'):
                self.run_publish()
        self.assertEqual(self.latest.read_text(), 'PREVIOUS_GOOD_BYTES')

    def test_nonready_incoming_is_non_executable(self):
        p = publish_signals.unavailable(self.day)
        p['reason'] = 'Simulated source feed outage'
        self.incoming(p)
        self.run_publish()
        new = json.loads(self.latest.read_text())
        self.assertEqual(new['status'], 'UNAVAILABLE')
        self.assertEqual(new['signals'], [])
        self.assertFalse(new['execution_enabled'])


if __name__ == '__main__':
    unittest.main()
