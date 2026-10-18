import unittest
from tracker import diff_models, normalize_models

class TrackerTests(unittest.TestCase):
    def test_new_models(self):
        self.assertEqual(diff_models({"openai": ["a"]}, {"openai": ["a", "b"]}), {"openai": ["b"]})

    def test_initial_baseline(self):
        self.assertEqual(diff_models({}, {"openai": ["a"]}, initial=True), {})

    def test_normalize(self):
        self.assertEqual(normalize_models([{"id": "b"}, {"id": "a"}, {"id": "a"}]), ["a", "b"])

if __name__ == "__main__":
    unittest.main()
