"""Technical input readiness inside the existing collector; never selects stocks."""
from datetime import time
from news_collector.engine import IST,regular_market_day,window_for
from news_collector.morning import read_evidence
from news_collector.vps_final import input_readiness

def due(now):
    now=now.astimezone(IST)
    return regular_market_day(now.date()) and time(7,0)<=now.time().replace(tzinfo=None)<time(7,55)

def preview(engine,now):
    """SELECT-only preview, with the same full news input and size calculation."""
    from pathlib import Path
    import csv
    from news_collector.engine import ROOT
    now=now.astimezone(IST)
    start,_=window_for(now.date().isoformat())
    with engine.connect() as conn:
        if engine.dialect.name=='postgresql':conn.exec_driver_sql('SET TRANSACTION READ ONLY')
        snapshot=read_evidence(conn,start,now,require_verified_origin=False)
    try:
        with (Path(ROOT)/'data/universe_snapshot.csv').open() as handle:
            snapshot['current_nifty_symbols']=sorted({r['Symbol'] for r in csv.DictReader(handle)
                if r.get('Series')=='EQ' and r.get('ISIN Code','').startswith('INE')})
    except (OSError,ValueError):
        snapshot['current_nifty_symbols']=sorted({s for r in snapshot['items'] for s in r['nifty_symbols']})
    _,audit=input_readiness(snapshot)
    return {**audit,'checked_at':now.isoformat(),'session_date':now.date().isoformat(),
            'window_start':start.isoformat(),'selection_run':False,'news_verification':False}
