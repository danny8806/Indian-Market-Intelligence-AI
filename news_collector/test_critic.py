import json
import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

from news_collector import critic


class CriticTests(unittest.TestCase):
    def test_codex_fallback_is_audited_as_shared_provider(self):
        with patch.dict(os.environ, {}, clear=True), \
             patch("news_collector.critic.run_codex",
                   return_value=("OK", {"selections": []})) as run:
            status, payload, audit = critic.run_critic("prompt", {"type": "object"})
        self.assertEqual((status, payload), ("OK", {"selections": []}))
        self.assertEqual(audit["provider"], "codex")
        self.assertFalse(audit["independent"])
        self.assertEqual(audit["status"], "OK")
        run.assert_called_once()

    def test_configured_endpoint_is_provider_independent(self):
        env = {"NEWS_CRITIC_BASE_URL": "https://critic.example/v1",
               "NEWS_CRITIC_MODEL": "critic-model",
               "NEWS_CRITIC_API_KEY": "test-key"}
        with patch.dict(os.environ, env, clear=True):
            audit = critic.describe()
        self.assertEqual(audit, {"provider": "openai-compatible",
                                 "model": "critic-model", "independent": True})

    def test_compatible_endpoint_returns_json_and_audit(self):
        env = {"NEWS_CRITIC_BASE_URL": "https://critic.example/v1",
               "NEWS_CRITIC_MODEL": "critic-model",
               "NEWS_CRITIC_API_KEY": "test-key"}
        response = MagicMock()
        response.choices[0].message.content = json.dumps({"selections": []})
        client = MagicMock()
        client.chat.completions.create.return_value = response
        fake_openai = types.SimpleNamespace(OpenAI=MagicMock(return_value=client))
        with patch.dict(os.environ, env, clear=True), \
             patch.dict(sys.modules, {"openai": fake_openai}):
            status, payload, audit = critic.run_critic("prompt", {"type": "object"})
        self.assertEqual((status, payload), ("OK", {"selections": []}))
        self.assertEqual(audit["provider"], "openai-compatible")
        self.assertTrue(audit["independent"])
        self.assertEqual(audit["status"], "OK")

    def test_compatible_endpoint_maps_quota_errors(self):
        env = {"NEWS_CRITIC_BASE_URL": "https://critic.example/v1",
               "NEWS_CRITIC_MODEL": "critic-model",
               "NEWS_CRITIC_API_KEY": "test-key"}
        client = MagicMock()
        client.chat.completions.create.side_effect = RuntimeError("429 quota exceeded")
        fake_openai = types.SimpleNamespace(OpenAI=MagicMock(return_value=client))
        with patch.dict(os.environ, env, clear=True), \
             patch.dict(sys.modules, {"openai": fake_openai}):
            status, payload, audit = critic.run_critic("prompt", {"type": "object"})
        self.assertEqual((status, payload), ("QUOTA_LIMIT", None))
        self.assertEqual(audit["status"], "QUOTA_LIMIT")
        self.assertIn("429", audit["error"])


if __name__ == "__main__":
    unittest.main()
