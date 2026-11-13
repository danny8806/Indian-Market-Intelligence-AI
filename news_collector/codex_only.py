"""Reuse ONLY Codex's recorded independent source retrievals. Never fetch again."""
from collections import Counter
from datetime import timezone
from sqlalchemy import select
from news_collector.db_store import article_revisions
from news_collector.engine import IST

CODEX_ORIGINS=('codex_independent_source','codex_search')

def read_evidence(conn,start,cutoff):
    rows=conn.execute(select(article_revisions).where(
        article_revisions.c.evidence['discoverer'].as_string().in_(CODEX_ORIGINS),
        article_revisions.c.published_at>=start.astimezone(timezone.utc),
        article_revisions.c.published_at<cutoff.astimezone(timezone.utc),
        article_revisions.c.observed_at<cutoff.astimezone(timezone.utc),
        article_revisions.c.published_at<=article_revisions.c.observed_at,
    ).order_by(article_revisions.c.observed_at.desc(),article_revisions.c.id)).mappings()
    items=[];seen=set();origins=Counter()
    for row in rows:
        data=row['evidence']
        if data.get('discoverer') not in CODEX_ORIGINS or row['article_id'] in seen:continue
        seen.add(row['article_id']);origins[data['discoverer']]+=1
        observed=row['observed_at']
        if observed.tzinfo is None:observed=observed.replace(tzinfo=timezone.utc)
        items.append({**data,'evidence_id':row['id'],'observed_at':observed.astimezone(IST).isoformat()})
    return {'items':items,'input_mode':'CODEX_ONLY_CACHED','source_health':{'Saved Codex independent news':'REUSED'},
        'codex_only_audit':{'origin_counts':dict(origins),'eligible_items':len(items),
           'saved_retrievals_only':True,'new_fetches':0,'python_or_other_agent_news_used':False,
           'window_start':start.isoformat(),'cutoff':cutoff.isoformat()}}
