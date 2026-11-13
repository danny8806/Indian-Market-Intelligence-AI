"""Local immutable-source MCP reader. No networking, DB, shell or broker operations."""
import argparse,json,threading,os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from news_collector.news_chunks import canonical,digest,GROUP_SIZE,CHUNK_BYTES

class FrozenReader:
    def __init__(self,assignment,spool):
        self.manifest=assignment['manifest'];self.parts=assignment['parts'];self.spool=Path(spool)
        self.lock=threading.Lock()
        if len(self.parts)!=len(self.manifest['chunks']):raise ValueError('Incomplete assignment')
        if digest(''.join(self.parts))!=self.manifest['document_sha256']:raise ValueError('Document digest mismatch')
        for i,part in enumerate(self.parts):
            expected=self.manifest['chunks'][i]
            if expected!={'index':i,'sha256':digest(part),'bytes':len(part.encode('utf-8'))}:raise ValueError('Chunk digest mismatch')
            if expected['bytes']>CHUNK_BYTES:raise ValueError('Chunk exceeds byte bound')
    def read(self,start,count=GROUP_SIZE):
        if type(start) is not int or type(count) is not int or start<0 or not 1<=count<=GROUP_SIZE or start>=len(self.parts):
            raise ValueError('Only assigned chunk indices and bounded groups are allowed')
        end=min(start+count,len(self.parts));rows=self.manifest['chunks'][start:end]
        text=''.join(self.parts[start:end])
        if len(text.encode('utf-8'))>CHUNK_BYTES*GROUP_SIZE:raise ValueError('Output bound exceeded')
        record={'manifest_sha256':self.manifest['manifest_sha256'],'chunks':rows}
        with self.lock,self.spool.open('a',encoding='utf-8') as handle:
            handle.write(canonical(record)+'\n');handle.flush();os.fsync(handle.fileno())
        return 'FROZEN JSON DATA FRAGMENT '+str(start)+'..'+str(end-1)+'\n'+text

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--assignment',type=Path,required=True)
    parser.add_argument('--spool',type=Path,required=True);args=parser.parse_args()
    reader=FrozenReader(json.loads(args.assignment.read_text(encoding='utf-8')),args.spool)
    from fastmcp import FastMCP
    server=FastMCP('frozen_news')
    @server.tool(annotations={'readOnlyHint':True,'destructiveHint':False,'openWorldHint':False})
    def read_chunks(start:int,count:int=GROUP_SIZE)->str:
        """Read a bounded group of assigned immutable chunks, starting at its integer index."""
        return reader.read(start,count)
    server.run(transport='stdio')
if __name__=='__main__':main()
