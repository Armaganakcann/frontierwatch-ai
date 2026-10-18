import unittest
from unittest.mock import patch
from datetime import datetime, timezone
from external_signals import parse_claudemon_feed, collect_claudemon, source_alerts

class ExternalSignalTests(unittest.TestCase):
    def setUp(self):
        self.item={"id":"tag:claudemon.com,2026:change:abc","url":"https://platform.openai.com/docs/models/aurora-red-alpha","title":"aurora-red-alpha","content_text":"openai openai.models model.listing","date_published":"2026-10-17T01:15:26Z","tags":["openai","openai.models","model.listing"]}
    def test_aurora_external_listing_is_attributed_not_official_api_confirmation(self):
        entries=parse_claudemon_feed({"version":"https://jsonfeed.org/version/1.1","items":[self.item]})
        self.assertEqual(len(entries),1)
        self.assertEqual(entries[0]["model"],"aurora-red-alpha")
        self.assertEqual(entries[0]["source"],"external_listing")
        self.assertEqual(entries[0]["provider"],"claudemon")
        self.assertEqual(entries[0]["reference"],"https://platform.openai.com/docs/models/aurora-red-alpha")
        self.assertEqual(entries[0]["observation_url"],"https://claudemon.com/")
    def test_no_invented_model_from_opaque_item(self):
        self.assertEqual(parse_claudemon_feed({"items":[{**self.item,"title":"new models","url":"https://example.org"}]}),[])
    def test_bad_feed_is_rejected(self):
        with self.assertRaises(ValueError):parse_claudemon_feed({"items":"bad"})
    def test_source_failure_preserves_health(self):
        entries,health=collect_claudemon(lambda u,h: (_ for _ in ()).throw(OSError("offline")))
        self.assertEqual(entries,[])
        self.assertEqual(health["status"],"failed")
    def test_unverified_alert_has_link(self):
        entries=parse_claudemon_feed({"items":[self.item]})
        msg=source_alerts(entries)[0]
        self.assertIn("EXTERNAL",msg)
        self.assertIn("aurora-red-alpha",msg)
        self.assertIn("https://platform.openai.com/docs/models/aurora-red-alpha",msg)
    def test_duplicate_items_deduplicated(self):
        entries=parse_claudemon_feed({"items":[self.item,self.item]})
        self.assertEqual(len(entries),1)


    def test_external_listing_rejects_deceptive_url_hosts(self):
        spoof={**self.item,"url":"https://platform.openai.com.evil.test/docs/models/aurora-red-alpha"}
        self.assertEqual(parse_claudemon_feed({"items":[spoof]}),[])
    def test_external_listing_filters_old_events_but_keeps_recent_aurora(self):
        from datetime import datetime,timezone
        now=datetime(2026,10,18,12,0,tzinfo=timezone.utc)
        old={**self.item,"date_published":"2025-04-10T20:49:33Z","title":"gpt-4.1-mini"}
        found=parse_claudemon_feed({"items":[old,self.item]},now=now,max_age_days=14)
        self.assertEqual([x["model"] for x in found],["aurora-red-alpha"])
    def test_external_listing_requires_valid_date_for_recent_filter(self):
        from datetime import datetime,timezone
        now=datetime(2026,10,18,12,0,tzinfo=timezone.utc)
        unknown={**self.item,"date_published":"invalid"}
        self.assertEqual(parse_claudemon_feed({"items":[unknown]},now=now,max_age_days=14),[])
    def test_external_listing_keeps_newest_50_from_larger_feed(self):
        from datetime import datetime,timezone
        now=datetime(2026,10,18,12,0,tzinfo=timezone.utc)
        items=[{**self.item,"id":str(i),"title":f"aurora-{i}-alpha"} for i in range(100)]
        found=parse_claudemon_feed({"items":items},now=now,max_age_days=14)
        self.assertEqual(len(found),50)
