import unittest
import json
import tempfile
from pathlib import Path
import tracker
from tracker import diff_models, normalize_models, validate_catalog, notify, collect, release_signals, classify_release, commit_signals, patch_signals, collect_patch_signals, deliver_alerts, queue_alerts
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
        files = [{"filename": "src/client.py", "patch": "@@ -1 +1 @@\n+model = request.model"}]
        self.assertEqual(patch_signals("openai-python", "sha", "https://github.com/a/commit/sha", files), [])

    def test_patch_signals_does_not_extract_removed_model(self):
        files = [{"filename": "src/models.py", "patch": "@@ -1 +1 @@\n-OLD = 'aurora-blue'\n+TIMEOUT = 5"}]
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

    def test_commit_signals_skip_incomplete_history(self):
        commits = [{"sha": "new", "html_url": "https://github.com/x/commit/new", "commit": {"message": "Add model aurora-blue"}}]
        self.assertEqual(commit_signals("x", "missing", commits), [])

    def test_diff_models_does_not_announce_new_provider_baseline(self):
        self.assertEqual(diff_models({"openai": ["x"]}, {"openrouter": ["new"]}), {})

    def test_normalize_rejects_empty_model_ids(self):
        self.assertEqual(normalize_models([{"id": ""}, {"id": "valid"}]), ["valid"])

    def test_telegram_message_chunks_are_bounded(self):
        from tracker import chunk_message
        pieces = chunk_message("a" * 9000, limit=4000)
        self.assertEqual("".join(pieces), "a" * 9000)
        self.assertTrue(all(len(part) <= 4000 for part in pieces))


    def test_catalog_rejects_empty_and_invalid_response(self):
        with self.assertRaises(ValueError):
            validate_catalog([], "openai")
        with self.assertRaises(ValueError):
            validate_catalog({"data": [{"id": "a"}]}, "openai")
        with self.assertRaises(ValueError):
            validate_catalog([{"id": " "}], "openai")

    def test_catalog_rejects_sudden_shrink(self):
        baseline = [f"model-{i}" for i in range(100)]
        with self.assertRaises(ValueError):
            validate_catalog([{"id": "model-1"}], "openai", baseline)
        self.assertEqual(validate_catalog([{"id": "model-1"}], "openai", ["model-1"]), ["model-1"])

    def test_catalog_normalization_drops_blank_identifiers(self):
        self.assertEqual(normalize_models([{"id": "   "}, {"id": " valid "}, {"name": " models/test "}]),
                         ["models/test", "valid"])

    def test_patch_cursor_catches_up_without_skipping_uninspected_commits(self):
        sha_list = ["new4", "new3", "new2", "new1", "old"]
        commits = {"openai-python": [{"sha": sha, "html_url": "https://github.com/openai/openai-python/commit/" + sha} for sha in sha_list]}
        def fake_fetch(url, headers):
            return {"files": [{"filename": "src/models.py", "patch": "@@ -0,0 +1 @@\\n+MODEL = 'aurora-" + url.rsplit("/", 1)[-1] + "'"}]}
        with patch("tracker.fetch", side_effect=fake_fetch):
            messages, checkpoints = collect_patch_signals({"openai-python": "old"}, commits, per_provider_limit=2)
        self.assertEqual(len(messages), 2)
        self.assertEqual(checkpoints["openai-python"], "new2")
        with patch("tracker.fetch", side_effect=fake_fetch):
            later, next_checkpoints = collect_patch_signals(checkpoints, commits, per_provider_limit=2)
        self.assertEqual(len(later), 2)
        self.assertEqual(next_checkpoints["openai-python"], "new4")

    def test_patch_cursor_waits_for_failed_detail_download(self):
        commits = {"openai-python": [{"sha": "new", "html_url": "https://github.com/openai/openai-python/commit/new"},
                                     {"sha": "old"}]}
        with patch("tracker.fetch", side_effect=OSError("temporarily unavailable")):
            _, checkpoints = collect_patch_signals({"openai-python": "old"}, commits)
        self.assertEqual(checkpoints["openai-python"], "old")

    def test_pending_alerts_remain_after_failed_delivery(self):
        queued = queue_alerts(["one", "two"], ["two", "three"])
        self.assertEqual(queued, ["one", "two", "three"])
        remaining = deliver_alerts(queued, lambda message: message != "two", limit=2)
        self.assertEqual(remaining, ["two", "three"])
        self.assertEqual(deliver_alerts(remaining, lambda message: True), [])

    def test_notification_delivery_catches_transport_errors(self):
        def failing_sender(message):
            raise OSError("telegram down")
        self.assertEqual(deliver_alerts(["alert"], failing_sender), ["alert"])


    def test_main_keeps_failed_notifications_and_delivers_them_on_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "models.json"
            state.write_text(json.dumps({"openai": ["old"], "_telegram_test_sent": True}))
            with patch.object(tracker, "STATE", state), \
                 patch("tracker.collect", return_value={"openai": ["old", "new"]}), \
                 patch("tracker.collect_sdk_releases", return_value={}), \
                 patch("tracker.collect_sdk_commits", return_value={}), \
                 patch("tracker.notify", return_value=False):
                tracker.main()
            saved = json.loads(state.read_text())
            self.assertEqual(saved["openai"], ["old", "new"])
            self.assertTrue(any("new" in message for message in saved["_pending_alerts"]))
            with patch.object(tracker, "STATE", state), \
                 patch("tracker.collect", return_value={"openai": ["old", "new"]}), \
                 patch("tracker.collect_sdk_releases", return_value={}), \
                 patch("tracker.collect_sdk_commits", return_value={}), \
                 patch("tracker.notify", return_value=True):
                tracker.main()
            self.assertEqual(json.loads(state.read_text())["_pending_alerts"], [])

    def test_main_retry_queue_survives_complete_catalog_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "models.json"
            state.write_text(json.dumps({"openai": ["old"], "_pending_alerts": ["previous alert"], "_telegram_test_sent": True}))
            with patch.object(tracker, "STATE", state), \
                 patch("tracker.collect", return_value={}), \
                 patch("tracker.collect_sdk_releases", return_value={}), \
                 patch("tracker.collect_sdk_commits", return_value={}), \
                 patch("tracker.notify", return_value=True):
                tracker.main()
            self.assertEqual(json.loads(state.read_text())["_pending_alerts"], [])
            self.assertEqual(json.loads(state.read_text())["openai"], ["old"])

    def test_normalize(self):
        self.assertEqual(normalize_models([{"id": "b"}, {"id": "a"}, {"id": "a"}]), ["a", "b"])

if __name__ == "__main__":
    unittest.main()
