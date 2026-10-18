import unittest
from datetime import datetime, timezone
from release_feed import parse_release_feed, collect_release_feed, release_feed_alerts

class ReleaseFeedTests(unittest.TestCase):
    def setUp(self):
        self.event={"id":"release-123","type":"release","provider":"openai",
                    "modelId":"gpt-6-preview","publishedAt":"2026-10-18T09:00:00Z",
                    "baseline":False,"sourceUrl":"https://developers.openai.com/api/docs/models/gpt-6-preview"}
        self.now=datetime(2026,10,18,12,0,tzinfo=timezone.utc)
    def test_recent_release_with_original_source(self):
        entries=parse_release_feed({"schemaVersion":1,"events":[self.event]},now=self.now)
        self.assertEqual(len(entries),1)
        self.assertEqual(entries[0]["model"],"gpt-6-preview")
        self.assertEqual(entries[0]["provider"],"aidatahub")
        self.assertEqual(entries[0]["source"],"external_release")
        self.assertEqual(entries[0]["reference"],self.event["sourceUrl"])
    def test_old_and_baseline_are_suppressed(self):
        old={**self.event,"publishedAt":"2025-01-01T00:00:00Z"}
        baseline={**self.event,"baseline":True}
        self.assertEqual(parse_release_feed({"schemaVersion":1,"events":[old,baseline]},now=self.now),[])
    def test_wrong_source_host_is_rejected(self):
        event={**self.event,"sourceUrl":"https://developers.openai.com.evil.test/model"}
        self.assertEqual(parse_release_feed({"schemaVersion":1,"events":[event]},now=self.now),[])
    def test_listing_is_not_a_release(self):
        event={**self.event,"type":"listing"}
        self.assertEqual(parse_release_feed({"schemaVersion":1,"events":[event]},now=self.now),[])
    def test_fetch_error_reports_failure(self):
        entries,health=collect_release_feed(lambda url,headers: (_ for _ in ()).throw(OSError("down")))
        self.assertEqual(entries,[])
        self.assertEqual(health["status"],"failed")
    def test_alert_does_not_claim_our_api_access(self):
        msg=release_feed_alerts(parse_release_feed({"schemaVersion":1,"events":[self.event]},now=self.now))[0]
        self.assertIn("EXTERNAL",msg)
        self.assertIn("gpt-6-preview",msg)
