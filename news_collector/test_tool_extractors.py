import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
from news_collector.engine import rss_items
from news_collector.tool_extractors import article_summary


class ToolIntegrationTests(unittest.TestCase):
    def atom(self, dates='', summary='<summary type="html">&lt;p&gt;Source text&lt;/p&gt;</summary>'):
        return ('<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Publisher headline</title>'
                '<link href="https://publisher.example/news/item"/>'+dates+summary+'</entry></feed>').encode()

    def test_atom_body_and_exact_publication_time(self):
        rows=rss_items(self.atom('<published>2026-11-11T18:00:00+05:30</published>'),{})
        self.assertEqual(rows[0]['summary'],'Source text')
        self.assertEqual(rows[0]['raw_time'],'2026-11-11T18:00:00+05:30')
        self.assertTrue(rows[0]['original_time'])

    def test_unknown_and_discovery_times_never_filled(self):
        self.assertEqual(rss_items(self.atom(),{})[0]['raw_time'],'')
        rows=rss_items(self.atom('<published>2026-11-11T18:00:00+05:30</published>'),{'timestamp_provenance':'discovery'})
        self.assertEqual(rows[0]['raw_time'],'')

    def test_updated_is_not_original_publication(self):
        row=rss_items(self.atom('<updated>2026-11-11T18:00:00Z</updated>'),{})[0]
        self.assertFalse(row['original_time'])
        self.assertEqual(row['raw_time'],'2026-11-11T18:00:00Z')

    def test_malformed_atom_is_not_forgivingly_accepted(self):
        with self.assertRaises(ET.ParseError):rss_items(self.atom()[:-7],{})

    def test_preserve_existing_summary_without_extractor(self):
        with patch('news_collector.tool_extractors.trafilatura.extract') as extract:
            self.assertEqual(article_summary(b'<html/>','Publisher description'),'Publisher description')
            extract.assert_not_called()

    def test_bounded_extractor_and_no_date_inference(self):
        with patch('news_collector.tool_extractors.trafilatura.extract',return_value='body '*1000) as extract:
            self.assertEqual(len(article_summary(b'x'*600000,'')),1800)
            self.assertEqual(len(extract.call_args.args[0]),512000)

    def test_optional_extraction_error_does_not_fail_record(self):
        with patch('news_collector.tool_extractors.trafilatura.extract',side_effect=ValueError):
            self.assertEqual(article_summary(b'<html/>',''),'')

    def test_empty_extraction_does_not_create_content(self):
        with patch('news_collector.tool_extractors.trafilatura.extract',return_value=None):
            self.assertEqual(article_summary(b'<html/>',''),'')
