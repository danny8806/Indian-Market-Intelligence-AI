"""One bounded native task. stdout ends in JSON; no model or broker operations."""
import asyncio,base64,hashlib,io,json,os,subprocess,sys,tempfile
from pathlib import Path
from urllib.parse import urlsplit,urljoin
import requests
from bs4 import BeautifulSoup
from news_collector.engine import USER_AGENT,parse_timestamp

class SourceDenied(ValueError):pass

def allowed_target(url,source):
    from news_collector.codex_research import allowed_url
    hosts={urlsplit(source['url']).hostname,*source.get('allowed_domains',[])}
    hosts.update({h.removeprefix('www.') if h.startswith('www.') else 'www.'+h for h in list(hosts) if h})
    if source.get('provider') in {'NSE','BSE'}:
        hosts.update({'nsearchives.nseindia.com','archives.nseindia.com','www.bseindia.com','bseindia.com'})
    return allowed_url(url,{x for x in hosts if x})

def fetch(url,source):
    from news_collector.broker_sources import allowed_by_robots
    if not allowed_target(url,source) or not allowed_by_robots(url,USER_AGENT)[0]:
        raise ValueError('Source URL or robots access not permitted')
    with requests.get(url,headers={'User-Agent':USER_AGENT},allow_redirects=False,
                      timeout=(3,8),stream=True) as r:
        if r.status_code in (401,403,429):raise SourceDenied('Source denied request')
        r.raise_for_status()
        if r.status_code!=200:raise ValueError('Only direct successful source responses accepted')
        data=bytearray()
        for chunk in r.iter_content(65536):
            data.extend(chunk)
            if len(data)>9_000_000:raise ValueError('Source size limit')
    return bytes(data)

def article(raw,url):
    from news_collector.tool_extractors import article_summary
    soup=BeautifulSoup(raw[:512000],'lxml')
    def meta(*names):
        for name in names:
            n=soup.find('meta',attrs={'property':name}) or soup.find('meta',attrs={'name':name})
            if n and n.get('content'):return n['content']
        return ''
    headline=meta('og:title','twitter:title')
    if not headline:
        node=soup.find('h1');headline=node.get_text(' ',strip=True) if node else ''
    stated=meta('article:published_time','datePublished','pubdate','publish-date')
    if not stated:
        for node in soup.select('article time[datetime],main time[datetime]'):
            stated=node.get('datetime','')
            if stated:break
    # extruct reads publisher metadata only. Do not replace missing dates with
    # URL dates, sitemap lastmod, search dates or machine fetch time.
    if not stated:
        import extruct
        data=extruct.extract(raw[:512000].decode(errors='replace'),base_url=url,syntaxes=['json-ld'])
        for node in data.get('json-ld',[]):
            nodes=node.get('@graph',[node]) if isinstance(node,dict) else []
            for value in nodes:
                if isinstance(value,dict) and value.get('datePublished') and value.get('headline'):
                    if not headline or str(value['headline']).strip().casefold()==headline.strip().casefold():
                        headline=str(value['headline']);stated=str(value['datePublished']);break
    if not headline:return []
    return [{'headline':headline[:550],'summary':article_summary(raw,meta('description','og:description')),
             'url':url,'raw_time':stated,'original_time':bool(stated)}]

def render(raw,url,method):
    if method=='lightpanda':
        r=subprocess.run(['lightpanda','fetch','--obey-robots','--dump','html',url],capture_output=True,timeout=15)
        if any(code in r.stderr.decode(errors='replace') for code in ('403','429','401')):raise SourceDenied('Source denied renderer request')
        if r.returncode:raise ValueError('Lightpanda rendering failed')
        return r.stdout
    if method=='playwright':
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
            try:
                page=browser.new_page(user_agent=USER_AGENT)
                page.route('**/*',lambda route:route.continue_() if urlsplit(route.request.url).scheme=='https' and urlsplit(route.request.url).hostname==urlsplit(url).hostname else route.abort())
                response=page.goto(url,wait_until='domcontentloaded',timeout=12000)
                if response and response.status in (401,403,429):raise SourceDenied('Source denied renderer request')
                return page.content().encode()
            finally:browser.close()
    if method=='puppeteer':
        code="""const p=require('puppeteer-core');(async()=>{const b=await p.launch({executablePath:'/usr/bin/chromium',headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});try{const t=await b.newPage();await t.setUserAgent(process.argv[2]);await t.setRequestInterception(true);const host=new URL(process.argv[1]).hostname;t.on('request',r=>{try{const u=new URL(r.url());u.protocol==='https:'&&u.hostname===host?r.continue():r.abort()}catch{r.abort()}});await t.goto(process.argv[1],{waitUntil:'domcontentloaded',timeout:12000});process.stdout.write(await t.content())}finally{await b.close()}})().catch(()=>process.exit(1))"""
        r=subprocess.run(['node','-e',code,url,USER_AGENT],capture_output=True,timeout=16)
        if r.returncode:raise ValueError('Puppeteer rendering failed')
        return r.stdout
    if method=='selenium':
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        o=Options();o.binary_location='/usr/bin/chromium'
        for a in ['--headless','--no-sandbox','--disable-dev-shm-usage']:o.add_argument(a)
        browser=webdriver.Chrome(options=o)
        try:
            browser.execute_cdp_cmd('Network.enable',{})
            browser.execute_cdp_cmd('Network.setBlockedURLs',{'urls':['*']})
            browser.get('data:text/html;base64,'+base64.b64encode(raw).decode())
            return browser.page_source.encode()
        finally:browser.quit()
    if method=='crawl4ai':
        from crawl4ai import AsyncWebCrawler,BrowserConfig,CrawlerRunConfig
        import socket
        async def run():
            with tempfile.TemporaryDirectory() as folder:
                with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
                chrome=subprocess.Popen(['/usr/bin/chromium','--headless','--no-sandbox','--disable-dev-shm-usage',
                    '--remote-debugging-address=127.0.0.1','--remote-debugging-port='+str(port),'--user-data-dir='+folder],
                    stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                try:
                    for _ in range(35):
                        try:
                            if requests.get(f'http://127.0.0.1:{port}/json/version',timeout=.5).ok:break
                        except requests.RequestException:pass
                        await asyncio.sleep(.1)
                    config=BrowserConfig(browser_type='chromium',headless=True,browser_mode='cdp',
                                         cdp_url=f'http://127.0.0.1:{port}',ignore_https_errors=False)
                    soup=BeautifulSoup(raw,'lxml')
                    for node in soup.select('script,iframe,object,embed,link,img,meta[http-equiv]'):node.decompose()
                    async with AsyncWebCrawler(config=config) as crawler:
                        result=await crawler.arun('raw:'+str(soup),config=CrawlerRunConfig(page_timeout=12000))
                        return (result.cleaned_html or result.html).encode()
                finally:chrome.terminate();chrome.wait(timeout=5)
        return asyncio.run(run())
    if method=='playwright_mcp':
        from mcp import ClientSession,StdioServerParameters
        from mcp.client.stdio import stdio_client
        import re
        soup=BeautifulSoup(raw[:512000],'lxml')
        for node in soup.select('script,iframe,object,embed,link,img,meta[http-equiv]'):node.decompose()
        target='data:text/html;base64,'+base64.b64encode(str(soup).encode()).decode()
        async def snapshot():
            params=StdioServerParameters(command='playwright-mcp',args=['--headless','--executable-path','/usr/bin/chromium',
                '--no-sandbox','--isolated','--no-webmcp','--block-service-workers','--blocked-origins','*',
                '--timeout-navigation','12000'],env={k:os.environ[k] for k in ('PATH','HOME','NODE_PATH') if k in os.environ})
            async with stdio_client(params) as (read,write):
                async with ClientSession(read,write) as session:
                    await session.initialize()
                    await session.call_tool('browser_navigate',{'url':target})
                    response=await session.call_tool('browser_evaluate',{'function':'() => document.documentElement.outerHTML'})
                    if response.is_error:raise ValueError('MCP DOM read failed')
                    text='\n'.join(c.text for c in response.content if hasattr(c,'text'))
                    match=re.search(r'### Result\s+("(?:[^"\\]|\\.)*")',text,re.S)
                    if not match:raise ValueError('MCP DOM result missing')
                    return json.loads(match.group(1)).encode()
        return asyncio.run(snapshot())
    raise ValueError('Unknown renderer')

def pdf_task(data,task):
    from news_collector.enrich import extract_pdf_text
    result=extract_pdf_text(data,pages=3);text=result.get('text_sample','');tools=['pypdf']
    with tempfile.TemporaryDirectory(prefix='news-pdf-task-') as folder:
        p=Path(folder)/'source.pdf';p.write_bytes(data)
        if not text.strip():
            output=Path(folder)/'ocr.pdf'
            r=subprocess.run(['ocrmypdf','--skip-text','--pages','1-'+str(min(3,result['pdf_pages'])),'--jobs','1',str(p),str(output)],capture_output=True,timeout=18)
            if r.returncode==0 and output.exists():text=extract_pdf_text(output.read_bytes(),pages=3).get('text_sample','')
            tools+=['OCRmyPDF','Tesseract']
        tables=[]
        if text and any(k in text.lower() for k in ('revenue','profit','results','income')):
            try:
                import camelot
                for table in camelot.read_pdf(str(p),pages='1',flavor='stream')[:2]:tables.append(table.df.to_string(index=False,header=False))
                tools.append('Camelot')
            except Exception:pass
            if not tables:
                try:
                    import tabula
                    tables=[t.to_string(index=False) for t in tabula.read_pdf(str(p),pages=1,multiple_tables=True)[:2]]
                    tools.append('tabula')
                except Exception:pass
    item=dict(task['source'].get('item',{}))
    if not item:return {'status':'EMPTY','tools':tools,'items':[]}
    item['summary']=(item.get('summary','')+' '+text+' '+' '.join(tables))[:1800]
    return {'status':'OK' if text else 'EMPTY','tools':tools,'items':[item] if text else []}

def discovery(raw,url):
    # Run discovery packages against a loopback mirror of already-fetched
    # bytes. External retrieval is blocked by replacing only declared feed URLs.
    from scrapy.http import HtmlResponse
    from feed_seeker import find_feed_url
    from usp.tree import sitemap_tree_for_homepage
    import feedfinder2,threading,http.server,functools
    soup=BeautifulSoup(raw,'lxml')
    links=[urljoin(url,n.get('href','')) for n in soup.select('link[type*="rss"],link[type*="atom"]')]
    response=HtmlResponse(url=url,body=raw,encoding='utf-8')
    links+=response.css('link[type*="rss"]::attr(href)').getall()
    with tempfile.TemporaryDirectory(prefix='news-feed-discovery-') as folder:
        root=Path(folder)
        class Handler(http.server.SimpleHTTPRequestHandler):
            def log_message(self,*args):pass
        server=http.server.ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Handler,directory=folder))
        local='http://127.0.0.1:'+str(server.server_port)
        tags=[]
        for i,link in enumerate(links[:2]):
            try:feed=fetch(link,{'name':'declared feed','url':url})
            except SourceDenied:raise
            except Exception:continue
            (root/f'feed{i}.xml').write_bytes(feed)
            tags.append('<link rel="alternate" type="application/rss+xml" href="'+local+f'/feed{i}.xml">')
        (root/'index.html').write_text('<html><head>'+''.join(tags)+'</head></html>')
        (root/'publisher.html').write_bytes(raw)
        (root/'robots.txt').write_text('User-agent: *\nAllow: /\nSitemap: '+local+'/sitemap.xml')
        (root/'sitemap.xml').write_text('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+''.join('<url><loc>'+u+'</loc></url>' for u in links[:10])+'</urlset>')
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            feedfinder2.find_feeds(local+'/');find_feed_url(local+'/',html=(root/'index.html').read_text(),spider=0,max_time=3,max_links=1)
            list(sitemap_tree_for_homepage(local).all_pages())
            code="const {HttpCrawler}=require('crawlee');(async()=>{let n=0;const c=new HttpCrawler({maxRequestsPerCrawl:1,maxConcurrency:1,maxRequestRetries:0,useSessionPool:false,async requestHandler(ctx){n++;}});await c.run([process.argv[1]]);if(n!==1)process.exit(1)})().catch(()=>process.exit(1))"
            crawler=subprocess.run(['node','-e',code,local+'/publisher.html'],capture_output=True,timeout=12,
                                   env={**os.environ,'CRAWLEE_PERSIST_STORAGE':'false'})
            if crawler.returncode:raise ValueError('Crawlee source snapshot queue failed')
        finally:server.shutdown();server.server_close()
    return {'status':'OK','tools':['Scrapy','Crawlee','FeedFinder2','Feed Seeker','Ultimate Sitemap Parser'],
            'declared_feed_urls':links[:10],'items':[],'scope':'Discovery adapters inspect declared links; no source activated or date inferred.'}

def monitor(raw,task):
    import threading,http.server,functools
    root=Path(task['blob']).parent/('monitor-'+task['id']);root.mkdir(exist_ok=True)
    (root/'page.html').write_bytes(raw)
    class Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self,*args):pass
    port=37000+int(task['id'][:4],16)%20000
    server=http.server.ThreadingHTTPServer(('127.0.0.1',port),functools.partial(Handler,directory=str(root)))
    threading.Thread(target=server.serve_forever,daemon=True).start()
    origin='http://127.0.0.1:'+str(server.server_port)+'/page.html'
    results={}
    try:
        for binary,flag,dbflag in [('urlwatch','--urls','--cache'),('webchanges','--jobs','--database')]:
            jobs=root/(binary+'-jobs.yaml');config=root/(binary+'-config.yaml')
            jobs.write_text('name: publisher snapshot\nurl: '+origin+'\n')
            config.write_text('report:\n  stdout:\n    enabled: false\n')
            r=subprocess.run([binary,flag,str(jobs),'--config',str(config),dbflag,str(root/(binary+'.db'))],capture_output=True,timeout=10)
            results[binary]='OK' if r.returncode==0 else 'FAILED'
    finally:server.shutdown();server.server_close()
    return {'status':'OK' if all(v=='OK' for v in results.values()) else 'PARTIAL','tools':results,
            'sha256':hashlib.sha256(raw).hexdigest(),'items':[],'scope':'Already-fetched source snapshot; external notifications disabled'}

def run(task):
    source=task['source'];url=task['url'];kind=task['kind']
    if not allowed_target(url,source):raise ValueError('URL outside configured publisher')
    raw=Path(task['blob']).read_bytes() if task.get('blob') else fetch(url,source)
    if kind=='article':return {'status':'OK','tools':['Trafilatura','news-please','Readability','extruct'],'items':article(raw,url)}
    if kind=='pdf':return pdf_task(raw,task)
    if kind=='discovery':return discovery(raw,url)
    if kind=='monitor':
        # Fingerprint already-fetched bytes; native monitoring tools are available
        # through their explicit snapshot commands, never another scheduler.
        return monitor(raw,task)
    if kind=='render':
        from news_collector.engine import html_items
        from news_collector.broker_sources import allowed_by_robots
        if not allowed_by_robots(url,USER_AGENT)[0]:raise ValueError('Robots denied')
        methods=['lightpanda','playwright','puppeteer','selenium','crawl4ai','playwright_mcp']
        start=task.get('attempts',0)%len(methods);used=[]
        for method in (methods[start:]+methods[:start])[:2]:
            used.append(method)
            try:
                rendered=render(raw,url,method);items=html_items(rendered,source)
                if items:return {'status':'OK','tools':used,'items':items}
            except SourceDenied:raise
            except Exception:continue
        return {'status':'EMPTY','tools':used,'items':[]}
    raise ValueError('Unknown task kind')

def main():
    try:result=run(json.load(sys.stdin))
    except Exception as exc:result={'status':'BLOCKED_SOURCE' if isinstance(exc,SourceDenied) else 'TOOL_FAILED','error_type':type(exc).__name__,'tools':[],'items':[]}
    print(json.dumps(result,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
