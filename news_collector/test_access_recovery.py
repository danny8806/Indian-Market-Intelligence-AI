"""Actual false-block pattern and malformed-feed recovery; no live requests."""
import unittest
import json
from pathlib import Path
from unittest.mock import patch,MagicMock
import xml.etree.ElementTree as ET
from news_collector.broker_sources import allowed_by_robots,listing_items
from news_collector.engine import rss_items,USER_AGENT,html_table_items


class AccessRecoveryTests(unittest.TestCase):
    def response(self,text,status=200):
        r=MagicMock();r.status_code=status;r.iter_content.return_value=[text.encode()]
        r.__enter__.return_value=r;return r

    def test_unrelated_short_bot_token_cannot_block_research_collector(self):
        body='User-agent: es\nDisallow: /\n\nUser-agent: *\nDisallow: /admin/\n'
        with patch('news_collector.broker_sources.requests.get',return_value=self.response(body)) as get:
            allowed,_=allowed_by_robots('https://broker.test/news/stocks',USER_AGENT)
        self.assertTrue(allowed)
        self.assertEqual(get.call_args.kwargs['headers']['User-Agent'],USER_AGENT)
        with patch('news_collector.broker_sources.requests.get',return_value=self.response(body)):
            self.assertFalse(allowed_by_robots('https://broker.test/news/stocks','es')[0])

    def test_named_identity_and_wildcard_denials_remain_enforced(self):
        token=USER_AGENT.split('/')[0]
        for body in [f'User-agent: {token}\nDisallow: /\n', 'User-agent: *\nDisallow: /\n']:
            with self.subTest(body=body),patch('news_collector.broker_sources.requests.get',return_value=self.response(body)):
                self.assertFalse(allowed_by_robots('https://broker.test/news',USER_AGENT)[0])

    def test_longest_path_allow_and_matching_group_merge(self):
        token=USER_AGENT.split('/')[0]
        body=f'User-agent: {token}\nDisallow: /news/\nAllow: /news/public/\n\nUser-agent: {token}\nDisallow: /private/\n'
        for path,expected in [('/news/public/item',True),('/news/secret',False),('/private/x',False)]:
            with self.subTest(path=path),patch('news_collector.broker_sources.requests.get',return_value=self.response(body)):
                self.assertEqual(allowed_by_robots('https://broker.test'+path,USER_AGENT)[0],expected)

    def test_denied_or_redirecting_robots_still_blocks(self):
        for status in [301,401,403,429,500]:
            with self.subTest(status=status),patch('news_collector.broker_sources.requests.get',return_value=self.response('',status)):
                self.assertFalse(allowed_by_robots('https://broker.test/news',USER_AGENT)[0])

    def feed(self):
        return (b'<?xml version="1.0"?><rss version="2.0"><channel><item>'
            b'<title>Company A & B publishes quarterly news</title>'
            b'<link>https://publisher.test/article</link>'
            b'<pubDate>Thu, 12 Nov 2026 18:05:00 +0530</pubDate>'
            b'<description>Reported revenue and earnings context</description>'
            b'</item><item><title>Truncated next item')

    def test_opt_in_recovers_only_complete_item_with_original_source_time(self):
        with self.assertRaises(ET.ParseError):rss_items(self.feed(),{})
        rows=rss_items(self.feed(),{'recover_malformed_rss':True})
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['url'],'https://publisher.test/article')
        self.assertEqual(rows[0]['headline'],'Company A & B publishes quarterly news')
        self.assertEqual(rows[0]['raw_time'],'Thu, 12 Nov 2026 18:05:00 +0530')
        self.assertTrue(rows[0]['original_time'])

    def test_recovery_cannot_invent_missing_times_or_promote_discovery_dates(self):
        unknown=self.feed().replace(b'<pubDate>Thu, 12 Nov 2026 18:05:00 +0530</pubDate>',b'')
        row=rss_items(unknown,{'recover_malformed_rss':True})[0]
        self.assertEqual(row['raw_time'],'');self.assertFalse(row['original_time'])
        row=rss_items(self.feed(),{'recover_malformed_rss':True,'timestamp_provenance':'discovery'})[0]
        self.assertEqual(row['raw_time'],'')

    def test_recovery_rejects_html_no_complete_items_and_entities(self):
        for raw in [b'<html><body>denied</body></html>', b'<html>'+self.feed(),
                    b'<rss><channel><item>partial',b'<!DOCTYPE rss [<!ENTITY x SYSTEM "file:///etc/passwd">]>'+self.feed()]:
            with self.subTest(raw=raw[:30]),self.assertRaises((ValueError,ET.ParseError)):
                rss_items(raw,{'recover_malformed_rss':True})

    def config(self,name):
        return next(s for s in json.loads((Path(__file__).parent/'sources.json').read_text(encoding='utf-8'))['sources'] if s['name']==name)

    def test_icici_real_article_paths_include_the_numeric_news_id(self):
        source=self.config('ICICI Direct Market News')
        rows=listing_items(b'<h4><a href="/share-market-today/news/company-announces-results/5044128">Company announces quarterly operating results</a></h4>',source)
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['raw_time'],'')
        self.assertTrue(rows[0]['url'].endswith('/5044128'))

    def test_direct_results_cards_do_not_infer_dates_from_slugs(self):
        source=self.config('ResultKal indexed discovery')
        rows=listing_items(b'<a href="/r/example-2026-11-12">EXAMPLE Company Limited revenue increased in quarterly results 12 Nov 07:58 pm</a>',source)
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['raw_time'],'')

    def test_disclosure_table_keeps_official_document_link_without_guessing_day(self):
        source=self.config('PatternsRadar indexed discovery')
        raw=b'<section id="announcements"><table><thead><tr><th>Time</th><th>Symbol</th><th>Announcement</th><th>Source</th></tr></thead><tbody><tr><td>19:04</td><td>EXAMPLE</td><td>Quarterly financial results published</td><td><a href="https://nsearchives.nseindia.com/corporate/document.pdf">PDF</a></td></tr></tbody></table></section>'
        rows=html_table_items(raw,source)
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['raw_time'],'')
        self.assertEqual(rows[0]['url'],'https://nsearchives.nseindia.com/corporate/document.pdf')
        from news_collector.tool_worker import allowed_target
        self.assertTrue(allowed_target(rows[0]['url'],source))
        self.assertFalse(allowed_target('https://attacker.test/corporate/document.pdf',source))

    def test_explicit_public_source_limit_does_not_drop_after_100_links(self):
        source=self.config('ResultKal indexed discovery')
        raw=''.join(f'<a href="/r/company-{i}-2026-11-12">Company {i} publishes quarterly results</a>' for i in range(220)).encode()
        self.assertEqual(len(listing_items(raw,source)),220)
        with self.assertRaises(ValueError):listing_items(raw,{**source,'max_items':0})

    def test_explicit_table_limit_does_not_drop_after_150_disclosures(self):
        source=self.config('PatternsRadar indexed discovery')
        rows=''.join(f'<tr><td>19:04</td><td>COMP{i}</td><td>Quarterly results published</td><td><a href="https://nsearchives.nseindia.com/corporate/{i}.pdf">PDF</a></td></tr>' for i in range(220))
        raw=('<section id="announcements"><table><thead><tr><th>Time</th><th>Symbol</th><th>Announcement</th><th>Source</th></tr></thead><tbody>'+rows+'</tbody></table></section>').encode()
        self.assertEqual(len(html_table_items(raw,source)),220)
        with self.assertRaises(ValueError):html_table_items(raw,{**source,'max_items':True})


if __name__=='__main__':unittest.main()
