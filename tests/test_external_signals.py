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
