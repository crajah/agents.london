"""Commons caches — user directive 2026-08-31: four different kinds, one
unit each; colour-gated; never adjacent."""
import unittest

from genome_core import construction as C
from genome_core.engine import AgentView, on_event


class TestCacheCost(unittest.TestCase):
    def test_four_different_kinds_one_each(self):
        self.assertEqual(C.cache_cost({"1": 2.0, "2": 1.0, "3": 5.0, "4": 1.0}),
                         {"1": 1.0, "2": 1.0, "3": 1.0, "4": 1.0})

    def test_three_kinds_is_not_enough(self):
        self.assertIsNone(C.cache_cost({"1": 9.0, "2": 9.0, "3": 9.0}))

    def test_fractional_units_do_not_count(self):
        self.assertIsNone(
            C.cache_cost({"1": 0.9, "2": 1.0, "3": 1.0, "4": 1.0}))


class TestSpacing(unittest.TestCase):
    def test_adjacent_blocked(self):
        caches = [{"x": 0.5, "y": 0.5}]
        self.assertFalse(C.cache_spot_clear_payloads(caches, 0.52, 0.5))
        self.assertTrue(C.cache_spot_clear_payloads(caches, 0.6, 0.5))


class TestColourGate(unittest.TestCase):
    def test_own_colours_open(self):
        site = {"colours": ["#AA", "#BB"]}
        self.assertTrue(C.cache_open_to(site, {"colour_pair": ["#AA", "#BB"]}))
        self.assertFalse(C.cache_open_to(site, {"colour_pair": ["#AA", "#CC"]}))


class TestEngineOptions(unittest.TestCase):
    def _view(self, cargo):
        return AgentView("a1", "home", "genome_commons_0", 0.5, 0.5, cargo,
                         frozenset(), frozenset({(3, 3)}))

    def test_build_offered_in_commons_with_the_cost(self):
        req = on_event("decide", self._view({"1": 1, "2": 1, "3": 1, "4": 1}),
                       [], 1000.0, {}, {}, [],
                       {"is_commons": True, "caches": [],
                        "colour_pair": ["#A", "#B"]})
        self.assertIn("build_cache", req.options)

    def test_not_offered_outside_commons(self):
        req = on_event("decide", self._view({"1": 1, "2": 1, "3": 1, "4": 1}),
                       [], 1000.0, {}, {}, [], {"is_commons": False})
        self.assertNotIn("build_cache", req.options)

    def test_not_offered_next_to_a_cache(self):
        req = on_event("decide", self._view({"1": 1, "2": 1, "3": 1, "4": 1}),
                       [], 1000.0, {}, {}, [],
                       {"is_commons": True, "colour_pair": ["#A", "#B"],
                        "caches": [{"key": "c1", "x": 0.51, "y": 0.5,
                                    "colours": ["#X", "#Y"], "holdings": {}}]})
        self.assertNotIn("build_cache", req.options)

    def test_stash_and_collect_at_own_colours_only(self):
        mine = {"key": "c1", "x": 0.5, "y": 0.52, "colours": ["#A", "#B"],
                "holdings": {"7": 3.0}}
        req = on_event("decide", self._view({"9": 2.0}), [], 1000.0, {}, {},
                       [], {"is_commons": True, "caches": [mine],
                            "colour_pair": ["#A", "#B"]})
        self.assertIn("stash_cache", req.options)
        self.assertIn("collect_cache", req.options)
        req2 = on_event("decide", self._view({"9": 2.0}), [], 1000.0, {}, {},
                        [], {"is_commons": True, "caches": [mine],
                             "colour_pair": ["#Z", "#B"]})
        self.assertNotIn("stash_cache", req2.options)


if __name__ == "__main__":
    unittest.main()
