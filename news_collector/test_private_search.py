import json,os,unittest
from unittest.mock import patch,Mock
from news_collector.index_discovery import search_index_available,searx_base,fetch_search_index,search_index_items

class PrivateSearchTests(unittest.TestCase):
    def test_accept_only_named_private_endpoint(self):
        for url in ['https://outside.example','http://127.0.0.1:8080','http://u:p@news-search:8080','http://news-search:8080/path','http://news-search:8080?token=x']:
            with patch.dict(os.environ,{'SERPER_API_KEY':'','NEWS_SEARXNG_URL':url}):
                self.assertEqual(searx_base(),'');self.assertFalse(search_index_available())
        with patch.dict(os.environ,{'SERPER_API_KEY':'','NEWS_SEARXNG_URL':'http://news-search:8080'}):
            self.assertTrue(search_index_available())

    def test_search_dates_never_become_publication_times(self):
        payload={'results':[{'url':'https://publisher.example/item','title':'Actual publisher headline','content':'Source snippet','publishedDate':'2026-11-11T08:00:00Z'}]}
        response=Mock(status_code=200,content=json.dumps(payload).encode());response.json.return_value=payload
        source={'search_query':'site:publisher.example news','allowed_domains':['publisher.example']}
        with patch.dict(os.environ,{'SERPER_API_KEY':'','NEWS_SEARXNG_URL':'http://news-search:8080'}):
            with patch('news_collector.index_discovery.requests.get',return_value=response) as get:
                raw=fetch_search_index(source)
        self.assertNotIn(b'publishedDate',raw)
        self.assertEqual(search_index_items(raw,source)[0]['raw_time'],'')
        self.assertFalse(get.call_args.kwargs['allow_redirects'])

    def test_foreign_hosts_still_rejected(self):
        raw=json.dumps({'organic':[{'link':'https://elsewhere.example/story','title':'Foreign domain source headline'}]}).encode()
        self.assertEqual(search_index_items(raw,{'allowed_domains':['publisher.example']}),[])

    def test_private_redirects_rejected(self):
        response=Mock(status_code=302,content=b'')
        with patch.dict(os.environ,{'SERPER_API_KEY':'','NEWS_SEARXNG_URL':'http://news-search:8080'}):
            with patch('news_collector.index_discovery.requests.get',return_value=response):
                with self.assertRaises(ValueError):fetch_search_index({'search_query':'actual source query'})
