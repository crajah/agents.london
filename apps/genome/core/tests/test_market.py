"""The marketplace — genome-spec §4.5: escrow at listing, binding atomic
fills, collect-in-person, withdraw, and the board drowning."""
import asyncio
import unittest

from genome_core import market as M


class Row:
    def __init__(self, payload):
        self.payload, self.id = payload, 1


class FakeClient:
    def __init__(self):
        self.rows = {}
        self._n = 0

    async def add_vertex(self, table, realm=None, payload=None, **k):
        self._n += 1
        self.rows[payload["key"]] = Row(dict(payload))

    async def find_vertices(self, table, realm=None, filters=None, **k):
        r = self.rows.get(filters["key"])
        return [r] if r else []

    async def get_vertices(self, table, realm=None, **k):
        return list(self.rows.values())

    async def upsert_vertex(self, table, realm=None, vertex_id=None,
                            payload=None, **k):
        self.rows[payload["key"]] = Row(dict(payload))


class TestMarket(unittest.TestCase):
    def setUp(self):
        self.c = FakeClient()

    def test_no_goods_no_listing(self):
        r = asyncio.run(M.post(self.c, "w", "a", "u", {"3": 5.0}, {"7": 2.0},
                               {"3": 1.0}))
        self.assertIn("error", r)

    def test_escrow_leaves_the_hold(self):
        r = asyncio.run(M.post(self.c, "w", "a", "u", {"3": 5.0}, {"7": 2.0},
                               {"3": 6.0, "9": 1.0}))
        self.assertTrue(r["ok"])
        self.assertEqual(r["cargo_after"], {"3": 1.0, "9": 1.0})

    def test_fill_is_atomic_binding_and_hand_to_hand(self):
        r = asyncio.run(M.post(self.c, "w", "a", "u", {"3": 5.0}, {"7": 2.0},
                               {"3": 6.0}))
        f = asyncio.run(M.fill(self.c, "w", r["key"], "b",
                               {"7": 3.0, "1": 1.0},
                               lister_present=True,
                               lister_cargo={"9": 1.0}))
        self.assertTrue(f["ok"])
        self.assertEqual(f["cargo_after"], {"7": 1.0, "1": 1.0, "3": 5.0})
        # the lister was paid on the spot, hand to hand
        self.assertEqual(f["lister_cargo_after"], {"9": 1.0, "7": 2.0})
        self.assertEqual(self.c.rows[r["key"]].payload["status"],
                         "collected")

    def test_absent_lister_means_the_trade_waits(self):
        r = asyncio.run(M.post(self.c, "w", "a", "u", {"3": 5.0}, {"7": 2.0},
                               {"3": 6.0}))
        f = asyncio.run(M.fill(self.c, "w", r["key"], "b", {"7": 3.0},
                               lister_present=False))
        self.assertIn("error", f)
        self.assertEqual(self.c.rows[r["key"]].payload["status"], "open")

    def test_cannot_pay_cannot_fill(self):
        r = asyncio.run(M.post(self.c, "w", "a", "u", {"3": 5.0}, {"7": 2.0},
                               {"3": 6.0}))
        f = asyncio.run(M.fill(self.c, "w", r["key"], "b", {"7": 1.0}))
        self.assertIn("error", f)

    def test_own_listing_unfillable(self):
        r = asyncio.run(M.post(self.c, "w", "a", "u", {"3": 5.0}, {"7": 2.0},
                               {"3": 6.0}))
        f = asyncio.run(M.fill(self.c, "w", r["key"], "a", {"7": 9.0}))
        self.assertIn("error", f)

    def test_collect_still_works_for_legacy_filled(self):
        # pre-revision listings may sit "filled"; collection stays honest
        self.c.rows["old"] = Row({"key": "old", "lister": "a",
                                  "status": "filled",
                                  "proceeds": {"7": 2.0}})
        col = asyncio.run(M.collect(self.c, "w", "old", "a", {"3": 1.0}))
        self.assertTrue(col["ok"])
        self.assertEqual(col["cargo_after"], {"3": 1.0, "7": 2.0})

    def test_withdraw_returns_escrow(self):
        r = asyncio.run(M.post(self.c, "w", "a", "u", {"3": 5.0}, {"7": 2.0},
                               {"3": 6.0}))
        w = asyncio.run(M.withdraw(self.c, "w", r["key"], "a", {"9": 1.0}))
        self.assertEqual(w["cargo_after"], {"9": 1.0, "3": 5.0})

    def test_flood_takes_the_board(self):
        r = asyncio.run(M.post(self.c, "w", "a", "u", {"3": 5.0}, {"7": 2.0},
                               {"3": 6.0}))
        n = asyncio.run(M.flood_wipe(self.c, "w"))
        self.assertEqual(n, 1)
        self.assertEqual(self.c.rows[r["key"]].payload["status"], "drowned")

    def test_fillable_excludes_own_and_unaffordable(self):
        ls = [{"key": "1", "status": "open", "lister": "a",
               "want": {"7": 2.0}},
              {"key": "2", "status": "open", "lister": "b",
               "want": {"7": 2.0}},
              {"key": "3", "status": "open", "lister": "c",
               "want": {"9": 5.0}}]
        out = M.fillable(ls, {"7": 2.0}, "a")
        self.assertEqual([l["key"] for l in out], ["2"])


if __name__ == "__main__":
    unittest.main()
