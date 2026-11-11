"""Narrow stdio MCP source reader. Own source fetches, no DB/broker credentials."""
import argparse,json,os,time,sys,threading
from datetime import datetime
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from news_collector.engine import IST,fetch_one


class SourceReader:
    def __init__(self,assignment,spool,*,fetch=fetch_one,clock=lambda:datetime.now(IST)):
        self.sources={str(i):s for i,s in enumerate(assignment)}
        self.spool=Path(spool);self.fetch=fetch;self.clock=clock;self.done={}
        self.locks={key:threading.Lock() for key in self.sources};self.parallel=threading.BoundedSemaphore(2)
        self.spool_lock=threading.Lock()

    def read(self,source_id:str)->dict:
        if source_id not in self.sources:raise ValueError('Unknown assigned source ID')
        with self.locks[source_id],self.parallel:return self._read(source_id)

    def _read(self,source_id):
        if source_id in self.done:return self.done[source_id]
        source=self.sources[source_id]
        try:stats,items=self.fetch(source)
        except Exception as exc:stats,items={'status':'ERROR','error_type':type(exc).__name__},[]
        observed=self.clock().isoformat()
        record={'source_id':source_id,'source':source,'stats':stats,'items':items,'observed_at':observed}
        # Full independently retrieved source records are preserved, even if the
        # model's compact result lists fewer URLs. Source text never controls paths.
        with self.spool_lock,self.spool.open('a',encoding='utf-8') as f:
            f.write(json.dumps(record,ensure_ascii=False)+'\n');f.flush();os.fsync(f.fileno())
        public={'source_id':source_id,'source':source['name'],'status':stats.get('status'),
                'item_count':len(items),'observed_at':observed,
                'items':[{k:r.get(k,'') for k in ('headline','url','raw_time','summary')} for r in items[:40]],
                'note':'Full source results saved by reader; publication times are publisher-reported, not independently verified.'}
        self.done[source_id]=public;return public


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--assignment',type=Path,required=True)
    parser.add_argument('--spool',type=Path,required=True);args=parser.parse_args()
    reader=SourceReader(json.loads(args.assignment.read_text()),args.spool)
    from fastmcp import FastMCP
    server=FastMCP('news_reader')

    @server.tool(annotations={'readOnlyHint':True,'destructiveHint':False,'openWorldHint':True})
    def read_source(source_id:str)->dict:
        """Independently read one assigned configured source by ID; save all its original results."""
        return reader.read(source_id)

    server.run(transport='stdio')

if __name__=='__main__':main()
