"""Tests for public, explicitly unverified community model references."""
import unittest
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

from community import parse_hn_hit, collect_community, community_alerts


class CommunityTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
        self.timestamp = int(self.now.timestamp())

    def hit(self, item_id="12345", title="Three aurora-blue-alpha variants appear in OpenAI model listing", offset=-1800):
        return {"objectID": item_id, "title": title,
                "created_at_i": self.timestamp + offset,
                "url": "https://example.net/claim"}

    def test_parse_hn_hit_returns_unverified_evidence_with_hn_perma_link(self):
        entries = parse_hn_hit(self.hit(), now=self.now, max_age_hours=72)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["source"], "community")
        self.assertEqual(entries[0]["provider"], "hackernews")
        self.assertEqual(entries[0]["model"], "aurora-blue-alpha")
        self.assertEqual(entries[0]["reference"], "https://news.ycombinator.com/item?id=12345")
        self.assertTrue(entries[0]["published_at"].startswith("2026-10-18T"))

    def test_parse_hn_hit_rejects_unmatched_old_future_invalid_id_and_missing_title(self):
        self.assertEqual(parse_hn_hit(self.hit(title="Aurora borealis above Finland"), now=self.now), [])
        self.assertEqual(parse_hn_hit(self.hit(item_id="not-a-number"), now=self.now), [])
        self.assertEqual(parse_hn_hit(self.hit(offset=-8 * 86400), now=self.now), [])
        self.assertEqual(parse_hn_hit(self.hit(offset=3600), now=self.now), [])
        self.assertEqual(parse_hn_hit(self.hit(title=""), now=self.now), [])

    def test_parse_hn_hit_multiple_distinct_ids_and_sanitized_title(self):
        entry = self.hit(title="gpt-6-preview vs aurora-red-alpha\x00 " + "a"*500)
        result = parse_hn_hit(entry, now=self.now)
        self.assertEqual([x["model"] for x in result], ["aurora-red-alpha", "gpt-6-preview"])
        self.assertLessEqual(len(result[0]["title"]), 180)
        self.assertNotIn("\x00", result[0]["title"])

    def test_collect_community_deduplicates_across_searches(self):
        urls = []
        def fetch(url, headers):
            urls.append(url)
            return {"hits": [self.hit()], "nbPages": 1}
        entries, health = collect_community(fetch, now=self.now)
        self.assertEqual(len(entries), 1)
        self.assertEqual(health["status"], "ok")
        self.assertEqual(health["query_count"], len(urls))
        self.assertGreaterEqual(len(urls), 3)
        params = parse_qs(urlsplit(urls[0]).query)
        self.assertEqual(params["tags"], ["story"])
        self.assertIn("numericFilters", params)
        self.assertNotIn("Authorization", urls[0])

    def test_collect_community_partial_failure_is_explicit(self):
        def fetch(url, headers):
            if "aurora" in url:
                raise OSError("unauthorized")
            return {"hits": [self.hit()], "nbPages": 1}
        entries, health = collect_community(fetch, now=self.now)
        self.assertEqual(health["status"], "partial")
        self.assertGreater(len(entries), 0)
        self.assertEqual(health["failed_queries"], 1)

    def test_collect_community_all_failed_does_not_mark_initialized(self):
        def fetch(url, headers):
            raise OSError("offline")
        entries, health = collect_community(fetch, now=self.now)
        self.assertEqual(entries, [])
        self.assertEqual(health["status"], "failed")
        self.assertFalse(health["initialized"])

    def test_community_alerts_are_unverified_and_bounded(self):
        candidates = [dict(self.hit(item_id=str(i)), model=f"aurora-{i}-alpha",
                           source="community", provider="hackernews",
                           reference=f"https://news.ycombinator.com/item?id={i}", title="rumor")
                      for i in range(10, 20)]
        messages = community_alerts(candidates, limit=3)
        self.assertEqual(len(messages), 1)
        self.assertIn("UNVERIFIED", messages[0])
        self.assertIn("3", messages[0])
        self.assertIn("aurora-10-alpha", messages[0])
        self.assertNotIn("aurora-13-alpha", messages[0])

if __name__ == "__main__":
    unittest.main()
