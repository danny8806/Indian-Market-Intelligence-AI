import unittest
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
from sqlalchemy import create_engine,select,insert
from news_collector.engine import IST,window_for,default_session
from news_collector.db_store import metadata,article_revisions,morning_reports
from news_collector.morning import read_evidence
from news_collector import vps_final as final
from news_collector.continuous_worker import codex_slot

class EarlyFinalWindowTests(unittest.TestCase):
 def setUp(self):
  self.db=create_engine('sqlite://');metadata.create_all(self.db);self.addCleanup(self.db.dispose)
  self.base={'evidence_id':'e1','nifty_symbols':['IIFL'],'headline':'Dated source quarterly results',
   'summary':'Source reports quarterly financial results and figures.', 'url':'https://nsearchives.nseindia.com/a.pdf',
   'published_at':'2026-11-12T18:00:00+05:30','observed_at':'2026-11-12T18:01:00+05:30','providers':['NSE']}
 def test_actual_0800_cutoff_and_retry_until_0911(self):
  s={'items':[self.base]}
  with patch.object(final,'read_evidence',return_value=s) as read,patch('news_collector.codex_only.read_evidence',return_value={**s,'input_mode':'CODEX_ONLY_CACHED'}) as own:
   for hour,minute in [(8,0),(8,5),(9,0),(9,1),(9,10)]:
    now=datetime(2026,11,13,hour,minute,tzinfo=IST)
    result=final.run(self.db,clock=lambda:now,analyst=lambda *a,**k:('QUOTA_LIMIT',None))
    self.assertEqual(result['status'],'AWAITING_CODEX_RETRY')
    self.assertEqual((own if hour>=9 else read).call_args.args[2],now)
  with self.db.connect() as c:row=c.execute(select(morning_reports)).mappings().one()
  self.assertIsNone(row['report']);self.assertEqual(len(row['evidence']['attempt_history']),5)
 def test_0759_and_0912_never_start_selection(self):
  for hour,minute in [(7,59),(9,12)]:
   result=final.run(self.db,clock=lambda:datetime(2026,11,13,hour,minute,tzinfo=IST),
    analyst=lambda *a,**k:self.fail('Outside-window model call'))
   self.assertEqual(result['status'],'OUTSIDE_FINAL_WINDOW')
 def test_fetch_reserves_the_new_selection_window(self):
  self.assertEqual(codex_slot(datetime(2026,11,13,7,30,tzinfo=IST),48),15)
  self.assertIsNone(codex_slot(datetime(2026,11,13,8,0,tzinfo=IST),48))
  self.assertIsNone(codex_slot(datetime(2026,11,13,8,30,tzinfo=IST),48))
  self.assertEqual(codex_slot(datetime(2026,11,13,9,30,tzinfo=IST),48),19)
 def test_previous_regular_session_1500_and_actual_start_are_strict(self):
  cutoff=datetime(2026,11,13,8,0,tzinfo=IST);start,_=window_for('2026-11-13')
  self.assertEqual(start,datetime(2026,11,12,15,tzinfo=IST))
  cases=[('old',start-timedelta(seconds=1),start),('at_start',start,start+timedelta(seconds=1)),
   ('valid',cutoff-timedelta(minutes=5),cutoff-timedelta(minutes=4)),
   ('at_cutoff',cutoff,cutoff),('late_observed',cutoff-timedelta(minutes=1),cutoff),
   ('future',cutoff+timedelta(minutes=1),cutoff+timedelta(minutes=2)),('undated',None,cutoff-timedelta(minutes=1))]
  with self.db.begin() as c:
   for identity,published,observed in cases:
    evidence={**self.base,'published_at':published.isoformat() if published else None}
    c.execute(insert(article_revisions).values(id=identity,article_id=identity,
     observed_at=observed.astimezone(timezone.utc),published_at=published.astimezone(timezone.utc) if published else None,
     verified_origin=False,evidence=evidence))
  with self.db.connect() as c:s=read_evidence(c,start,cutoff,require_verified_origin=False)
  self.assertEqual({r['evidence_id'] for r in s['items']},{'at_start','valid'})
  later=cutoff+timedelta(minutes=5)
  with self.db.connect() as c:s=read_evidence(c,start,later,require_verified_origin=False)
  self.assertEqual({r['evidence_id'] for r in s['items']},{'at_start','valid','at_cutoff','late_observed','future'})
 def test_weekend_uses_previous_regular_session(self):
  next_day=default_session(datetime(2026,11,14,8,tzinfo=IST))
  start,_=window_for(next_day)
  self.assertEqual(start,datetime(2026,11,13,15,tzinfo=IST))
