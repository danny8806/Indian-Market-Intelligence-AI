import unittest
from datetime import datetime
from unittest.mock import patch
from sqlalchemy import create_engine, select
from news_collector.db_store import metadata, morning_reports
from news_collector.engine import IST
from news_collector.vps_final import decision, run, VERSION

class SoleFinalTests(unittest.TestCase):
    def setUp(self):
        self.snapshot={'recent_coverage':True,'recent_universe':True,'items':[{'evidence_id':'e1','nifty_symbols':['IIFL'],'published_at':'2026-11-10T18:00:00+05:30','observed_at':'2026-11-10T18:01:00+05:30','headline':'Dated source reports quarterly profit increase','summary':'Source content supplied directly','url':'https://example.com/news','providers':['MEDIA'],'verified_origin':False}]}
        self.pick={'symbol':'IIFL','side':'LONG','reason':'Source reports quarterly profit increased.','news_summary':'The source reports an increase in quarterly profit.','evidence_ids':['e1']}
    def analyst(self,*args,**kwargs):
        self.assertFalse(kwargs['search']);return 'OK',{'selections':[self.pick]}
    def test_direct_source_does_not_require_independent_verification(self):
        status,_,signals=decision(self.snapshot,analyst=self.analyst)
        self.assertEqual(status,'READY');self.assertEqual(signals[0]['symbol'],'IIFL')
    def test_quota_never_creates_heuristic_picks(self):
        self.assertEqual(decision(self.snapshot,analyst=lambda *a,**k:('QUOTA_LIMIT',None))[0],'UNAVAILABLE')
    def test_wrong_evidence_symbol_is_excluded(self):
        self.pick['symbol']='TCS';self.assertEqual(decision(self.snapshot,analyst=self.analyst)[0],'NO_TRADE')
    def test_no_candidate_is_invented_when_output_empty(self):
        self.assertEqual(decision(self.snapshot,analyst=lambda *a,**k:('OK',{'selections':[]}))[0],'NO_TRADE')
    def test_snapshot_and_final_report_are_immutable(self):
        db=create_engine('sqlite://');metadata.create_all(db)
        now=lambda:datetime(2026,11,11,9,1,tzinfo=IST)
        with patch('news_collector.vps_final.read_evidence',return_value=self.snapshot):
            first=run(db,clock=now,analyst=self.analyst)
            second=run(db,clock=now,analyst=lambda *a,**k:self.fail('Final was rerun'))
        self.assertEqual(first,second)
        with db.connect() as c:self.assertEqual(c.execute(select(morning_reports.c.evidence)).scalar()['pipeline_version'],VERSION)
        db.dispose()
    def test_deadline_rejects_late_model_result(self):
        db=create_engine('sqlite://');metadata.create_all(db)
        clocks=iter([datetime(2026,11,11,9,10,tzinfo=IST)]*2+[datetime(2026,11,11,9,12,tzinfo=IST)]*4)
        with patch('news_collector.vps_final.read_evidence',return_value=self.snapshot):
            r=run(db,clock=lambda:next(clocks),analyst=self.analyst)
        self.assertEqual(r['status'],'FINALIZATION_DEADLINE_ELAPSED');db.dispose()

if __name__=='__main__':unittest.main()
