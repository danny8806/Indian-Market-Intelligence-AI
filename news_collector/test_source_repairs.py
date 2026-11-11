import json,unittest
from unittest.mock import patch
from news_collector.broker_sources import listing_items,research_json_items
from news_collector.engine import fetch_one
class SourceRepairTests(unittest.TestCase):
    def test_pdf_title_uses_filename_not_uploads_directory(self):
        source={'url':'https://www.kotakneo.com/fundamental-research-report/morning-insights/','article_path':r'/uploads/Morning_Insight[^/]*\.pdf','fallback_slug':True}
        rows=listing_items(b'<a href="/uploads/Morning_Insight_06_11_2026.pdf">Download pdf</a>',source)
        self.assertEqual(len(rows),1);self.assertIn('Morning Insight',rows[0]['headline']);self.assertEqual(rows[0]['raw_time'],'')
    def test_research_index_rejects_foreign_or_credentialed_urls(self):
        source={'document_hosts':['cdn.broker.test'],'article_path':r'/ResearchReport/\d{8}/Company/\d+\.pdf'}
        base={'reportTitle':'Company quarterly research report','reportDate':'2025-12-11T00:00:00'}
        data={'data':[{**base,'pdfFileName':'https://cdn.broker.test/ResearchReport/11122025/Company/1.pdf'},
                      {**base,'pdfFileName':'https://evil.test/ResearchReport/11122025/Company/2.pdf'},
                      {**base,'pdfFileName':'https://u:p@cdn.broker.test/ResearchReport/11122025/Company/3.pdf'}]}
        rows=research_json_items(json.dumps(data).encode(),source)
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['raw_time'],'')
    def test_broker_json_still_honors_robots(self):
        source={'name':'Broker research','url':'https://broker.test/index.json','kind':'broker_json','authority':'secondary','provider':'BROKER'}
        with patch('news_collector.engine.allowed_by_robots',return_value=(False,'restricted')):
            with patch('news_collector.engine.read_with_retry') as get:
                state,rows=fetch_one(source)
        self.assertEqual(state['status'],'BLOCKED_ROBOTS');get.assert_not_called();self.assertEqual(rows,[])
