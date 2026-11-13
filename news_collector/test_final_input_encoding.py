import json,unittest
from news_collector.vps_final import encode_news,decode_news,NEWS_COLUMNS,decision

class LargeFrozenInputTests(unittest.TestCase):
 def snapshot(self):
  rows=[]
  for i in range(3805):
   rows.append({'evidence_id':format(i,'064x'),'nifty_symbols':['IIFL'],
    'headline':'Quarterly source headline '+str(i%70),
    'summary':'Full stated publisher context ₹ crore — unchanged. '*5+str(i%90),
    'url':'https://nsearchives.nseindia.com/corporate/announcements/document-'+str(i)+'.pdf',
    'published_at':'2026-11-12T15:12:00+05:30','observed_at':'2026-11-13T08:12:01.123456+05:30','providers':['NSE']})
  return {'items':rows,'current_nifty_symbols':['IIFL']}
 def test_large_snapshot_restores_every_original_field(self):
  s=self.snapshot();before=json.dumps(s,ensure_ascii=False)
  encoded=encode_news(s);p=json.loads(encoded)
  self.assertEqual(p['evidence_id_format'],'row_alias_n_index')
  self.assertEqual(decode_news(p,s),[{k:r.get(k) for k in NEWS_COLUMNS} for r in s['items']])
  self.assertEqual(len(p['news']),3805)
  self.assertLess(len(encoded.encode()),1_200_000)
  self.assertEqual(json.dumps(s,ensure_ascii=False),before)
 def test_aliases_restore_identity_before_issuer_validation(self):
  s=self.snapshot()
  symbols=['IIFL','TCS','INFY','WIPRO','MRF','TITAN','ITC','HDFCBANK','ICICIBANK','SBIN']
  s['current_nifty_symbols']=symbols
  for i,symbol in enumerate(symbols):s['items'][i]['nifty_symbols']=[symbol]
  def analyst(prompt,schema,**kw):
   self.assertFalse(kw['search'])
   return 'OK',{'selections':[{'symbol':symbol,'side':'LONG' if i<5 else 'SHORT',
     'reason':'Direct dated source reports quarterly news context.',
     'news_summary':'Source reports the quarterly event described in its headline.',
     'evidence_ids':['n'+str(i)]} for i,symbol in enumerate(symbols)]}
  status,_,signals=decision(s,analyst=analyst)
  self.assertEqual(status,'READY');self.assertEqual(len(signals),10)
  self.assertEqual(signals[0]['sources'][0]['url'],s['items'][0]['url'])
 def test_unknown_alias_cannot_create_signal(self):
  s=self.snapshot()
  def analyst(*a,**k):
   return 'OK',{'selections':[{'symbol':'IIFL','side':'LONG','reason':'Direct source quarterly news.',
    'news_summary':'Direct source quarterly news content.','evidence_ids':['n99999']}]}
  self.assertEqual(decision(s,analyst=analyst)[0],'UNAVAILABLE')
