import unittest
import json
import io
import tempfile
from pathlib import Path
import tracker
from tracker import diff_models, normalize_models, validate_catalog, fetch_catalog_pages, notify, collect, release_signals, classify_release, commit_signals, patch_signals, collect_patch_signals, deliver_alerts, queue_alerts
from unittest.mock import patch
from intelligence import extract_model_ids, evidence_level, new_evidence, merge_evidence, model_summary

class TrackerTests(unittest.TestCase):
    def setUp(self):
        community_stub = patch("tracker.collect_community", return_value=([], {"status": "ok", "initialized": True}))
        community_stub.start()
        self.addCleanup(community_stub.stop)

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
            return {"files": [{"filename": "src/models.py", "patch": "@@ -0,0 +1 @@\n+MODEL = 'aurora-" + url.rsplit("/", 1)[-1] + "'"}]}
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

    def test_new_sdk_release_source_is_baseline_only(self):
        new = {"openai-python": {"tag": "v1", "url": "https://github.com/openai/openai-python/releases/tag/v1", "body": "Add model aurora-test"}}
        self.assertEqual(release_signals({}, new), [])

    def test_patch_source_model_evidence_reference_is_commit_url(self):
        messages = patch_signals("openai-python", "sha", "https://github.com/openai/openai-python/commit/sha",
                                [{"filename": "src/models.py", "patch": "@@ -0,0 +1 @@\n+MODEL = 'aurora-blue-alpha'"}])
        self.assertEqual(messages[0].splitlines()[-1], "https://github.com/openai/openai-python/commit/sha")


    def test_anthropic_pagination_collects_all_pages(self):
        requested = []
        def fake_fetch(url, headers):
            requested.append(url)
            if "after_id=" in url:
                return {"data": [{"id": "claude-two"}], "has_more": False, "last_id": "claude-two"}
            return {"data": [{"id": "claude-one"}], "has_more": True, "last_id": "claude-one"}
        with patch("tracker.fetch", side_effect=fake_fetch):
            data = fetch_catalog_pages("anthropic", "https://api.anthropic.com/v1/models?limit=100", {})
        self.assertEqual(normalize_models(data), ["claude-one", "claude-two"])
        self.assertIn("after_id=claude-one", requested[1])

    def test_gemini_pagination_collects_all_pages(self):
        def fake_fetch(url, headers):
            if "pageToken=" in url:
                return {"models": [{"name": "models/gemini-two"}]}
            return {"models": [{"name": "models/gemini-one"}], "nextPageToken": "next+token"}
        with patch("tracker.fetch", side_effect=fake_fetch):
            data = fetch_catalog_pages("google", "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000", {})
        self.assertEqual(normalize_models(data), ["models/gemini-one", "models/gemini-two"])

    def test_pagination_rejects_missing_or_repeated_cursor(self):
        with patch("tracker.fetch", return_value={"data": [{"id": "one"}], "has_more": True}):
            with self.assertRaises(ValueError):
                fetch_catalog_pages("anthropic", "https://api.anthropic.com/v1/models?limit=100", {})
        with patch("tracker.fetch", return_value={"models": [{"name": "models/one"}], "nextPageToken": "same"}):
            with self.assertRaises(ValueError):
                fetch_catalog_pages("google", "https://example.com/models?pageSize=1000", {}, max_pages=3)

    def test_pagination_aborts_on_second_page_failure(self):
        def fake_fetch(url, headers):
            if "pageToken=" in url:
                raise OSError("page failed")
            return {"models": [{"name": "models/one"}], "nextPageToken": "two"}
        with patch("tracker.fetch", side_effect=fake_fetch):
            with self.assertRaises(OSError):
                fetch_catalog_pages("google", "https://example.com/models?pageSize=1000", {})


    def test_health_reports_failed_and_missing_sources_without_credentials(self):
        health = {}
        def fake_fetch(url, headers):
            if "api.openai.com" in url:
                raise OSError("test-secret-is-never-repeated")
            if "openrouter.ai" in url:
                return {"data": [{"id": "test-model"}]}
            raise RuntimeError("unexpected source")
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-secret-is-never-repeated"}, clear=True), \
             patch("tracker.fetch", side_effect=fake_fetch):
            results = collect(diagnostics=health)
        self.assertEqual(results, {"openrouter": ["test-model"]})
        self.assertEqual(health["openai"]["status"], "failed")
        self.assertEqual(health["openrouter"]["count"], 1)
        self.assertEqual(health["anthropic"]["status"], "missing_key")
        self.assertNotIn("test-secret-is-never-repeated", json.dumps(health))

    def test_main_saves_public_source_health_without_api_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "models.json"
            state.write_text(json.dumps({"openai": ["old"], "_telegram_test_sent": True}))
            def fake_collect(previous, diagnostics=None, metadata=None):
                diagnostics["openai"] = {"status": "failed", "error": "HTTP_403"}
                return {}
            with patch.object(tracker, "STATE", state), \
                 patch("tracker.collect", side_effect=fake_collect), \
                 patch("tracker.collect_sdk_releases", return_value={}), \
                 patch("tracker.collect_sdk_commits", return_value={}), \
                 patch("tracker.notify", return_value=False):
                tracker.main()
            data = json.loads(state.read_text())
            self.assertEqual(data["_health"]["catalogs"]["openai"]["error"], "HTTP_403")
            self.assertEqual(data["_health"]["telegram_pending"], 0)


    def test_github_authentication_applies_only_to_github_api(self):
        seen = []
        def fake_open(request, timeout):
            seen.append((request.full_url, request.get_header("Authorization")))
            return io.BytesIO(b"{}")
        with patch.dict("os.environ", {"GH_API_TOKEN": "test-private-token"}, clear=True), \
             patch("urllib.request.urlopen", side_effect=fake_open):
            tracker.fetch("https://api.github.com/repos/openai/openai-python/releases/latest", {"Accept": "application/json"})
            tracker.fetch("https://api.openai.com/v1/models", {"Authorization": "Bearer provider-key"})
        self.assertEqual(seen[0][1], "Bearer test-private-token")
        self.assertEqual(seen[1][1], "Bearer provider-key")
        self.assertNotEqual(seen[1][1], "Bearer test-private-token")


    def test_official_typescript_and_js_sdks_are_included(self):
        self.assertEqual(tracker.SDK_REPOS["openai-node"], "openai/openai-node")
        self.assertEqual(tracker.SDK_REPOS["anthropic-sdk-typescript"], "anthropics/anthropic-sdk-typescript")
        self.assertEqual(tracker.SDK_REPOS["js-genai"], "googleapis/js-genai")

    def test_main_baselines_unverified_public_mentions_then_only_alerts_new(self):
        from datetime import datetime, timezone
        observation_a = {"source": "community", "provider": "hackernews",
            "model": "aurora-blue-alpha", "reference": "https://news.ycombinator.com/item?id=1",
            "title": "Aurora blue model reported", "published_at": "2026-10-18T10:00:00+00:00"}
        observation_b = {**observation_a, "model": "aurora-red-alpha",
                         "reference": "https://news.ycombinator.com/item?id=2"}
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "models.json"
            state.write_text(json.dumps({"openai": ["old"], "_telegram_test_sent": True}))
            sent = []
            def notify_record(message):
                sent.append(message)
                return True
            with patch.object(tracker, "STATE", state), \
                 patch("tracker.collect", return_value={"openai": ["old"]}), \
                 patch("tracker.collect_sdk_releases", return_value={}), \
                 patch("tracker.collect_sdk_commits", return_value={}), \
                 patch("tracker.notify", side_effect=notify_record):
                with patch("tracker.collect_community", return_value=([observation_a], {"status": "ok", "initialized": True})):
                    tracker.main()
                self.assertFalse(sent)
                self.assertTrue(json.loads(state.read_text())["_community_initialized"])
                self.assertEqual(len(json.loads(state.read_text())["_evidence"]), 1)
                with patch("tracker.collect_community", return_value=([observation_a, observation_b], {"status": "ok", "initialized": True})):
                    tracker.main()
                self.assertEqual(len(sent), 1)
                self.assertIn("UNVERIFIED", sent[0])
                self.assertIn("aurora-red-alpha", sent[0])
                self.assertNotIn("aurora-blue-alpha", sent[0])
                self.assertEqual(len(json.loads(state.read_text())["_evidence"]), 2)


    def test_official_openapi_spec_is_monitored_for_commits(self):
        self.assertEqual(tracker.SOURCE_REPOS["openai-openapi"], "openai/openai-openapi")
        self.assertNotIn("openai-openapi", tracker.SDK_REPOS)

    def test_patch_signals_detect_added_openapi_yaml_model(self):
        files = [{"filename": "openapi.yaml", "patch": "@@ -3 +3 @@\n- type: old\n+ enum: [gpt-6-preview]"}]
        signals = patch_signals("openai-openapi", "abc", 
            "https://github.com/openai/openai-openapi/commit/abc", files)
        self.assertEqual(len(signals), 1)
        self.assertIn("gpt-6-preview", signals[0])

    def test_patch_signals_ignore_yaml_removed_ids(self):
        files = [{"filename": "openapi.yaml", "patch": "@@ -3 +3 @@\n- enum: [aurora-blue-alpha]\n+ type: string"}]
        self.assertEqual(patch_signals("openai-openapi", "abc",
            "https://github.com/openai/openai-openapi/commit/abc", files), [])


    def test_collect_keeps_provider_creation_metadata_separately(self):
        public_metadata = {}
        def fake_fetch(url, headers):
            if "api.openai.com" in url:
                return {"data": [{"id": "aurora-blue-alpha", "created": 1792200000,
                                  "owned_by": "system", "secret": "do-not-store"}]}
            if "openrouter.ai" in url:
                return {"data": [{"id": "openai/public"}]}
            raise AssertionError(url)
        with patch.dict("os.environ", {"OPENAI_API_KEY": "private-key"}, clear=True), \
             patch("tracker.fetch", side_effect=fake_fetch):
            observed = collect(metadata=public_metadata)
        self.assertIn("aurora-blue-alpha", observed["openai"])
        self.assertEqual(public_metadata["openai"]["aurora-blue-alpha"],
                         {"created": 1792200000, "owned_by": "system"})
        self.assertNotIn("do-not-store", json.dumps(public_metadata))

    def test_main_preserves_creation_metadata_for_failed_providers(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "models.json"
            old = {"openai": ["aurora-blue-alpha"],
                   "_catalog_metadata": {"openai": {"aurora-blue-alpha":
                       {"created": 1792200000, "owned_by": "system"}}},
                   "_telegram_test_sent": True}
            state.write_text(json.dumps(old))
            with patch.object(tracker, "STATE", state), \
                 patch("tracker.collect", return_value={}), \
                 patch("tracker.collect_sdk_releases", return_value={}), \
                 patch("tracker.collect_sdk_commits", return_value={}), \
                 patch("tracker.notify", return_value=True):
                tracker.main()
            saved = json.loads(state.read_text())
            self.assertEqual(saved["_catalog_metadata"]["openai"],
                             old["_catalog_metadata"]["openai"])


    def test_missing_optional_metadata_does_not_erase_previous_creation_date(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "models.json"
            state.write_text(json.dumps({
                "openai": ["aurora-blue-alpha"],
                "_catalog_metadata": {"openai": {"aurora-blue-alpha":
                    {"created": 1792200000, "owned_by": "system"}}},
                "_telegram_test_sent": True}))
            def collect_without_optional_fields(previous, diagnostics=None, metadata=None):
                metadata["openai"] = {}
                return {"openai": ["aurora-blue-alpha"]}
            with patch.object(tracker, "STATE", state), \
                 patch("tracker.collect", side_effect=collect_without_optional_fields), \
                 patch("tracker.collect_sdk_releases", return_value={}), \
                 patch("tracker.collect_sdk_commits", return_value={}), \
                 patch("tracker.notify", return_value=True):
                tracker.main()
            saved = json.loads(state.read_text())
            self.assertEqual(saved["_catalog_metadata"]["openai"]["aurora-blue-alpha"]["created"],
                             1792200000)

    def test_normalize(self):
        self.assertEqual(normalize_models([{"id": "b"}, {"id": "a"}, {"id": "a"}]), ["a", "b"])

if __name__ == "__main__":
    unittest.main()
