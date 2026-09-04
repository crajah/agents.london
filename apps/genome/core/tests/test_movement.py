"""Rule 5.6 (exclusion), 5.7 (movement styles), 4.3a (muster deposits) and the
Teleport Affinity gate — the movement-dynamics directive, proven pure."""
import unittest

import pathlib
import sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from genome_core import engine, styles, worldgen
from genome_core.engine import AgentView, Choice, PileView


def view(x=0.5, y=0.5, cargo=None, explored=frozenset({(3, 3)})):
    return AgentView("agent-t", "w", "w", x, y, cargo or {},
                     frozenset(), explored)


class TestExclusion(unittest.TestCase):
    def test_standoff_stops_short_of_target(self):
        tx, ty = engine.standoff(0.2, 0.2, 0.5, 0.5)
        d = ((tx - 0.5) ** 2 + (ty - 0.5) ** 2) ** 0.5
        self.assertAlmostEqual(d, engine.PILE_STANDOFF, places=6)

    def test_separate_moves_off_occupied_spot(self):
        occ = [(0.5, 0.5)]
        tx, ty = engine.separate(0.5, 0.5, occ, "seed-a")
        self.assertGreaterEqual(
            ((tx - 0.5) ** 2 + (ty - 0.5) ** 2) ** 0.5,
            engine.MIN_SEPARATION - 1e-9)

    def test_separate_is_deterministic_and_per_agent(self):
        occ = [(0.5, 0.5)]
        a1 = engine.separate(0.5, 0.5, occ, "agent-1")
        a1b = engine.separate(0.5, 0.5, occ, "agent-1")
        a2 = engine.separate(0.5, 0.5, occ, "agent-2")
        self.assertEqual(a1, a1b)
        self.assertNotEqual(a1, a2)

    def test_clear_target_untouched(self):
        self.assertEqual(engine.separate(0.3, 0.3, [(0.7, 0.7)], "s"),
                         (0.3, 0.3))

    def test_travel_to_pile_stands_off_and_apart(self):
        pile = PileView("p1", 3, 0.6, 0.6, 10.0)
        eff = engine.apply_choice(
            Choice("travel_to_pile", "p1"), view(0.2, 0.2), [pile], 1000.0,
            {}, [], 1.0, {"occupied": [(0.6, 0.6)]})
        tx, ty = eff.movement["waypoints"][-1]
        d = ((tx - 0.6) ** 2 + (ty - 0.6) ** 2) ** 0.5
        self.assertGreater(d, 0.015)      # never ON the pile


class TestMuster(unittest.TestCase):
    def test_worldgen_places_exactly_five(self):
        for seed in (1, 77, 5001):
            w = worldgen.generate_world(seed, "u:test")
            self.assertEqual(len(w["muster_points"]), 5)
            for m in w["muster_points"]:
                self.assertTrue(0.0 < m["x"] < 1.0 and 0.0 < m["y"] < 1.0)

    def test_deposit_routes_to_nearest_flag(self):
        muster = [{"x": 0.9, "y": 0.9}, {"x": 0.3, "y": 0.25}]
        eff = engine.apply_choice(
            Choice("go_home_deposit"), view(0.25, 0.2, {"3": 5.0}), [],
            1000.0, {}, [], 1.0, {"muster": muster})
        tx, ty = eff.movement["waypoints"][-1]
        self.assertLess(((tx - 0.3) ** 2 + (ty - 0.25) ** 2) ** 0.5, 0.05)
        self.assertEqual(eff.schedule[0], "deposit_arrival")

    def test_no_muster_falls_back_to_legacy_home(self):
        eff = engine.apply_choice(
            Choice("go_home_deposit"), view(0.2, 0.2, {"3": 5.0}), [],
            1000.0, {}, [], 1.0, {})
        tx, ty = eff.movement["waypoints"][-1]
        self.assertLess(((tx - 0.5) ** 2 + (ty - 0.5) ** 2) ** 0.5, 0.05)


class TestTeleportAffinity(unittest.TestCase):
    PORTAL = [{"x": 0.5, "y": 0.5, "to_world": "w2"}]

    def _options(self, affinity):
        req = engine.on_event(
            "decide", view(), [], 1000.0, {}, {},
            self.PORTAL, {"genotype": {"Teleport Affinity": affinity}})
        return req.options

    def test_low_affinity_never_offered_portal(self):
        self.assertNotIn("take_portal", self._options(500.0))

    def test_high_affinity_offered_portal(self):
        self.assertIn("take_portal", self._options(9000.0))

    def test_absent_locus_defaults_to_willing(self):
        req = engine.on_event("decide", view(), [], 1000.0, {}, {},
                              self.PORTAL, {"genotype": {}})
        self.assertIn("take_portal", req.options)


class TestStyles(unittest.TestCase):
    def test_pick_is_deterministic(self):
        g = {"Curiosity": 8000, "Patience": 1000}
        env = {"neighbours": [], "explored_frac": 0.1}
        self.assertEqual(styles.pick_style(g, env, "a:1"),
                         styles.pick_style(g, env, "a:1"))

    def test_genotype_shapes_the_walk(self):
        env = {"neighbours": [], "explored_frac": 0.1}
        sweeper = {k: 500.0 for k in
                   ("Curiosity", "Patience", "Wanderlust", "Loyalty",
                    "Cooperativeness", "Courage")}
        sweeper.update({"Prudence": 9500.0, "Knowledge": 9500.0})
        jitterbug = {k: 500.0 for k in sweeper}
        jitterbug.update({"Curiosity": 9500.0, "Patience": 200.0})
        self.assertEqual(styles.pick_style(sweeper, env, "s:1"), "lawnmower")
        self.assertEqual(styles.pick_style(jitterbug, env, "s:1"), "brownian")

    def test_swarm_needs_company(self):
        flocker = {"Loyalty": 9800.0, "Cooperativeness": 9800.0,
                   "Prudence": 100.0, "Knowledge": 100.0, "Curiosity": 100.0,
                   "Patience": 9800.0, "Wanderlust": 100.0, "Courage": 9800.0}
        alone = styles.style_scores(flocker, {"neighbours": [],
                                              "explored_frac": 0.5})
        crowd = styles.style_scores(flocker, {"neighbours": [(0.4, 0.4)] * 4,
                                              "explored_frac": 0.5})
        self.assertEqual(alone["swarm"], 0.0)
        self.assertGreater(crowd["swarm"], 0.9)

    def test_swarm_target_moves_toward_flock(self):
        tx, ty = styles.target_for("swarm", 0.2, 0.2, frozenset(),
                                   {"neighbours": [(0.8, 0.8)]}, "z")
        self.assertGreater(tx, 0.3)
        self.assertGreater(ty, 0.3)

    def test_lawnmower_sweeps_row_major(self):
        t1 = styles.target_for("lawnmower", 0.5, 0.5, frozenset(), {}, "z")
        self.assertEqual(t1, engine.cell_centre((0, 0)))
        done_first_row = frozenset((i, 0) for i in range(engine.GRID_K))
        t2 = styles.target_for("lawnmower", 0.5, 0.5, done_first_row, {}, "z")
        self.assertEqual(t2, engine.cell_centre((0, 1)))

    def test_targets_stay_in_bounds(self):
        for style in styles.STYLES:
            for s in range(20):
                tx, ty = styles.target_for(style, 0.05, 0.95, frozenset(),
                                           {"neighbours": [(0.5, 0.5)]},
                                           f"b:{s}")
                self.assertTrue(0.0 <= tx <= 1.0 and 0.0 <= ty <= 1.0,
                                f"{style} escaped: {tx},{ty}")

    def test_style_rides_the_explored_event(self):
        eff = engine.apply_choice(
            Choice("explore_frontier"), view(), [], 1000.0, {}, [], 1.0,
            {"genotype": {"Prudence": 9500.0, "Knowledge": 9500.0}})
        self.assertEqual(eff.schedule[0], "explored")
        self.assertIn(eff.schedule[3].get("style"), styles.STYLES)


if __name__ == "__main__":
    unittest.main()
