import unittest
from pathlib import Path

from codex_typesafe.feed import (
    MAX_INPUT_TOKENS,
    REQUEST_OVERHEAD_TOKENS,
    _encoding,
    prepare_request,
)
from codex_typesafe.questions import FEATURE_NOUL_ID
from codex_typesafe.threads import CodexThread


class RequestBudgetTests(unittest.TestCase):
    def thread(self, text):
        return CodexThread("test", Path("test.jsonl"), turns=[{"turn_id": "one", "user": text}])

    def test_short_thread_is_sent_once(self):
        raw, questions = prepare_request(self.thread("unique thread phrase"), "foo")
        self.assertIn("unique thread phrase", raw)
        self.assertNotIn("unique thread phrase", questions[FEATURE_NOUL_ID]["instructions"])

    def test_long_thread_fits_request_budget(self):
        raw, questions = prepare_request(self.thread("mixed code 🧪 and text " * 3000), "foo")
        encoding = _encoding()
        request_tokens = len(encoding.encode(raw)) + len(
            encoding.encode(questions[FEATURE_NOUL_ID]["instructions"])
        )
        self.assertLessEqual(request_tokens + REQUEST_OVERHEAD_TOKENS, MAX_INPUT_TOKENS)
        self.assertTrue(raw.endswith("…"))

    def test_long_query_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "too long"):
            prepare_request(self.thread("thread"), "query " * 3000)


if __name__ == "__main__":
    unittest.main()
