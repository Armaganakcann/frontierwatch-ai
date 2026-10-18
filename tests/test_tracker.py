import unittest
from tracker import diff_models, normalize_models, notify
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

    def test_normalize(self):
        self.assertEqual(normalize_models([{"id": "b"}, {"id": "a"}, {"id": "a"}]), ["a", "b"])

if __name__ == "__main__":
    unittest.main()
