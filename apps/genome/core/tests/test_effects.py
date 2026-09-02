"""Calibration §5 complete: every construction's standing effect."""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from genome_core import construction as C
from genome_core import flood
from genome_core import pathogen
from genome_core.combat import Fighter, resolve


def standing(*names):
    return [{"name": n, "complete": True} for n in names]


class TestEffectsTable(unittest.TestCase):
    def test_neutral_when_nothing_stands(self):
        fx = C.effects_from([])
        self.assertEqual(fx["mine_rate_mult"], 1.0)
        self.assertEqual(fx["regen_mult"], 1.0)
        self.assertEqual(fx["cargo_bonus"], 0.0)
        self.assertFalse(fx["map_room"])
        self.assertFalse(fx["strain_guard"])

    def test_each_building_moves_exactly_its_knob(self):
        for name, key, value in [
            ("store", "stock_ceiling_bonus", 25.0),
            ("rampart", "defence_mult", 1.2),
            ("foundation", "build_time_mult", 0.5),
            ("kiln", "mine_stint_bonus", 2.0),
            ("toolhouse", "mine_rate_mult", 1.5),
            ("forge", "attack_mult", 1.25),
            ("grove", "regen_mult", 1.25),
            ("granary", "cargo_bonus", 5.0),
            ("infirmary", "combat_recovery_mult", 0.5),
            ("sanatorium", "recovery_mult", 2.0),
            ("cairn", "sight_mult", 1.25),
            ("beacon", "pace_mult", 1.15),
        ]:
            self.assertEqual(C.effects_from(standing(name))[key], value, name)
        self.assertTrue(C.effects_from(standing("library"))["map_room"])
        self.assertTrue(C.effects_from(standing("apothecary"))["strain_guard"])

    def test_spent_or_destroyed_confers_nothing(self):
        for dead in ({"spent": True}, {"destroyed": True}, {"complete": False}):
            fx = C.effects_from([{"name": "toolhouse", "complete": True,
                                  **dead}])
            self.assertEqual(fx["mine_rate_mult"], 1.0, dead)


class TestObservatory(unittest.TestCase):
    def test_window_doubles_only_while_standing(self):
        base = flood.countdown_window({"time_scale": 1.0})
        watched = flood.countdown_window({"time_scale": 1.0,
                                          "observatory_standing": True})
        self.assertAlmostEqual(watched, base * 2)


class TestSanatorium(unittest.TestCase):
    def test_recovery_runs_twice_as_fast(self):
        rec = {"strain": {"strain_uuid": "s1", "signature": [0.5] * 6},
               "caught_at": 0.0, "synth_done_at": 1000.0}
        pl = {"genotype": {}, "identity": "i", "infections": [rec]}
        still, _ = pathogen.settle(dict(pl), 600.0)
        self.assertEqual(len(still["infections"]), 1)      # 600 < 1000
        healed, _ = pathogen.settle(dict(pl), 600.0, recovery_mult=2.0)
        self.assertEqual(len(healed["infections"]), 0)     # 600 > 1000/2


class TestCombatMults(unittest.TestCase):
    G = {k: 5000.0 for k in ("Intelligence", "Dexterity", "Courage",
                             "Agility", "Knowledge", "Wisdom", "Charisma",
                             "Aggression", "Attrition", "Prudence")}

    def _p(self, **kw):
        import random
        a = Fighter("a", dict(self.G), 1.0, 1.0, {})
        d = Fighter("d", dict(self.G), 1.0, 1.0, {})
        return resolve(a, d, "seed", **kw)["p_attacker"]

    def test_forge_arms_and_rampart_shields(self):
        base = self._p()
        self.assertGreater(self._p(att_mult=1.25), base)
        self.assertLess(self._p(dfd_mult=1.2), base)

    def test_infirmary_halves_the_toll(self):
        full = resolve(Fighter("a", dict(self.G), 1.0, 1.0, {}),
                       Fighter("d", dict(self.G), 1.0, 1.0, {}), "s")
        half = resolve(Fighter("a", dict(self.G), 1.0, 1.0, {}),
                       Fighter("d", dict(self.G), 1.0, 1.0, {}), "s",
                       stamina_mult=0.5)
        self.assertAlmostEqual(half["loser_stamina_delta"],
                               full["loser_stamina_delta"] / 2)


if __name__ == "__main__":
    unittest.main()
