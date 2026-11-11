"""Explicit public-source transport adapters; no identity or auth changes."""
import asyncio,subprocess,tempfile,time
from pathlib import Path
import requests

LIMIT=14_000_000
UA='IndianMarketResearchCollector/1.0 (public feeds; no login or bypass)'

def _size(chunks):
    data=bytearray()
    for chunk in chunks:
        data.extend(chunk)
        if len(data)>LIMIT:raise ValueError('Source response exceeds size cap')
    return bytes(data)

def fetch(url,method):
    if method=='httpx':
        import httpx
        with httpx.stream('GET',url,headers={'User-Agent':UA},timeout=15,follow_redirects=False) as r:
            r.raise_for_status();return _size(r.iter_bytes(65536))
    if method=='aiohttp':
        import aiohttp
        async def read():
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20),headers={'User-Agent':UA}) as s:
                async with s.get(url,allow_redirects=False) as r:
                    r.raise_for_status()
                    if r.status!=200:raise ValueError('Source redirected')
                    data=bytearray()
                    async for chunk in r.content.iter_chunked(65536):
                        data.extend(chunk)
                        if len(data)>LIMIT:raise ValueError('Source response exceeds size cap')
                    return bytes(data)
        return asyncio.run(read())
    if method in {'curl','wget'}:
        args=(['curl','--fail','--silent','--show-error','--max-time','20','--max-redirs','0','--max-filesize',str(LIMIT),'-A',UA,url]
              if method=='curl' else ['wget','--quiet','--timeout=15','--tries=1','--max-redirect=0','--user-agent='+UA,'-O','-',url])
        with tempfile.TemporaryFile() as output,tempfile.TemporaryFile() as error:
            r=subprocess.run(args,stdout=output,stderr=error,timeout=23)
            if r.returncode:raise ValueError(method+' public-source request failed; no auth/access bypass')
            if output.tell()>LIMIT:raise ValueError('Source response exceeds size cap')
            output.seek(0);return output.read(LIMIT)
    raise ValueError('Unconfigured source transport')
