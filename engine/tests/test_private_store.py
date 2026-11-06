from __future__ import annotations

import os
import unittest

from core.private_store import PREFIX, protect_text, unprotect_text


class PrivateStoreTests(unittest.TestCase):
    def test_plain_legacy_values_remain_readable(self):
        self.assertEqual(unprotect_text('{"legacy": true}'), '{"legacy": true}')

    @unittest.skipUnless(os.name == "nt", "DPAPI is Windows-only")
    def test_dpapi_round_trip_is_user_bound(self):
        original = '{"embedding": [0.1, 0.2]}'
        encrypted = protect_text(original)
        self.assertTrue(encrypted.startswith(PREFIX))
        self.assertNotIn("embedding", encrypted)
        self.assertEqual(unprotect_text(encrypted), original)


if __name__ == "__main__":
    unittest.main()
