"""Restrict persisted public provider metadata to known safe fields."""
import unittest

from metadata import catalog_metadata


class MetadataTests(unittest.TestCase):
    def test_openai_creation_timestamp_and_owner_are_retained(self):
        source = [{"id": "aurora-blue-alpha", "created": 1792200000,
                   "owned_by": "system", "sensitive": "never-save-me"}]
        result = catalog_metadata("openai", source)
        self.assertEqual(result["aurora-blue-alpha"],
                         {"created": 1792200000, "owned_by": "system"})
        self.assertNotIn("never-save-me", str(result))

    def test_openrouter_creation_epoch_is_retained(self):
        models = [{"id": "openai/gpt-6", "created": 1780000000, "context_length": 128000}]
        self.assertEqual(catalog_metadata("openrouter", models),
                         {"openai/gpt-6": {"created": 1780000000}})

    def test_anthropic_created_at_is_preserved_if_valid(self):
        models = [{"id": "claude-sonnet-x", "created_at": "2026-10-17T20:01:00Z"}]
        self.assertEqual(catalog_metadata("anthropic", models),
                         {"claude-sonnet-x": {"created_at": "2026-10-17T20:01:00Z"}})

    def test_invalid_metadata_does_not_leak_or_poison_state(self):
        models = [{"id": " test ", "created": True, "owned_by": "private\ntoken",
                   "created_at": "not-a-date", "api_key": "keep-secret"}]
        self.assertEqual(catalog_metadata("openai", models), {})
        self.assertEqual(catalog_metadata("anthropic", models), {})

    def test_creation_time_outside_plausible_range_is_ignored(self):
        models = [{"id": "a", "created": -1}, {"id": "b", "created": 999999999999999}]
        self.assertEqual(catalog_metadata("openai", models), {})

    def test_model_without_identifier_is_ignored(self):
        self.assertEqual(catalog_metadata("openai", [{"created": 1792200000}]), {})

if __name__ == "__main__":
    unittest.main()
