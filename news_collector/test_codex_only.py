import unittest
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
from sqlalchemy import create_engine,insert,select
from news_collector.db_store import metadata,article_revisions,morning_reports
from news_collector.engine import IST,window_for
from news_collector import codex_only,vps_final as final

class CodexOnlyTests(unittest.TestCase):
 def setUp(self):
  self.db=create_engine('sqlite://');metadata.create_all(self.db);self.addCleanup(self.db.dispose)
  self.start,_=window_for('2026-11-13');self.cutoff=datetime(2026,11,13,9,tzinfo=IST)
 def add(self,identity,origin,*,article=None,published=None,observed=None):
  published=published or self.start+timedelta(hours=1);observed=observed or self.cutoff-timedelta(minutes=20)
  data={'discoverer':origin,'url':'https://nsearchives.nseindia.com/'+identity+'.pdf','headline':identity,
   'summary':'The publisher reports quarterly profits and losses directly.','published_at':published.isoformat(),
   'nifty_symbols':['IIFL'],'providers':['NSE']}
  with self.db.begin() as c:c.execute(insert(article_revisions).values(id=identity,article_id=article or identity,
   observed_at=observed.astimezone(timezone.utc),published_at=published.astimezone(timezone.utc),verified_origin=False,evidence=data))
 def test_only_codex_saved_origins_and_strict_timestamps(self):
  for identity,origin in [('ownfeed','codex_independent_source'),('ownsearch','codex_search'),('other','python'),('opencode','opencode'),('fake','not_codex_search')]:self.add(identity,origin)
  self.add('early','codex_search',published=self.start-timedelta(seconds=1))
  self.add('future','codex_search',published=self.cutoff,observed=self.cutoff)
  self.add('unobserved','codex_search',observed=self.cutoff)
  with self.db.connect() as c:s=codex_only.read_evidence(c,self.start,self.cutoff)
  self.assertEqual({r['evidence_id'] for r in s['items']},{'ownfeed','ownsearch'})
  self.assertEqual(s['codex_only_audit']['new_fetches'],0)
  self.assertFalse(s['codex_only_audit']['python_or_other_agent_news_used'])
 def test_newer_python_revision_does_not_replace_own_saved_source(self):
  self.add('own','codex_search',article='same',observed=self.cutoff-timedelta(minutes=30))
  self.add('python_new','python',article='same',observed=self.cutoff-timedelta(minutes=1))
  with self.db.connect() as c:s=codex_only.read_evidence(c,self.start,self.cutoff)
  self.assertEqual([r['evidence_id'] for r in s['items']],['own'])
 def test_after_9_never_reads_combined_input_or_refetches(self):
  self.add('own','codex_search')
  with patch.object(final,'read_evidence',side_effect=AssertionError('Combined data must not be used')),patch('requests.get',side_effect=AssertionError('No refetch')):
   result=final.run(self.db,clock=lambda:self.cutoff,analyst=lambda *a,**k:('QUOTA_LIMIT',None))
  self.assertEqual(result['status'],'AWAITING_CODEX_RETRY')
  with self.db.connect() as c:s=c.execute(select(morning_reports.c.evidence)).scalar_one()
  self.assertEqual(s['input_mode'],'CODEX_ONLY_CACHED')
  self.assertEqual([r['evidence_id'] for r in s['items']],['own'])
 def test_empty_own_input_does_not_fall_back_to_python(self):
  self.add('python','python')
  result=final.run(self.db,clock=lambda:self.cutoff,analyst=lambda *a,**k:self.fail('No own news means no invented picks'))
  self.assertEqual(result['status'],'AWAITING_CODEX_RETRY')
  with self.db.connect() as c:s=c.execute(select(morning_reports.c.evidence)).scalar_one()
  self.assertEqual(s['items'],[]);self.assertIn('saved Codex-source',s['last_attempt_outcome']['reason'])
 def test_non_ready_terminal_is_preserved_before_retry(self):
  old={'status':'UNAVAILABLE','reason':'previous input error','signals':[]}
  with self.db.begin() as c:c.execute(insert(morning_reports).values(session_date='2026-11-13',
   frozen_at=self.cutoff,evidence={'pipeline_version':final.VERSION,'attempt_history':[]},report=old))
  self.add('own','codex_search')
  result=final.run(self.db,clock=lambda:self.cutoff,analyst=lambda *a,**k:('QUOTA_LIMIT',None))
  self.assertEqual(result['status'],'AWAITING_CODEX_RETRY')
  with self.db.connect() as c:r=c.execute(select(morning_reports)).mappings().one()
  self.assertIsNone(r['report']);self.assertEqual(r['evidence']['rejected_reports'][0]['report'],old)
