"""Read public GitHub ChatGPT news-inbox files into a local research mirror.

Uses *no* OpenAI API key, GitHub token, broker credentials or publisher crawls.
This is a read-only public repository discovery mirror. The existing inbox
importer treats all links as UNVERIFIED and assigns no original publish time.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import requests

REPO = "danny8806/Indian-Market-Intelligence-AI"
GITHUB_CONTENTS = (
    "https://api.github.com/repos/" + REPO +
    "/contents/news_collector/chatgpt_inbox?ref=main"
)
RAW_PREFIX = (
    "https://raw.githubusercontent.com/" + REPO +
    "/main/news_collector/chatgpt_inbox/"
)
NAME = re.compile(r"^20\d{2}-\d{2}-\d{2}T\d{6}-IST\.json$")
MAX_BYTES = 250_000


def _get(url: str, get=requests.get) -> requests.Response:
    response = get(
        url, timeout=(7, 15), allow_redirects=False,
        headers={"Accept": "application/vnd.github+json",
                 "User-Agent": "IndianMarketResearchCollector/1.0"},
    )
    if response.status_code != 200:
        raise RuntimeError("GitHub inbox HTTP " + str(response.status_code))
    if len(response.content) > MAX_BYTES * 4:
        raise ValueError("GitHub inbox response too large")
    return response


def pull_public_inbox(root: Path, *, get=requests.get) -> dict:
    """Download only new, format-allowlisted file names. Never delete local files."""
    response = _get(GITHUB_CONTENTS, get=get)
    data = json.loads(response.content)
    if not isinstance(data, list):
        raise ValueError("Unexpected public GitHub inbox listing")
    if len(data) >= 1000:
        # GitHub's directory contents API may truncate at 1000 entries.
        # Refuse to falsely certify complete coverage.
        raise ValueError("GitHub inbox listing at possible 1000-file limit")
    target = root / "chatgpt_inbox"
    target.mkdir(parents=True, exist_ok=True)
    candidates = set()
    for item in data:
        if not isinstance(item, dict) or item.get("type") != "file":
            continue
        name = item.get("name")
        if isinstance(name, str) and NAME.fullmatch(name):
            candidates.add(name)
    downloaded = 0
    for name in sorted(candidates):
        path = target / name
        if path.is_file():
            continue
        raw = _get(RAW_PREFIX + name, get=get).content
        if len(raw) > MAX_BYTES:
            raise ValueError("ChatGPT inbox JSON too large")
        # Parsing now ensures we don't persist invalid/truncated data. The
        # importer later validates the article schema and individual URLs.
        obj = json.loads(raw)
        if not isinstance(obj, dict) or obj.get("schema") != "chatgpt-news-discovery/v1":
            raise ValueError("Unexpected ChatGPT inbox schema")
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(raw)
        tmp.replace(path)
        downloaded += 1
    return {
        "status": "GITHUB_INBOX_PULLED", "listed": len(candidates),
        "new_files": downloaded, "pending": len(candidates) - downloaded,
        "auth": "PUBLIC_GITHUB_NO_API_KEY",
    }
