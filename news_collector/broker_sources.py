"""Collect public broker headlines as leads with explicit article path rules."""
import re
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

from bs4 import BeautifulSoup
import requests


def allowed_by_robots(url: str, user_agent: str) -> tuple[bool, str]:
    parts = urlsplit(url)
    robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
    with requests.get(robots_url, headers={"User-Agent": user_agent}, timeout=(4, 6),
                      allow_redirects=False, stream=True) as response:
        if response.status_code in (404, 410):
            return True, ""
        if response.status_code != 200:
            return False, f"robots.txt HTTP {response.status_code}"
        data = bytearray()
        for chunk in response.iter_content(8192):
            data.extend(chunk)
            if len(data) > 256000:
                return False, "robots.txt exceeded the size limit"
    parser = RobotFileParser()
    parser.parse(data.decode("utf-8-sig", errors="replace").splitlines())
    return parser.can_fetch(user_agent.split("/", 1)[0], url), "robots.txt path restriction"


def listing_items(raw: bytes, source: dict) -> list[dict]:
    soup = BeautifulSoup(raw, "html.parser")
    if source.get("card_selector"):
        rows = {}
        for card in soup.select(source["card_selector"])[:100]:
            title = card.select_one(source["headline_selector"])
            summary = card.select_one(source["summary_selector"])
            if title is None or summary is None:
                continue
            headline = title.get_text(" ", strip=True)[:550]
            if len(headline) >= 15:
                rows[headline] = {
                    "url": source["url"], "headline": headline,
                    "summary": summary.get_text(" ", strip=True)[:1800],
                    "raw_time": "", "shared_broker_link": True,
                }
        return list(rows.values())
    path_rule = re.compile(source["article_path"], re.I)
    origin = urlsplit(source["url"]).hostname
    result, seen = [], set()
    for anchor in soup.select("a[href]"):
        link = urljoin(source["url"], anchor["href"])
        parsed = urlsplit(link)
        if (parsed.scheme != "https" or parsed.hostname != origin or parsed.username
                or not path_rule.fullmatch(parsed.path)):
            continue
        title_node = anchor.select_one(source["headline_selector"]) if source.get("headline_selector") else anchor
        if title_node is None:
            continue
        title = title_node.get_text(" ", strip=True)
        if len(title) < 15 and source.get("fallback_slug"):
            title = parsed.path.rstrip("/").split("/")[-2].replace("-", " ")
        if len(title) < 15:
            continue
        key = (parsed.path, title) if source.get("shared_link") else parsed.path
        if key in seen:
            continue
        seen.add(key)
        result.append({
            "url": link, "headline": title[:550], "summary": "", "raw_time": "",
            "shared_broker_link": bool(source.get("shared_link")),
        })
        if len(result) == 100:
            break
    return result
