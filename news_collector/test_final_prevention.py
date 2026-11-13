import json,os,tempfile,unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from sqlalchemy import create_engine,select
from news_collector.engine import IST
from news_collector.db_store import metadata,morning_reports
from news_collector import vps_final as final,final_preflight as preflight,codex_research

class FinalPreventionTests(unittest.TestCase):
 def setUp(self):
  self.s={'items':[{'evidence_id':'e1','nifty_symbols':['IIFL'],'headline':'Dated quarterly news',
    'summary':'The dated source reports quarterly financial results.', 'url':'https://example.com/a',
    'published_at':'2026-11-12T18:00:00+05:30','observed_at':'2026-11-12T18:01:00+05:30','providers':['MEDIA']}]}
 def test_full_message_count_includes_instructions(self):
  prompt,audit=final.input_readiness(self.s)
  self.assertEqual(audit['prompt_characters'],len(prompt))
  self.assertGreater(len(prompt),len(final.encode_news(self.s)))
 def test_small_evidence_cannot_hide_instruction_overflow(self):
  analyst=lambda *a,**k:self.fail('Oversized CLI input was invoked')
  with patch.object(final,'CLI_INPUT_MAX_CHARS',1000):
   status,reason,_=final.decision(self.s,analyst=analyst)
  self.assertEqual(status,'UNAVAILABLE');self.assertIn('CLI character',reason)
 def test_repair_text_also_counted_before_invocation(self):
  prompt,_=final.input_readiness(self.s)
  with patch.object(final,'CLI_INPUT_MAX_CHARS',len(prompt)+500):
   status,reason,_=final.decision(self.s,_repair={'error':'x'*1000},
    analyst=lambda *a,**k:self.fail('Oversized repair invoked'))
  self.assertEqual(status,'UNAVAILABLE');self.assertIn('CLI character',reason)
 def test_preflight_uses_existing_premarket_window(self):
  self.assertTrue(preflight.due(datetime(2026,11,13,7,50,tzinfo=IST)))
  self.assertFalse(preflight.due(datetime(2026,11,13,7,55,tzinfo=IST)))
  self.assertFalse(preflight.due(datetime(2026,11,13,8,30,tzinfo=IST)))
  self.assertFalse(preflight.due(datetime(2026,11,13,8,55,tzinfo=IST)))
  self.assertFalse(preflight.due(datetime(2026,11,14,8,30,tzinfo=IST)))
 def test_preview_never_creates_report_or_calls_selector(self):
  db=create_engine('sqlite://');metadata.create_all(db)
  with patch.object(preflight,'read_evidence',return_value=self.s) as read:
   result=preflight.preview(db,datetime(2026,11,13,8,30,tzinfo=IST))
  self.assertFalse(result['selection_run']);self.assertFalse(result['news_verification'])
  self.assertFalse(read.call_args.kwargs['require_verified_origin'])
  with db.connect() as c:self.assertEqual(c.execute(select(morning_reports)).all(),[])
  db.dispose()
 def test_failed_attempt_reason_survives_before_retry(self):
  db=create_engine('sqlite://');metadata.create_all(db)
  with patch.object(final,'read_evidence',return_value=self.s):
   result=final.run(db,clock=lambda:datetime(2026,11,13,9,0,tzinfo=IST),
    analyst=lambda *a,**k:('QUOTA_LIMIT',None))
  self.assertEqual(result['status'],'AWAITING_CODEX_RETRY')
  with db.connect() as c:row=c.execute(select(morning_reports)).mappings().one()
  self.assertIsNone(row['report'])
  outcome=row['evidence']['last_attempt_outcome']
  self.assertEqual(outcome['status'],'UNAVAILABLE');self.assertIn('QUOTA_LIMIT',outcome['reason'])
  self.assertEqual(outcome['input']['items'],1)
  self.assertEqual(row['evidence']['attempt_history'][0]['outcome'],outcome)
  db.dispose()
 def test_cli_input_failure_is_not_generic_error(self):
  with tempfile.TemporaryDirectory() as directory:
   (Path(directory)/'auth.json').write_text('{}')
   response=SimpleNamespace(returncode=1,stdout='',stderr='Input exceeds the maximum length. input_too_large')
   with patch.dict(os.environ,{'NEWS_CODEX_HOME':directory}),patch.object(codex_research.shutil,'which',return_value='/usr/bin/codex'),patch.object(codex_research.subprocess,'run',return_value=response):
    status,_=codex_research._run_codex('public input',{},search=False,timeout=1)
   self.assertEqual(status,'INPUT_TOO_LARGE')
