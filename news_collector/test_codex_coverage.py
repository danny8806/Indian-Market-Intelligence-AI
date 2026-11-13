import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from news_collector.codex_coverage import read_ledger, source_batch, record_checks
from news_collector import codex_research as cr
from news_collector.engine import IST


def source(i):
    return dict(name=f'feed {i}', url=f'https://publisher.example/{i}',
                provider='MEDIA', kind='rss', authority='media', enabled=True)


class CodexCoverageTests(unittest.TestCase):
    def test_restart_progress_covers_expanded_registry_in_six_passes(self):
        sources = [source(i) for i in range(108)]
        seen = set()
        with tempfile.TemporaryDirectory() as f:
            for n in range(6):
                ledger = read_ledger(f)
                batch = source_batch(sources, ledger)
                seen.update(s['name'] for s in batch)
                now = (datetime(2026, 11, 13, 0, tzinfo=IST) + timedelta(minutes=30*n)).isoformat()
                checks = [dict(source=s['name'], status='OK', items=3) for s in batch]
                Path(f, 'codex-source-coverage.json').write_text(json.dumps(record_checks(sources, ledger, checks, now)))
            self.assertEqual(seen, {s['name'] for s in sources})

    def test_incomplete_reads_remain_ahead_of_completed_reads(self):
        sources = [source(i) for i in range(25)]
        ledger = record_checks(sources, {}, [dict(source=s['name'], status='OK', items=1) for s in sources[:3]], '2026-11-13T07:00:00+05:30')
        batch = source_batch(sources, ledger)
        self.assertEqual([s['name'] for s in batch], [s['name'] for s in sources[3:23]])
        self.assertIsNone(ledger['feed 3']['attempted_at'])

    def test_changed_endpoint_invalid_ledger_and_new_sources_get_priority(self):
        a, b = source(0), source(1)
        ledger = {a['name']: dict(url='https://old.example/feed', attempted_at='2026-11-13T07:00:00+05:30'),
                  b['name']: dict(attempted_at='invalid')}
        self.assertEqual(source_batch([a, b], ledger), [a, b])
        updated = record_checks([a, b], ledger, [], '2026-11-13T08:00:00+05:30')
        self.assertIsNone(updated[a['name']]['attempted_at'])
        with tempfile.TemporaryDirectory() as f:
            Path(f, 'codex-source-coverage.json').write_text('[]')
            self.assertEqual(read_ledger(f), {})

    def test_success_history_preserved_when_later_source_attempt_fails(self):
        sources = [source(0)]
        first = record_checks(sources, {}, [dict(source='feed 0',status='OK')], '2026-11-13T07:00:00+05:30')
        second = record_checks(sources, first, [dict(source='feed 0',status='ERROR')], '2026-11-13T07:30:00+05:30')
        self.assertEqual(second['feed 0']['last_success_at'], '2026-11-13T07:00:00+05:30')
        self.assertEqual(second['feed 0']['status'], 'ERROR')

    def test_partial_model_failure_keeps_own_news_and_unread_source_pending(self):
        now = datetime(2026,11,13,7,30,tzinfo=IST)
        sources = [source(i) for i in range(25)]
        def model(*args, **kwargs):
            _, spool = cr.FETCH_CONTEXT.get()
            Path(spool).write_text(json.dumps(dict(source=sources[0], observed_at=now.isoformat(), stats=dict(status='OK'), items=[dict(headline='Thermax Limited wins new order',url='https://publisher.example/news',raw_time='2026-11-13T07:00:00+05:30',summary='Publisher reports new order')]))+'\n')
            return 'TIMEOUT', None
        with tempfile.TemporaryDirectory() as f, patch.object(cr, 'run_codex', new=model):
            status, rows = cr.discover(now, {'THERMAX':'Thermax Limited'}, {'THERMAX':'Thermax Limited'}, clock=lambda:now, sources=sources, coverage_root=f)
            self.assertEqual(status, 'COLLECTED')
            self.assertEqual(rows[0]['discoverer'], 'codex_independent_source')
            audit = json.loads(Path(f,'last_codex_run.json').read_text())
            self.assertEqual(audit['assigned'],20)
            self.assertEqual(len(audit['pending']),19)
            self.assertEqual(len(audit['registry_unattempted']),24)
            self.assertEqual(source_batch(sources,read_ledger(f))[0],sources[1])

    def test_more_than_eight_native_search_urls_reach_publisher_processing(self):
        now = datetime(2026,11,13,7,30,tzinfo=IST)
        urls = [f'https://publisher.example/news/{i}' for i in range(12)]
        item = dict(headline='Thermax Limited announces new order',summary='Source report',raw_time='2026-11-13T07:00:00+05:30')
        with patch.object(cr,'allowed_by_robots',return_value=(True,'')), patch.object(cr,'publisher_article',side_effect=lambda u:{**item,'url':u}) as fetch:
            _, rows = cr.verify_links(urls,{'THERMAX':'Thermax Limited'},{'THERMAX':'Thermax Limited'},clock=lambda:now,discoverer='codex_search',sources=[source(0)])
        self.assertEqual(fetch.call_count,12)
        self.assertEqual(len(rows),12)

    def test_expired_article_budget_records_pending_without_starting_fetches(self):
        urls = ['https://publisher.example/news/1']
        with patch.object(cr, 'publisher_article') as fetch:
            _, rows = cr.verify_links(urls, {}, {}, clock=lambda:datetime.now(IST),
                discoverer='codex_search',sources=[source(0)], deadline=0)
        fetch.assert_not_called()
        self.assertEqual(rows, [])
        self.assertEqual(cr.verify_links.last_audit['pending_urls'], urls)

    def test_connected_search_allowed_only_for_fetch_and_unknown_connectors_rejected(self):
        import os
        from types import SimpleNamespace
        for searching,tool,expected in [(True,'search_service.web_run','OK'),(False,'search_service.web_run','UNEXPECTED_TOOL'),(True,'unrelated.execute','UNEXPECTED_TOOL')]:
            with self.subTest(searching=searching,tool=tool), tempfile.TemporaryDirectory() as f:
                root=Path(f);(root/'auth.json').write_text('{}')
                def execute(command,**kw):
                    Path(command[command.index('--output-last-message')+1]).write_text('{"urls":[]}')
                    event=dict(type='item.completed',item=dict(type='mcp_tool_call',server='codex_apps',tool=tool,status='completed'))
                    return SimpleNamespace(returncode=0,stderr='',stdout=json.dumps(event))
                token=cr.FETCH_CONTEXT.set((root/'assignment',root/'spool'))
                try:
                    with patch.dict(os.environ,{'NEWS_CODEX_HOME':f}),patch.object(cr.shutil,'which',return_value='/usr/bin/tool'),patch.object(cr.subprocess,'run',side_effect=execute):
                        status,_=cr._run_codex('prompt',cr.LINKS_SCHEMA,search=searching,timeout=5)
                    self.assertEqual(status,expected)
                finally:cr.FETCH_CONTEXT.reset(token)
