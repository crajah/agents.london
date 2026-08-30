"""Terrain and routing — genome-spec Rules 5.3-5.5, execution-spec 2.1a/2.2."""
import math
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from genome_core import forms, path, worldgen


ROCK = [{"x": 0.5, "y": 0.5, "r": 0.1}]


class TestPath(unittest.TestCase):
    def test_direct_when_clear(self):
        pts = path.find_path([], 0.1, 0.1, 0.9, 0.9)
        self.assertEqual(pts, [(0.1, 0.1), (0.9, 0.9)])

    def test_detour_when_blocked(self):
        pts = path.find_path(ROCK, 0.1, 0.5, 0.9, 0.5)
        self.assertGreater(len(pts), 2)                     # it turned somewhere
        self.assertGreater(path.path_length(pts),
                           math.dist((0.1, 0.5), (0.9, 0.5)))
        # every leg of the route is clear of the rock
        for k in range(len(pts) - 1):
            self.assertTrue(path.segment_clear(*pts[k], *pts[k + 1], ROCK))

    def test_route_position_piecewise_and_monotone(self):
        pts = path.find_path(ROCK, 0.1, 0.5, 0.9, 0.5)
        r = forms.Route(tuple(pts), departed_at=0.0)
        self.assertEqual(forms.route_position(r, -1), (0.1, 0.5))
        end = forms.route_position(r, r.arrives_at + 1)
        self.assertAlmostEqual(end[0], 0.9)
        # travelled distance along the route is monotone in time
        last = -1.0
        prev = pts[0]
        travelled = 0.0
        for i in range(300):
            t = r.arrives_at * i / 299
            q = forms.route_position(r, t)
            travelled += math.dist(prev, q)
            prev = q
            self.assertGreaterEqual(travelled, last - 1e-9)
            last = travelled
        # total time = length / speed (Rule 2.2: derived, never stored)
        self.assertAlmostEqual(r.arrives_at,
                               path.path_length(pts) / forms.SPEED, places=6)

    def test_heading_follows_current_leg(self):
        r = forms.Route(((0.0, 0.0), (0.5, 0.0), (0.5, 0.5)), 0.0)
        t_mid_leg2 = r.leg_times()[1] + 1.0
        self.assertAlmostEqual(forms.route_heading(r, t_mid_leg2),
                               math.pi / 2, places=3)


class TestTerrainWorldgen(unittest.TestCase):
    def test_terrain_generated_and_recorded(self):
        w = worldgen.generate_world(3, "u")
        self.assertGreaterEqual(len(w["terrain"]), 5)
        for o in w["terrain"]:
            self.assertGreater(o["r"], 0.0)

    def test_piles_outside_terrain_and_reachable(self):
        w = worldgen.generate_world(3, "u")
        for p in w["piles"]:
            for o in w["terrain"]:
                self.assertGreater(
                    (p["x"] - o["x"]) ** 2 + (p["y"] - o["y"]) ** 2,
                    o["r"] ** 2, "pile inside a rock")
            self.assertIsNotNone(
                path.find_path(w["terrain"], *worldgen.HOME_XY, p["x"], p["y"]),
                "pile unreachable from home")

    def test_home_never_walled_in(self):
        for seed in range(8):
            w = worldgen.generate_world(seed, "u")
            hx, hy = worldgen.HOME_XY
            for o in w["terrain"]:
                self.assertGreater((hx - o["x"]) ** 2 + (hy - o["y"]) ** 2,
                                   o["r"] ** 2)


if __name__ == "__main__":
    unittest.main(verbosity=1)
