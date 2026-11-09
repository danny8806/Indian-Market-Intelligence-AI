"""Public ChatGPT GitHub inbox mirroring never needs API or broker credentials."""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from news_collector.github_inbox_pull import GITHUB_CONTENTS, RAW_PREFIX, pull_public_inbox
from news_collector.healthcheck import healthy


class Response:
    def __init__(self, body, code=200):
        self.content = json.dumps(body).encode() if not isinstance(body, bytes) else body
        self.status_code = code


class PublicInboxTests(unittest.TestCase):
    def test_pulls_public_inbox_and_ignores_nonmatching_names(self):
        listing = [
            {"name": "2026-11-10T052500-IST.json", "type": "file"},
            {"name": "../bad.json", "type": "file"},
            {"name": "README.md", "type": "file"},
        ]
        real = {"schema": "chatgpt-news-discovery/v1", "articles": []}
        requests = []
        def fake_get(url, **kwargs):
            requests.append(url)
            self.assertFalse(kwargs["allow_redirects"])
            if url == GITHUB_CONTENTS:
                return Response(listing)
            if url == RAW_PREFIX + "2026-11-10T052500-IST.json":
                return Response(real)
            self.fail("unexpected URL " + url)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = pull_public_inbox(root, get=fake_get)
            b = pull_public_inbox(root, get=fake_get)
            self.assertEqual(a["new_files"], 1)
            self.assertEqual(b["new_files"], 0)
            self.assertEqual(len(requests), 3)
            self.assertTrue((root / "chatgpt_inbox/2026-11-10T052500-IST.json").exists())

    def test_never_accepts_truncated_directory_listing(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                pull_public_inbox(Path(tmp), get=lambda *_args, **_kw:
                                  Response([{"name": "x"}] * 1000))

    def test_heartbeat_health_is_fresh_only_after_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "last_successful_db_sync.json"
            now = datetime(2026, 11, 10, 5, 0, tzinfo=timezone.utc)
            self.assertFalse(healthy(marker, now=now))
            marker.write_text(json.dumps({
                "db_status": "DATABASE_SYNC_OK",
                "sync_completed_at": (now - timedelta(minutes=25)).isoformat()
            }))
            self.assertTrue(healthy(marker, now=now))
            self.assertFalse(healthy(marker, now=now+timedelta(minutes=100)))
            marker.write_text(json.dumps({
                "db_status": "SKIPPED_NO_DB", "sync_completed_at": now.isoformat()
            }))
            self.assertFalse(healthy(marker, now=now))

if __name__ == "__main__":
    unittest.main()
