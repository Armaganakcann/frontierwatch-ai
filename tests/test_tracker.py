import unittest
from tracker import diff_models, normalize_models, notify, collect, release_signals, classify_release, commit_signals, patch_signals
from unittest.mock import patch
from intelligence import extract_model_ids, evidence_level, new_evidence, merge_evidence, model_summary

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

    def test_extract_model_ids(self):
        text = 'MODEL_AURORA_BLUE = "aurora-blue"; model = "gpt-6-preview"'
        self.assertEqual(extract_model_ids(text), ["aurora-blue", "gpt-6-preview"])

    def test_extract_model_ids_rejects_generic_words(self):
        self.assertEqual(extract_model_ids("model = 'test'; use models and identifiers"), [])

    def test_evidence_levels(self):
        self.assertEqual(evidence_level("catalog"), "catalog_observation")
        self.assertEqual(evidence_level("sdk_patch"), "official_code_signal")
        self.assertEqual(evidence_level("rumor"), "unverified")

    def test_evidence_deduplication(self):
        seen = ["sdk_patch|openai-python|aurora-blue|abc"]
        entries = [
            {"source": "sdk_patch", "provider": "openai-python", "model": "aurora-blue", "reference": "abc"},
            {"source": "sdk_patch", "provider": "openai-python", "model": "aurora-blue", "reference": "def"},
        ]
        self.assertEqual(len(new_evidence(entries, seen)), 1)

    def test_merge_evidence_preserves_first_seen_and_adds_sources(self):
        old = [{"model": "aurora-blue", "source": "sdk_patch", "provider": "openai-python", "reference": "abc", "first_seen": "2026-10-17T00:00:00Z", "level": "official_code_signal"}]
        incoming = [
            {"model": "aurora-blue", "source": "sdk_patch", "provider": "openai-python", "reference": "abc"},
            {"model": "aurora-blue", "source": "catalog", "provider": "openai", "reference": "https://api.openai.com/v1/models"}
        ]
        merged, fresh = merge_evidence(old, incoming, "2026-10-18T00:00:00Z")
        self.assertEqual(len(merged), 2)
        self.assertEqual(len(fresh), 1)
        self.assertEqual(merged[0]["first_seen"], "2026-10-17T00:00:00Z")
        self.assertEqual(merged[1]["level"], "catalog_observation")

    def test_merge_evidence_does_not_duplicate_same_reference(self):
        entry = {"model": "gpt-6-preview", "source": "sdk_commit", "provider": "openai-python", "reference": "sha123"}
        first, fresh = merge_evidence([], [entry, entry], "2026-10-18T00:00:00Z")
        self.assertEqual(len(first), 1)
        self.assertEqual(len(fresh), 1)

    def test_patch_signals_ignores_generic_model_variable(self):
        files = [{"filename": "src/client.py", "patch": "@@ -1 +1 @@\\n+model = request.model"}]
        self.assertEqual(patch_signals("openai-python", "sha", "https://github.com/a/commit/sha", files), [])

    def test_patch_signals_does_not_extract_removed_model(self):
        files = [{"filename": "src/models.py", "patch": "@@ -1 +1 @@\\n-OLD = 'aurora-blue'\\n+TIMEOUT = 5"}]
        self.assertEqual(patch_signals("openai-python", "sha", "https://github.com/a/commit/sha", files), [])

    def test_model_summary_aggregates_sources_without_claiming_release(self):
        entries = [
            {"model": "aurora-blue", "source": "sdk_patch", "provider": "openai-python", "reference": "abc", "first_seen": "2026-10-17"},
            {"model": "aurora-blue", "source": "catalog", "provider": "openrouter", "reference": "xyz", "first_seen": "2026-10-18"}
        ]
        report = model_summary(entries)
        self.assertEqual(report["aurora-blue"]["source_count"], 2)
        self.assertEqual(report["aurora-blue"]["first_seen"], "2026-10-17")
        self.assertFalse(report["aurora-blue"]["release_confirmed"])

    def test_normalize(self):
        self.assertEqual(normalize_models([{"id": "b"}, {"id": "a"}, {"id": "a"}]), ["a", "b"])

if __name__ == "__main__":
    unittest.main()
