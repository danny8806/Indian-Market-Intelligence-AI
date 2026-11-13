import json,tempfile,unittest
from pathlib import Path
from datetime import datetime
from unittest.mock import patch
from news_collector.engine import IST,parse_timestamp
from news_collector.source_gateway import SourceReader
from news_collector.tool_router import enqueue,heavy_allowed
from news_collector.tool_worker import allowed_target,article,run

class ApprovedToolTests(unittest.TestCase):
    source={'name':'Publisher','url':'https://publisher.example/news','kind':'html','provider':'MEDIA','authority':'media'}
    def test_codex_mcp_gets_only_explicit_private_search_configuration(self):
        import os,tomllib
        from types import SimpleNamespace
        from news_collector.codex_research import _run_codex,FETCH_CONTEXT
        with tempfile.TemporaryDirectory() as f:
            root=Path(f);(root/'auth.json').write_text('{}')
            captured={}
            def execute(command,**kw):
                captured.update(command=command,env=kw['env'])
                Path(command[command.index('--output-last-message')+1]).write_text('{}')
                return SimpleNamespace(returncode=0,stderr='',stdout=json.dumps({'type':'item.completed','item':{'type':'mcp_tool_call','server':'news_reader','tool':'read_source','status':'completed'}}))
            token=FETCH_CONTEXT.set((root/'assignment',root/'spool'))
            try:
                with patch.dict(os.environ,{'NEWS_CODEX_HOME':f,'NEWS_SEARXNG_URL':'http://news-search:8080','NEWS_DATABASE_URL':'secret-test-value','KOTAK_NEO_MPIN':'secret-test-value'}),patch('news_collector.codex_research.shutil.which',return_value='/usr/bin/tool'),patch('news_collector.codex_research.subprocess.run',side_effect=execute):
                    self.assertEqual(_run_codex('prompt',{},search=True,timeout=10)[0],'OK')
            finally:FETCH_CONTEXT.reset(token)
            config=next(x for x in captured['command'] if x.startswith('mcp_servers.news_reader='))
            self.assertEqual(tomllib.loads(config)['mcp_servers']['news_reader']['env'],{'NEWS_SEARXNG_URL':'http://news-search:8080'})
            self.assertNotIn('NEWS_DATABASE_URL',captured['env']);self.assertNotIn('KOTAK_NEO_MPIN',captured['env'])
    def test_reader_saves_every_original_item_and_reads_independently_once(self):
        calls=[]
        items=[{'headline':f'actual fetched item {i}','url':f'https://publisher.example/{i}','raw_time':'2026-11-11T08:00:00+05:30'} for i in range(60)]
        def fetch(s):calls.append(s);return {'status':'OK'},items
        with tempfile.TemporaryDirectory() as f:
            path=Path(f)/'spool';reader=SourceReader([self.source],path,fetch=fetch)
            self.assertEqual(reader.read('0')['item_count'],60);reader.read('0')
            self.assertEqual(len(calls),1)
            self.assertEqual(len(json.loads(path.read_text())['items']),60)
            with self.assertRaises(ValueError):reader.read('https://arbitrary.example')
    def test_reader_records_source_failure_without_fabricated_news(self):
        with tempfile.TemporaryDirectory() as f:
            path=Path(f)/'spool';reader=SourceReader([self.source],path,fetch=lambda s:(_ for _ in ()).throw(TimeoutError()))
            self.assertEqual(reader.read('0')['status'],'ERROR')
            self.assertEqual(json.loads(path.read_text())['items'],[])
    def test_source_snapshot_updates_atomically_and_keeps_task_identity(self):
        with tempfile.TemporaryDirectory() as f:
            enqueue(f,self.source,'monitor',raw=b'old');enqueue(f,self.source,'monitor',raw=b'new')
            tasks=list((Path(f)/'tool_queue').glob('*.json'));self.assertEqual(len(tasks),1)
            task=json.loads(tasks[0].read_text());self.assertEqual(Path(task['blob']).read_bytes(),b'new')
            self.assertEqual(task['next_at'],0)
    def test_morning_heavy_work_yields_while_collection_clock_can_continue(self):
        for h,m,expected in [(7,54,True),(7,55,False),(8,0,False),(8,30,False),(8,55,False),(9,0,False),(9,29,False),(9,30,True)]:
            self.assertEqual(heavy_allowed(datetime(2026,11,11,h,m,tzinfo=IST)),expected)
        self.assertTrue(heavy_allowed(datetime(2026,11,14,9,0,tzinfo=IST)))
    def test_browser_fallback_never_runs_after_robots_denial(self):
        with tempfile.TemporaryDirectory() as f:
            p=Path(f)/'page';p.write_bytes(b'<h1>publisher</h1>')
            with patch('news_collector.broker_sources.allowed_by_robots',return_value=(False,'denied')),patch('news_collector.tool_worker.render') as render:
                with self.assertRaises(ValueError):run({'source':self.source,'kind':'render','url':self.source['url'],'blob':str(p)})
            render.assert_not_called()
    def test_source_tool_rejects_private_or_unassigned_urls(self):
        for url in ['https://127.0.0.1/x','http://publisher.example/x','https://other.example/x','https://publisher.example:8080/x']:
            self.assertFalse(allowed_target(url,self.source))
    def test_source_denial_stops_renderer_switching(self):
        from news_collector.tool_worker import SourceDenied
        with tempfile.TemporaryDirectory() as f:
            p=Path(f)/'page';p.write_bytes(b'<html>source</html>')
            with patch('news_collector.broker_sources.allowed_by_robots',return_value=(True,'')),patch('news_collector.tool_worker.render',side_effect=SourceDenied('denied')) as renderer:
                with self.assertRaises(SourceDenied):run({'source':self.source,'kind':'render','url':self.source['url'],'blob':str(p)})
            self.assertEqual(renderer.call_count,1)
    def test_article_keeps_source_time_without_fetch_time_guess(self):
        raw=b'<html><h1>Company publishes a current source announcement</h1><article><time datetime="2026-11-11T08:40:00+05:30"></time><p>Actual context from the supplied publisher page.</p></article></html>'
        row=article(raw,self.source['url'])[0];self.assertEqual(row['raw_time'],'2026-11-11T08:40:00+05:30')
        self.assertEqual(article(raw.replace(b'datetime=',b'data-unrecognized='),self.source['url'])[0]['raw_time'],'')
    def test_explicit_zone_does_not_confuse_year_with_utc_offset(self):
        self.assertEqual(parse_timestamp('05-Nov-2026 18:02:00',exchange='NSE').hour,18)
        self.assertEqual(parse_timestamp('11 Nov 2026 08:45 IST').hour,8)
        self.assertIsNone(parse_timestamp('11 Nov 2026'))
        self.assertIsNone(parse_timestamp('11 Nov 2026 08:45'))

if __name__=='__main__':unittest.main()
