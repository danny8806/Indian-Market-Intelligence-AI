"""Read-only native-tool catalogue and bounded extraction fallbacks. No network."""
import importlib.metadata
import io
import json
import shutil
from bs4 import BeautifulSoup

PACKAGES = ['requests','httpx','aiohttp','urllib3','feedparser','beautifulsoup4','lxml',
 'selectolax','trafilatura','newspaper4k','goose3','readability-lxml','extruct',
 'scrapling','news-please','scrapy','crawlee','crawl4ai','scrapy-playwright',
 'playwright','selenium','pypdf','pymupdf','pdfplumber','pdfminer.six','markitdown',
 'camelot-py','tabula-py','pydantic','jsonschema','python-dateutil','dateparser',
 'rapidfuzz','duckdb','polars','pandas','datasketch','sqlalchemy','mcp','fastmcp','faiss-cpu','qdrant-client',
 'feedfinder2','feed-seeker','ultimate-sitemap-parser','urlwatch','webchanges','mlx']


def inventory():
    packages={}
    for name in PACKAGES:
        try:packages[name]={'installed':True,'version':importlib.metadata.version(name)}
        except importlib.metadata.PackageNotFoundError:packages[name]={'installed':False}
    return {'packages':packages,'binaries':{name:bool(shutil.which(name)) for name in
            ['curl','wget','chromium','tesseract','ocrmypdf','java','urlwatch','webchanges','newsboat','httrack','playwright-mcp','lightpanda']},
            'note':'Installed capability inventory, not evidence of all-provider access or active workers. See benchmark report for each test level.'}


def fallback_article_text(raw: bytes) -> str:
    """Already-fetched HTML only. Ignore all inferred dates, tickers and image URLs."""
    raw=raw[:512000]
    # Strip active/resource elements before passing bytes to third-party extractors.
    soup=BeautifulSoup(raw,'lxml')
    for node in soup.select('script,iframe,img,object,embed,link,style'):
        node.decompose()
    html=str(soup)
    for method in ('news-please','readability'):
        try:
            if method=='news-please':
                from newsplease import NewsPlease
                text=NewsPlease.from_html(html,fetch_images=False).maintext or ''
            else:
                from readability import Document
                text=BeautifulSoup(Document(html).summary(),'lxml').get_text(' ',strip=True)
            text=' '.join(text.split())
            if len(text)>=30:return text[:1800]
        except Exception:
            continue
    return ''


def fallback_pdf_page(data: bytes, page: int) -> str:
    """Recover one already-fetched, validated PDF page. No OCR or document fetch."""
    if len(data)>9_000_000 or not data.startswith(b'%PDF-') or page<0 or page>=10:
        return ''
    for method in ('pymupdf','pdfplumber','pdfminer'):
        try:
            if method=='pymupdf':
                import pymupdf
                with pymupdf.open(stream=data,filetype='pdf') as doc:
                    if doc.needs_pass or page>=len(doc):return ''
                    text=doc[page].get_text()
            elif method=='pdfplumber':
                import pdfplumber
                with pdfplumber.open(io.BytesIO(data)) as doc:text=doc.pages[page].extract_text() or ''
            else:
                from pdfminer.high_level import extract_text
                text=extract_text(io.BytesIO(data),page_numbers=[page],maxpages=1)
            if text and text.strip():return text[:70000]
        except Exception:
            continue
    return ''


if __name__=='__main__':
    print(json.dumps(inventory()))
