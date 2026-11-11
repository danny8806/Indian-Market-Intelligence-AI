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
        symbols=['IIFL','TCS','INFY','WIPRO','MRF','TITAN','ITC','HDFCBANK','ICICIBANK','SBIN']
        base=self.snapshot['items'][0]
        self.snapshot['items']=[{**base,'evidence_id':f'e{i+1}','nifty_symbols':[symbol],
                                 'url':f'https://example.com/news/{i}'} for i,symbol in enumerate(symbols)]
        self.picks=[{**self.pick,'symbol':symbol,'side':'LONG' if i<5 else 'SHORT','evidence_ids':[f'e{i+1}']} for i,symbol in enumerate(symbols)]
        self.picks[0]=self.pick
    def analyst(self,*args,**kwargs):
        self.assertFalse(kwargs['search']);return 'OK',{'selections':self.picks}
    def test_direct_source_does_not_require_independent_verification(self):
        status,_,signals=decision(self.snapshot,analyst=self.analyst)
        self.assertEqual(status,'READY');self.assertEqual(signals[0]['symbol'],'IIFL')
    def test_quota_never_creates_heuristic_picks(self):
        self.assertEqual(decision(self.snapshot,analyst=lambda *a,**k:('QUOTA_LIMIT',None))[0],'UNAVAILABLE')
    def test_wrong_evidence_symbol_is_excluded(self):
        self.pick['symbol']='TCS';self.assertEqual(decision(self.snapshot,analyst=self.analyst)[0],'UNAVAILABLE')
    def test_no_candidate_is_invented_when_output_empty(self):
        self.assertEqual(decision(self.snapshot,analyst=lambda *a,**k:('OK',{'selections':[]}))[0],'UNAVAILABLE')

    def test_exact_five_per_side_and_no_recent_verification_gate(self):
        self.snapshot['recent_universe']=False
        status,_,signals=decision(self.snapshot,analyst=self.analyst)
        self.assertEqual(status,'READY')
        self.assertEqual([s['side'] for s in signals].count('LONG'),5)
        self.assertEqual([s['side'] for s in signals].count('SHORT'),5)

    def test_more_than_400_news_records_are_not_silently_excluded(self):
        self.snapshot['items'] += [{**self.snapshot['items'][0],'evidence_id':f'extra{i}'} for i in range(450)]
        def analyst(prompt,*args,**kwargs):
            self.assertIn('extra449',prompt)
            return self.analyst(prompt,*args,**kwargs)
        self.assertEqual(decision(self.snapshot,analyst=analyst)[0],'READY')

    def test_same_selector_can_correct_incomplete_output_without_verification(self):
        calls=[]
        def analyst(prompt,*args,**kwargs):
            calls.append(prompt)
            return 'OK',{'selections':self.picks[:-1] if len(calls)==1 else self.picks}
        status,_,signals=decision(self.snapshot,analyst=analyst)
        self.assertEqual(status,'READY');self.assertEqual(len(signals),10)
        self.assertEqual(len(calls),2);self.assertIn('no extra news verification',calls[1])

    def test_retry_uses_actual_new_cutoff_and_preserves_attempt_hashes(self):
        db=create_engine('sqlite://');metadata.create_all(db)
        with patch('news_collector.vps_final.read_evidence',side_effect=lambda *a,**k:dict(self.snapshot)) as read:
            first=run(db,clock=lambda:datetime(2026,11,11,9,0,tzinfo=IST),analyst=lambda *a,**k:('QUOTA_LIMIT',None))
            self.assertEqual(first['status'],'AWAITING_CODEX_RETRY')
            final=run(db,clock=lambda:datetime(2026,11,11,9,5,30,tzinfo=IST),analyst=self.analyst)
        self.assertEqual(final['news_cutoff_at'],'2026-11-11T09:05:30+05:30')
        self.assertEqual(read.call_args.args[2],datetime(2026,11,11,9,5,30,tzinfo=IST))
        with db.connect() as c:history=c.execute(select(morning_reports.c.evidence)).scalar()['attempt_history']
        self.assertEqual(len(history),2);self.assertNotEqual(history[0]['sha256'],history[1]['sha256'])
        db.dispose()
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
