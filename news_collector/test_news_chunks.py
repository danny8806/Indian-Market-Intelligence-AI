import json,tempfile,unittest,sqlite3,os
from pathlib import Path
from unittest.mock import patch
from datetime import datetime
from sqlalchemy import create_engine
from news_collector.engine import IST
from news_collector.db_store import metadata
from news_collector import news_chunks as chunks,vps_final as final
from news_collector.frozen_gateway import FrozenReader

class NewsChunkTests(unittest.TestCase):
 def setUp(self):
  self.symbols=['IIFL','TCS','INFY','WIPRO','MRF','TITAN','ITC','HDFCBANK','ICICIBANK','SBIN']
  self.s={'current_nifty_symbols':self.symbols,'items':[{'evidence_id':f'e{i}',
   'nifty_symbols':[symbol],'headline':f'{symbol} source quarterly results',
   'summary':'Full attributed source context: revenue increased; profit fell; debt and risks remain. ₹50 crore.',
   'url':f'https://example.com/{symbol}','published_at':'2026-11-12T18:00:00+05:30',
   'observed_at':'2026-11-12T18:01:00+05:30','providers':['MEDIA']}
   for i,symbol in enumerate(self.symbols)]}
  self.output={'selections':[{'symbol':symbol,'side':'LONG' if i<5 else 'SHORT','reason':'Direct source context supports this news-based direction.',
    'news_summary':'The source states the quarterly context and risks.', 'evidence_ids':['n'+str(i)]} for i,symbol in enumerate(self.symbols)]}
 def test_utf8_split_roundtrip_and_byte_bounds(self):
  text=('हिन्दी ₹50 — profit fell 😀\n'*1000)
  parts=chunks.split_utf8(text,limit=256)
  self.assertEqual(''.join(parts),text);self.assertTrue(all(len(x.encode())<=256 for x in parts))
 def test_all_frozen_fields_roundtrip_even_large_single_article(self):
  self.s['items'][0]['summary']='Full source context 😀 '*10000
  manifest,parts=chunks.plan(self.s)
  restored=final.decode_news(json.loads(''.join(parts)),self.s)
  self.assertEqual(restored,[{k:r.get(k) for k in final.NEWS_COLUMNS} for r in self.s['items']])
  self.assertEqual(manifest['items'],10);self.assertGreater(len(parts),1)
 def test_incremental_cache_only_prepares_new_revisions(self):
  with tempfile.TemporaryDirectory() as root:
   first=chunks.cache_records(self.s,root);second=chunks.cache_records(self.s,root)
   self.assertEqual(first['new'],10);self.assertEqual(second['new'],0)
   changed=json.loads(json.dumps(self.s));changed['items'][0]['summary']='Revised source states profit fell and debt increased.'
   third=chunks.cache_records(changed,root)
   self.assertEqual(third['new'],1);self.assertEqual(third['cached'],9)
   restored,audit=chunks.restore_cached(self.s,root)
   self.assertEqual(restored,self.s);self.assertEqual(audit['hits'],10)
 def test_cache_failure_never_drops_a_record(self):
  with tempfile.TemporaryDirectory() as root:
   chunks.cache_records(self.s,root)
   body=chunks.canonical([self.s['items'][0].get(k) for k in final.NEWS_COLUMNS])
   with sqlite3.connect(Path(root)/'records.sqlite') as c:c.execute('UPDATE records SET body=? WHERE sha=?',('future tampered content',chunks.digest(body)))
   restored,audit=chunks.restore_cached(self.s,root)
   self.assertEqual(restored,self.s);self.assertEqual(audit['raw_fallback'],1)
 def test_partial_cache_resumes_without_partial_selection(self):
  with tempfile.TemporaryDirectory() as root:
   limited=chunks.cache_records(self.s,root,budget=0)
   self.assertEqual(limited['pending'],10)
   restored,_=chunks.restore_cached(self.s,root);self.assertEqual(restored,self.s)
   complete=chunks.cache_records(self.s,root)
   self.assertEqual(complete['pending'],0)
 def test_reader_restricts_ids_counts_and_detects_tamper(self):
  with tempfile.TemporaryDirectory() as root:
   manifest,parts=chunks.plan(self.s);reader=FrozenReader({'manifest':manifest,'parts':parts},Path(root)/'reads')
   for start,count in [('../file',1),(-1,1),(0,5),(9999,1),(True,1)]:
    with self.assertRaises(ValueError):reader.read(start,count)
   parts[0]+='tampered'
   with self.assertRaises(ValueError):FrozenReader({'manifest':manifest,'parts':parts},Path(root)/'bad')
 def test_complete_reads_bind_to_exact_manifest(self):
  with tempfile.TemporaryDirectory() as root:
   manifest,parts=chunks.plan(self.s);spool=Path(root)/'reads'
   reader=FrozenReader({'manifest':manifest,'parts':parts},spool)
   for start in range(0,len(parts),chunks.GROUP_SIZE):reader.read(start)
   self.assertTrue(chunks.validate_reads(manifest,spool)['complete'])
   other=dict(manifest,manifest_sha256='wrong')
   self.assertFalse(chunks.validate_reads(other,spool)['complete'])
 def test_one_selector_reads_all_chunks_then_returns_5_plus_5(self):
  calls=[]
  def analyst(prompt,schema,**kw):
   self.assertFalse(kw['search']);calls.append(prompt)
   assignment,spool=chunks.FROZEN_CONTEXT.get()
   data=json.loads(assignment.read_text());reader=FrozenReader(data,spool)
   for start in range(0,len(data['parts']),chunks.GROUP_SIZE):reader.read(start)
   return 'OK',self.output
  with tempfile.TemporaryDirectory() as root,patch.dict(os.environ,{'NEWS_ARCHIVE_DIR':root}),patch.object(chunks,'CHUNK_THRESHOLD',1):
   status,_,signals=final.decision(self.s,analyst=analyst)
  self.assertEqual(status,'READY');self.assertEqual(len(calls),1);self.assertEqual(len(signals),10)
  self.assertTrue(final.decision.last_input_audit['chunk_read']['complete'])
  self.assertEqual(signals[0]['sources'][0]['url'],self.s['items'][0]['url'])
 def test_valid_picks_do_not_override_incomplete_reads(self):
  with tempfile.TemporaryDirectory() as root,patch.dict(os.environ,{'NEWS_ARCHIVE_DIR':root}),patch.object(chunks,'CHUNK_THRESHOLD',1):
   status,reason,signals=final.decision(self.s,analyst=lambda *a,**k:('OK',self.output))
  self.assertEqual(status,'UNAVAILABLE');self.assertEqual(signals,[]);self.assertIn('INCOMPLETE_CHUNK_READ',reason)
 def test_initial_message_stays_small_for_large_source_volume(self):
  self.s['items']*=1000
  manifest,parts=chunks.plan(self.s);prompt=chunks.chunk_prompt(manifest)
  self.assertLess(len(prompt),final.CLI_INPUT_MAX_CHARS)
  self.assertEqual(manifest['items'],10000)
  self.assertEqual(len(json.loads(''.join(parts))['news']),10000)
 def test_early_attempt_budget_has_margin_and_last_retry_keeps_deadline(self):
  for minute,expected in [(0,210),(5,210),(10,115)]:
   db=create_engine('sqlite://');metadata.create_all(db);budgets=[]
   def analyst(*a,**kw):budgets.append(kw['timeout']);return 'QUOTA_LIMIT',None
   with patch('news_collector.codex_only.read_evidence',return_value={**self.s,'input_mode':'CODEX_ONLY_CACHED'}):
    final.run(db,clock=lambda:datetime(2026,11,13,9,minute,tzinfo=IST),analyst=analyst)
   self.assertEqual(budgets,[expected]);db.dispose()
