"""Incremental exact-source cache and bounded frozen packets; no stock selector."""
import hashlib,json,sqlite3,time,os,tempfile
from pathlib import Path
from contextvars import ContextVar

FROZEN_CONTEXT=ContextVar('news_final_frozen_context',default=None)
CHUNK_BYTES=24_000
GROUP_SIZE=4
MAX_TOTAL_BYTES=4_800_000
CHUNK_THRESHOLD=600_000
VERSION='frozen-news-chunks-v1'

def canonical(value):return json.dumps(value,ensure_ascii=False,separators=(',',':'))
def digest(text):return hashlib.sha256(text.encode('utf-8')).hexdigest()

def cache_records(snapshot,root,*,budget=12,clock=time.monotonic):
    """Transactionally cache immutable rows. Interrupted/partial work is resumable."""
    from news_collector.vps_final import NEWS_COLUMNS
    began=clock();root=Path(root);root.mkdir(parents=True,exist_ok=True)
    cached=new=pending=0
    with sqlite3.connect(root/'records.sqlite',timeout=3) as conn:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('CREATE TABLE IF NOT EXISTS records (sha TEXT PRIMARY KEY, body TEXT NOT NULL)')
        for item in snapshot['items']:
            body=canonical([item.get(k) for k in NEWS_COLUMNS]);key=digest(body)
            row=conn.execute('SELECT body FROM records WHERE sha=?',(key,)).fetchone()
            if row and row[0]==body:cached+=1;continue
            if clock()-began>=budget:pending+=1;continue
            conn.execute('INSERT OR REPLACE INTO records(sha,body) VALUES (?,?)',(key,body));new+=1
    return {'status':'PARTIAL' if pending else 'READY','records':len(snapshot['items']),
            'cached':cached,'new':new,'pending':pending,'version':VERSION,'model_calls':0}

def restore_cached(snapshot,root):
    """Use only bytes matching this frozen revision. Missing/corrupt cache falls back exactly."""
    from news_collector.vps_final import NEWS_COLUMNS
    cache=Path(root)/'records.sqlite';hits=0;rows=[]
    conn=None
    try:
        if cache.is_file():conn=sqlite3.connect(cache.resolve().as_uri()+'?mode=ro',uri=True,timeout=3)
        for item in snapshot['items']:
            expected=[item.get(k) for k in NEWS_COLUMNS];body=canonical(expected)
            row=conn.execute('SELECT body FROM records WHERE sha=?',(digest(body),)).fetchone() if conn else None
            if row and row[0]==body:rows.append(json.loads(row[0]));hits+=1
            else:rows.append(expected)
    except sqlite3.Error:
        rows=[[item.get(k) for k in NEWS_COLUMNS] for item in snapshot['items']];hits=0
    finally:
        if conn:conn.close()
    items=[{**item,**dict(zip(NEWS_COLUMNS,row))} for item,row in zip(snapshot['items'],rows)]
    return {**snapshot,'items':items},{'hits':hits,'raw_fallback':len(rows)-hits}

def split_utf8(text,limit=CHUNK_BYTES):
    if limit<16:raise ValueError('Chunk budget too small')
    data=text.encode('utf-8');pieces=[]
    while data:
        end=min(limit,len(data))
        while end<len(data) and data[end]&0xC0==0x80:end-=1
        pieces.append(data[:end].decode('utf-8'));data=data[end:]
    return pieces or ['']

def plan(snapshot):
    from news_collector.vps_final import encode_news
    encoded=encode_news(snapshot,compact=True)
    parts=split_utf8(encoded)
    manifest={'version':VERSION,'items':len(snapshot['items']),'encoded_bytes':len(encoded.encode('utf-8')),
              'document_sha256':digest(encoded),'chunks':[{'index':i,'sha256':digest(p),'bytes':len(p.encode('utf-8'))} for i,p in enumerate(parts)],
              'group_size':GROUP_SIZE,'max_group_bytes':CHUNK_BYTES*GROUP_SIZE,
              'evidence_id_format':'row_alias_n_index','cache_optional':True}
    manifest['manifest_sha256']=digest(canonical(manifest))
    return manifest,parts

def chunk_prompt(manifest,repair=None):
    # Same sole selector and direct-source policy, but a small CLI message.
    from news_collector.vps_final import build_prompt
    prompt=build_prompt('CHUNKED_FROZEN_DOCUMENT')
    prompt=prompt.replace('No tools, external search, trading or invented facts.',
      'Only the frozen_news.read_chunks tool is allowed. No external search, shell, trading or invented facts.')
    prompt=prompt.replace('CHUNKED_FROZEN_DOCUMENT',canonical(manifest))
    prompt+='\nThe manifest describes ONE complete immutable JSON news document, split at UTF-8 boundaries. '
    prompt+='Call frozen_news.read_chunks(start,count) for every group, with count<=4: starts '+canonical(list(range(0,len(manifest['chunks']),GROUP_SIZE)))+'. '
    prompt+='Independent groups may be read in parallel. Concatenate the data fragments in index order to read the document. '
    prompt+='Do not output selections before every chunk has been read. No news verification or per-chunk stock ranking. '
    prompt+='Then make ONE combined five LONG/five SHORT decision using all source content and times. '
    prompt+='The document uses the news_columns, string_table and prefix conventions described above; n0,n1 etc reference original frozen rows. '
    if repair is not None:prompt+='\nCorrect count/ID mechanics only using the same frozen chunks; do not verify news. Prior output: '+canonical(repair)
    return prompt

def run_chunked(snapshot,schema,*,analyst,timeout,repair=None,root=None):
    original=snapshot;cache_audit={'hits':0,'raw_fallback':len(snapshot['items'])}
    if root is not None:snapshot,cache_audit=restore_cached(snapshot,root)
    manifest,parts=plan(snapshot)
    prompt=chunk_prompt(manifest,repair)
    if manifest['encoded_bytes']>MAX_TOTAL_BYTES:
        return 'CONTEXT_LIMIT',None,{'manifest':manifest,'cache':cache_audit,'complete':False}
    with tempfile.TemporaryDirectory(prefix='news-frozen-') as directory:
        base=Path(directory);payload=base/'assignment.json';spool=base/'reads.jsonl'
        payload.write_text(canonical({'manifest':manifest,'parts':parts}),encoding='utf-8')
        payload.chmod(0o400)
        token=FROZEN_CONTEXT.set((payload,spool))
        try:status,output=analyst(prompt,schema,search=False,timeout=timeout)
        finally:FROZEN_CONTEXT.reset(token)
        coverage=validate_reads(manifest,spool)
        audit={'manifest':manifest,'cache':cache_audit,**coverage,'prompt_characters':len(prompt)}
        if status=='OK' and not coverage['complete']:return 'INCOMPLETE_CHUNK_READ',None,audit
        return status,output,audit

def validate_reads(manifest,spool):
    expected={r['index']:r for r in manifest['chunks']};seen=set()
    try:lines=Path(spool).read_text(encoding='utf-8').splitlines()
    except FileNotFoundError:lines=[]
    for line in lines:
        try:record=json.loads(line)
        except ValueError:continue
        if not isinstance(record,dict) or record.get('manifest_sha256')!=manifest['manifest_sha256']:continue
        for row in record.get('chunks',[]):
            if isinstance(row,dict) and row==expected.get(row.get('index')):seen.add(row['index'])
    return {'complete':set(expected)==seen,'read_chunks':len(seen),'required_chunks':len(expected),
            'missing_chunks':sorted(set(expected)-seen)}

def warm(engine,root,now,*,budget=12):
    from news_collector.engine import IST,window_for,default_session
    from news_collector.morning import read_evidence
    now=now.astimezone(IST);start,_=window_for(default_session(now))
    with engine.connect() as conn:
        if engine.dialect.name=='postgresql':conn.exec_driver_sql('SET TRANSACTION READ ONLY')
        snapshot=read_evidence(conn,start,now,require_verified_origin=False)
    return {**cache_records(snapshot,root,budget=budget),'checked_at':now.isoformat(),'window_start':start.isoformat()}
