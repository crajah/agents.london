"""Flood clock and berths — construction-spec §4.1/§4.2 slice two, pure
parts: the draw, the window, berth allocation, boarding arithmetic."""
import unittest

from genome_core import construction as C
from genome_core import flood as F


class TestClock(unittest.TestCase):
    def test_draw_is_deterministic_and_in_range(self):
        a = F.draw_flood_at(0.0, 1.0, "w:1")
        b = F.draw_flood_at(0.0, 1.0, "w:1")
        self.assertEqual(a, b)
        self.assertTrue(15 * 86400 <= a <= 30 * 86400)

    def test_time_scale_compresses_the_calendar(self):
        slow = F.draw_flood_at(0.0, 1.0, "w:1")
        fast = F.draw_flood_at(0.0, 60.0, "w:1")
        self.assertAlmostEqual(slow / fast, 60.0, places=6)

    def test_clock_secret_until_the_window(self):
        meta = {"flood_at": 10 * 86400.0, "time_scale": 1.0}
        self.assertIsNone(F.countdown_visible(meta, 0.0))          # 10 days out
        self.assertIsNotNone(F.countdown_visible(meta, 8.5 * 86400.0))  # 1.5 out
        self.assertAlmostEqual(
            F.countdown_visible(meta, 9 * 86400.0), 86400.0)

    def test_scaled_window_scales_too(self):
        meta = {"flood_at": 10000.0, "time_scale": 60.0}
        # window = 2 days / 60 = 2880 s
        self.assertIsNone(F.countdown_visible(meta, 10000.0 - 3000.0))
        self.assertIsNotNone(F.countdown_visible(meta, 10000.0 - 2000.0))


class TestBerths(unittest.TestCase):
    def test_twelve_slots_proportional(self):
        pool = C.allocate_berths({"a": 100.0, "b": 100.0})
        self.assertEqual(pool, {"a": 6, "b": 6})

    def test_largest_remainder_and_all_slots_placed(self):
        pool = C.allocate_berths({"a": 50.0, "b": 30.0, "c": 20.0})
        self.assertEqual(sum(pool.values()), 12)
        self.assertEqual(pool["a"], 6)
        self.assertGreaterEqual(pool["b"], 3)

    def test_tiny_contributor_can_round_to_nothing(self):
        pool = C.allocate_berths({"whale": 1000.0, "minnow": 1.0})
        self.assertEqual(sum(pool.values()), 12)

    def test_empty_contributions_no_berths(self):
        self.assertEqual(C.allocate_berths({}), {})

    def test_deterministic_tiebreak(self):
        a = C.allocate_berths({"u1": 10.0, "u2": 10.0, "u3": 10.0})
        b = C.allocate_berths({"u3": 10.0, "u1": 10.0, "u2": 10.0})
        self.assertEqual(a, b)


class TestBoarding(unittest.TestCase):
    def _fake(self, site):
        class Row:
            def __init__(s2, payload): s2.payload, s2.id = payload, 1
        class FC:
            def __init__(s2): s2.site = site; s2.agent = {"key": "a1"}
            async def find_vertices(s2, table, **k):
                if table == C.TABLE:
                    return [Row(s2.site)]
                return [Row(s2.agent)]
            async def upsert_vertex(s2, table, **k):
                if table == C.TABLE:
                    s2.site = k["payload"]
                else:
                    s2.agent = k["payload"]
        return FC()

    def test_board_consumes_a_berth(self):
        import asyncio
        fc = self._fake({"key": "ark1", "name": "ark", "complete": True,
                         "berths": {"u:a": 2}, "boarded": {}})
        r = asyncio.run(C.board(fc, "w", "ark1", "u:a", "a1"))
        self.assertEqual(r, {"ok": True, "berths_left": 1})
        self.assertEqual(fc.site["boarded"], {"a1": "u:a"})
        self.assertTrue(fc.agent["berth"])

    def test_no_claim_no_board(self):
        import asyncio
        fc = self._fake({"key": "ark1", "name": "ark", "complete": True,
                         "berths": {"u:a": 0}, "boarded": {}})
        r = asyncio.run(C.board(fc, "w", "ark1", "u:a", "a1"))
        self.assertIn("error", r)

    def test_spent_ark_unboardable(self):
        import asyncio
        fc = self._fake({"key": "ark1", "name": "ark", "complete": True,
                         "spent": True, "berths": {"u:a": 3}, "boarded": {}})
        r = asyncio.run(C.board(fc, "w", "ark1", "u:a", "a1"))
        self.assertIn("error", r)


if __name__ == "__main__":
    unittest.main()
