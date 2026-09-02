"""Plans — Rules 13.6a-d, 13.7, 13.8: the grammar, the tree, the spread."""
import asyncio
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from genome_core import construction as C
from genome_core import plans as P


TREE = [{"item": "tower", "needs": {"16": 10.0}, "contributors": 2},
        {"item": "sails", "needs": {"4": 6.0}},
        {"item": "windmill", "needs": {"8": 4.0},
         "after": ["tower", "sails"]}]


class TestGrammar(unittest.TestCase):
    def test_valid_tree_passes(self):
        self.assertIsNone(P.validate_tree(TREE))

    def test_rule_13_7_no_field_can_carry_an_effect(self):
        for field in ("grants", "effect", "bonus", "multiplier", "power"):
            bad = [{"item": "x", "needs": {"1": 5.0}, field: 2.0}]
            self.assertIsNotNone(P.validate_tree(bad), field)

    def test_cycles_and_unknown_deps_rejected(self):
        self.assertIsNotNone(P.validate_tree(
            [{"item": "a", "needs": {"1": 1}, "after": ["a"]}]))
        self.assertIsNotNone(P.validate_tree(
            [{"item": "a", "needs": {"1": 1}, "after": ["ghost"]}]))

    def test_depth_is_the_tier(self):
        self.assertEqual(P.depth_of(TREE, "windmill"), 2)
        self.assertEqual(P.depth_of(TREE, "tower"), 1)


class TestFoundable(unittest.TestCase):
    PLAN = {"key": "plan-abc", "tree": TREE}

    def test_leaves_first_then_the_root(self):
        self.assertEqual(
            set(P.foundable_items(self.PLAN, [])),
            {"plan:plan-abc:tower", "plan:plan-abc:sails"})
        standing = [
            {"plan_key": "plan-abc", "plan_item": "tower", "complete": True},
            {"plan_key": "plan-abc", "plan_item": "sails", "complete": True}]
        self.assertEqual(P.foundable_items(self.PLAN, standing),
                         ["plan:plan-abc:windmill"])

    def test_no_duplicate_while_one_stands(self):
        live = [{"plan_key": "plan-abc", "plan_item": "tower",
                 "complete": False}]
        self.assertNotIn("plan:plan-abc:tower",
                         P.foundable_items(self.PLAN, live))


class TestGossipAndShadowing(unittest.TestCase):
    def test_merge_caps_and_keeps_order(self):
        mine = [f"p{i}" for i in range(10)]
        theirs = [f"q{i}" for i in range(10)]
        merged = P.merge_known(mine, theirs)
        self.assertEqual(len(merged), P.MAX_KNOWN)
        self.assertEqual(merged[:10], mine)

    def test_rule_13_7_plan_named_toolhouse_confers_nothing(self):
        impostor = [{"name": "toolhouse", "complete": True,
                     "plan_key": "plan-x", "plan_item": "toolhouse"}]
        self.assertEqual(C.effects_from(impostor)["mine_rate_mult"], 1.0)


class TestFoundFromPlan(unittest.TestCase):
    def test_found_site_builds_the_node(self):
        class Row:
            def __init__(self, pl): self.payload, self.id = pl, 1
        class FC:
            def __init__(self):
                self.added = []
                self.plan = {"key": "plan-abc", "tree": TREE}
            async def find_vertices(self, table, realm=None, filters=None,
                                    **k):
                if table == P.PLANS_TABLE:
                    return [Row(self.plan)]
                return []
            async def get_vertices(self, *a, **k): return []
            async def add_vertex(self, table, realm=None, payload=None, **k):
                self.added.append(payload)
        fc = FC()
        res = asyncio.run(C.found_site(fc, "w", "userA",
                                       "plan:plan-abc:tower", 0.4, 0.4, [16]))
        self.assertTrue(res.get("ok"), res)
        site = fc.added[0]
        self.assertEqual(site["needs"], {"16": 10.0})
        self.assertEqual(site["required_users"], 2)
        self.assertEqual(site["plan_item"], "tower")
        # the root refuses ground until its dependencies stand
        res2 = asyncio.run(C.found_site(fc, "w", "userA",
                                        "plan:plan-abc:windmill",
                                        0.4, 0.4, [16]))
        self.assertIn("requires completed", res2.get("error", ""))


if __name__ == "__main__":
    unittest.main()
