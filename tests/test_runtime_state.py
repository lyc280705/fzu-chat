from __future__ import annotations

import unittest
from uuid import uuid4

from app.runtime_state import acquire_dedupe_lock, acquire_pair_slot, fixed_window_rate_limit, release_slot


class RuntimeStateTests(unittest.TestCase):
    def test_fixed_window_rate_limit_rejects_after_limit(self):
        key = f"test-rate:{uuid4()}"

        self.assertTrue(fixed_window_rate_limit(key, 2, 60))
        self.assertTrue(fixed_window_rate_limit(key, 2, 60))
        self.assertFalse(fixed_window_rate_limit(key, 2, 60))

    def test_pair_slot_enforces_global_and_user_limits(self):
        suffix = str(uuid4())
        first = acquire_pair_slot("test-stream", f"test-global:{suffix}", 2, f"test-user:{suffix}", 1)
        second = acquire_pair_slot("test-stream", f"test-global:{suffix}", 2, f"test-user:{suffix}", 1)

        try:
            self.assertIsNotNone(first)
            self.assertIsNone(second)
        finally:
            release_slot(first)

        third = acquire_pair_slot("test-stream", f"test-global:{suffix}", 2, f"test-user:{suffix}", 1)
        try:
            self.assertIsNotNone(third)
        finally:
            release_slot(third)

    def test_dedupe_lock_allows_one_holder(self):
        name = f"test-lock:{uuid4()}"

        self.assertTrue(acquire_dedupe_lock(name, 60))
        self.assertFalse(acquire_dedupe_lock(name, 60))


if __name__ == "__main__":
    unittest.main()
