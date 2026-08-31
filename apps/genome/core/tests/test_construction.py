"""Construction-spec §3 slice one: the tree, resolved costs, acceptance,
contributor counting, completion, effects."""
import unittest

from genome_core import construction as C
from genome_core.engine import AgentView, Choice, Effects, apply_choice


class TestTree(unittest.TestCase):
    def test_eighteen_constructions(self):
        self.assertEqual(len(C.TREE), 18)

    def test_contributor_counts_match_rule_3_3(self):
        for root in ("cairn", "kiln", "grove", "apothecary", "library"):
            self.assertEqual(C.CONTRIBUTORS[root], 1)
        for t2 in ("store", "toolhouse", "granary", "infirmary", "beacon"):
            self.assertEqual(C.CONTRIBUTORS[t2], 2)
        for cap in ("foundation", "forge", "orchard", "sanatorium",
                    "observatory"):
            self.assertEqual(C.CONTRIBUTORS[cap], 3)
        self.assertEqual(C.CONTRIBUTORS["shipyard"], 5)
        self.assertEqual(C.CONTRIBUTORS["ark"], 8)

    def test_families_cover_twenty_kinds_once(self):
        seen = [k for fam in C.FAMILIES.values() for k in fam]
        self.assertEqual(sorted(seen), list(range(20)))

    def test_cost_prefers_world_kinds(self):
        # a world of kinds {17, 3}: cairn (earth) uses 17, not 16
        needs = C.resolve_cost("cairn", [17, 3])
        self.assertEqual(needs, {"17": 10.0})

    def test_capstone_needs_whole_family(self):
        needs = C.resolve_cost("observatory", [5, 12])
        self.assertEqual(set(needs), {"4", "5", "6", "7", "19"})

    def test_ark_touches_all_twenty(self):
        self.assertEqual(len(C.resolve_cost("ark", [0, 1])), 20)


class TestAcceptance(unittest.TestCase):
    SITE = {"needs": {"17": 10.0}, "delivered": {"17": 4.0}}

    def test_accepts_only_room(self):
        take = C.accepts(self.SITE, {"17": 9.0, "3": 5.0})
        self.assertEqual(take, {"17": 6.0})

    def test_full_site_accepts_nothing(self):
        self.assertEqual(
            C.accepts({"needs": {"17": 10.0}, "delivered": {"17": 10.0}},
                      {"17": 5.0}), {})

    def test_progress(self):
        self.assertAlmostEqual(C.progress(self.SITE), 0.4)


class TestEngineOptions(unittest.TestCase):
    def _view(self, cargo):
        return AgentView("a1", "w", "w", 0.5, 0.5, cargo,
                         frozenset(), frozenset({(3, 3)}))

    def test_contribute_offered_at_needy_site(self):
        from genome_core.engine import on_event
        site = {"key": "s1", "x": 0.5, "y": 0.51, "complete": False,
                "needs": {"17": 10.0}, "delivered": {}}
        req = on_event("decide", self._view({"17": 5.0}), [], 1000.0, {}, {},
                       [], {"sites": [site]})
        self.assertIn("contribute_here", req.options)

    def test_not_offered_with_wrong_cargo(self):
        from genome_core.engine import on_event
        site = {"key": "s1", "x": 0.5, "y": 0.51, "complete": False,
                "needs": {"17": 10.0}, "delivered": {}}
        req = on_event("decide", self._view({"3": 5.0}), [], 1000.0, {}, {},
                       [], {"sites": [site]})
        self.assertNotIn("contribute_here", req.options)
        self.assertNotIn("travel_to_site", req.options)

    def test_travel_routes_to_distant_site(self):
        site = {"key": "s1", "x": 0.9, "y": 0.9, "complete": False,
                "needs": {"17": 10.0}, "delivered": {}}
        eff = apply_choice(Choice("travel_to_site"), self._view({"17": 5.0}),
                           [], 1000.0, {}, [], 1.0, {"sites": [site]})
        tx, ty = eff.movement["waypoints"][-1]
        self.assertLess(((tx - 0.9) ** 2 + (ty - 0.9) ** 2) ** 0.5, 0.05)

    def test_contribute_effect_carries_the_hold(self):
        site = {"key": "s1", "x": 0.5, "y": 0.51, "complete": False,
                "needs": {"17": 10.0}, "delivered": {}}
        eff = apply_choice(Choice("contribute_here"),
                           self._view({"17": 5.0}), [], 1000.0,
                           {"site_here": "s1"}, [], 1.0, {"sites": [site]})
        self.assertEqual(eff.contribute, ("s1", {"17": 5.0}))


class TestReservation(unittest.TestCase):
    def test_one_user_cannot_fill_a_two_user_site(self):
        import asyncio
        class FakeRow:
            def __init__(self, payload): self.payload, self.id = payload, 1
        class FakeClient:
            def __init__(self, site): self.site = site; self.saved = None
            async def find_vertices(self, *a, **k): return [FakeRow(self.site)]
            async def upsert_vertex(self, *a, **k):
                self.saved = k["payload"]
        site = {"key": "s", "name": "store", "needs": {"16": 15.0, "17": 15.0},
                "delivered": {}, "contributors": {}, "required_users": 2,
                "complete": False}
        fc = FakeClient(site)
        res = asyncio.run(C.contribute(fc, "w", "s", "u:rich", "a1",
                                       {"16": 15.0, "17": 15.0}))
        # 5 units stay reserved for the missing second user
        self.assertAlmostEqual(sum(res["taken"].values()), 25.0)
        self.assertFalse(res["complete"])

    def test_second_user_completes(self):
        import asyncio
        class FakeRow:
            def __init__(self, payload): self.payload, self.id = payload, 1
        class FakeClient:
            def __init__(self, site): self.site = site
            async def find_vertices(self, *a, **k): return [FakeRow(self.site)]
            async def upsert_vertex(self, *a, **k):
                self.site = k["payload"]
        site = {"key": "s", "name": "store", "needs": {"16": 15.0, "17": 15.0},
                "delivered": {"16": 15.0, "17": 10.0},
                "contributors": {"u:rich": 25.0}, "required_users": 2,
                "complete": False}
        fc = FakeClient(site)
        res = asyncio.run(C.contribute(fc, "w", "s", "u:second", "a2",
                                       {"17": 6.0}))
        self.assertAlmostEqual(sum(res["taken"].values()), 5.0)
        self.assertTrue(res["complete"])


if __name__ == "__main__":
    unittest.main()


class TestStockManifest(unittest.TestCase):
    def _fake(self, ark):
        class Row:
            def __init__(s2, payload): s2.payload, s2.id = payload, 1
        class FC:
            def __init__(s2): s2.ark = ark
            async def find_vertices(s2, *a, **k): return [Row(s2.ark)]
            async def upsert_vertex(s2, *a, **k): s2.ark = k["payload"]
        return FC()

    def test_stock_rides_at_one_slot_per_unit(self):
        import asyncio
        fc = self._fake({"key": "a", "name": "ark", "complete": True,
                         "berths": {"u:a": 5}, "stock_manifest": {}})
        r = asyncio.run(C.manifest_stock(fc, "w", "a", "u:a",
                                         {"3": 2.0, "7": 1.5},
                                         {"3": 10.0, "7": 5.0}))
        self.assertTrue(r["ok"])
        self.assertEqual(r["slots_paid"], 4)          # ceil(3.5)
        self.assertEqual(fc.ark["berths"]["u:a"], 1)
        self.assertEqual(r["world_stock_after"], {"3": 8.0, "7": 3.5})

    def test_cannot_load_what_the_store_lacks(self):
        import asyncio
        fc = self._fake({"key": "a", "name": "ark", "complete": True,
                         "berths": {"u:a": 12}})
        r = asyncio.run(C.manifest_stock(fc, "w", "a", "u:a",
                                         {"3": 9.0}, {"3": 2.0}))
        self.assertIn("error", r)

    def test_slots_gate(self):
        import asyncio
        fc = self._fake({"key": "a", "name": "ark", "complete": True,
                         "berths": {"u:a": 2}})
        r = asyncio.run(C.manifest_stock(fc, "w", "a", "u:a",
                                         {"3": 5.0}, {"3": 9.0}))
        self.assertIn("error", r)
