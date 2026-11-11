import unittest
from unittest.mock import patch
from types import SimpleNamespace
from news_collector.tool_capabilities import fallback_article_text,fallback_pdf_page


class NativeToolTests(unittest.TestCase):
    def test_article_uses_bytes_only_and_disables_image_fetches(self):
        article=SimpleNamespace(maintext='Publisher text with sufficient visible content for extraction.')
        with patch('newsplease.NewsPlease.from_html',return_value=article) as parse:
            text=fallback_article_text(b'<p>Publisher text</p><script>remote()</script><img src="http://internal/">')
            self.assertTrue(text.startswith('Publisher text'))
            self.assertFalse(parse.call_args.kwargs['fetch_images'])
            self.assertNotIn('<script',parse.call_args.args[0])
            self.assertNotIn('<img',parse.call_args.args[0])
            self.assertNotIn('url',parse.call_args.kwargs)

    def test_article_extractors_fail_closed_without_invented_text(self):
        with patch('newsplease.NewsPlease.from_html',side_effect=ValueError):
            with patch('readability.Document.summary',side_effect=ValueError):
                self.assertEqual(fallback_article_text(b'<html/>'),'')

    def test_pdf_rejects_unsafe_bounds_before_opening(self):
        for raw,page in [(b'not-pdf',0),(b'%PDF-'+b'x'*9_000_000,0),(b'%PDF-',-1),(b'%PDF-',10)]:
            self.assertEqual(fallback_pdf_page(raw,page),'')

    def test_pdf_fallback_uses_requested_page_only(self):
        doc=SimpleNamespace(needs_pass=False)
        page=SimpleNamespace(get_text=lambda:'Recovered source PDF text')
        class FakeDoc:
            needs_pass=False
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def __len__(self):return 4
            def __getitem__(self,index):
                self.index=index
                if index!=2:raise AssertionError('Wrong page')
                return page
        with patch('pymupdf.open',return_value=FakeDoc()):
            self.assertEqual(fallback_pdf_page(b'%PDF- fixture',2),'Recovered source PDF text')
