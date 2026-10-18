import unittest
from tracker import diff_models, normalize_models, notify, collect, release_signals, classify_release, commit_signals, patch_signals
from unittest.mock import patch

class TrackerTests(unittest.TestCase):
    def test_new_models(self):
        self.assertEqual(diff_models({"openai": ["a"]}, {"openai": ["a", "b"]}), {"openai": ["b"]})

    def test_initial_baseline(self):
        self.assertEqual(diff_models({}, {"openai": ["a"]}, initial=True), {})

    def test_new_provider_does_not_alert_without_baseline(self):
        self.assertEqual(diff_models({"openai": ["a"]}, {"google": ["models/x"]}), {})

    def test_gemini_name(self):
        self.assertEqual(normalize_models([{"name": "models/gemini-2.5-flash"}]), ["models/gemini-2.5-flash"])

    def test_telegram_missing_credentials(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertFalse(notify("test"))

    def test_openrouter_public_catalog_without_key(self):
        def fake_fetch(url, headers):
            if "openrouter.ai" in url:
                self.assertEqual(headers, {"User-Agent": "FrontierWatchAI/0.2"})
                return {"data": [{"id": "openai/example"}, {"id": "anthropic/example"}]}
            raise OSError("offline")
        with patch.dict("os.environ", {}, clear=True), patch("tracker.fetch", side_effect=fake_fetch):
            self.assertEqual(collect(), {"openrouter": ["anthropic/example", "openai/example"]})

    def test_sdk_release_baseline_and_change(self):
        old = {"openai-python": "v1"}
        new = {"openai-python": {"tag": "v2", "url": "https://github.com/openai/openai-python/releases/tag/v2", "body": "Add model identifier aurora-blue"}}
        signals = release_signals(old, new)
        self.assertEqual(len(signals), 1)
        self.assertIn("aurora-blue", signals[0])
        self.assertEqual(release_signals({}, new), [])

    def test_sdk_release_without_model_keyword(self):
        self.assertFalse(classify_release("Fix HTTP timeout handling"))

    def test_sdk_release_model_keyword(self):
        self.assertTrue(classify_release("Add model identifier to SDK"))

    def test_commit_signals_only_new_matching_messages(self):
        commits = [{"sha": "new", "html_url": "https://github.com/openai/openai-python/commit/new", "commit": {"message": "Add model identifier aurora-blue"}}, {"sha": "old", "commit": {"message": "Old model"}}]
        self.assertEqual(len(commit_signals("openai-python", "old", commits)), 1)
        self.assertIn("aurora-blue", commit_signals("openai-python", "old", commits)[0])
        self.assertEqual(commit_signals("openai-python", None, commits), [])

    def test_commit_signals_ignore_nonmodel_changes(self):
        commits = [{"sha": "new", "html_url": "https://github.com/x/commit/new", "commit": {"message": "Fix timeout"}}, {"sha": "old", "commit": {"message": "Old"}}]
        self.assertEqual(commit_signals("x", "old", commits), [])

    def test_patch_signals_detect_added_model_identifier(self):
        files = [{"filename": "src/models.py", "patch": "@@ -1 +1 @@\n-old = True\n+MODEL_AURORA_BLUE = 'aurora-blue'"}]
        signals = patch_signals("openai-python", "abc123", "https://github.com/openai/openai-python/commit/abc123", files)
        self.assertEqual(len(signals), 1)
        self.assertIn("aurora-blue", signals[0])

    def test_patch_signals_ignore_removed_lines_and_docs(self):
        files = [{"filename": "src/models.py", "patch": "@@ -1 +1 @@\n-aurora-blue\n+timeout = 3"}, {"filename": "tests/test_models.py", "patch": "@@ -0,0 +1 @@\n+aurora-blue"}]
        self.assertEqual(patch_signals("x", "abc", "https://github.com/x/commit/abc", files), [])

    def test_normalize(self):
        self.assertEqual(normalize_models([{"id": "b"}, {"id": "a"}, {"id": "a"}]), ["a", "b"])

if __name__ == "__main__":
    unittest.main()
