"""Pools — Rules 9.3b/9.3d/9.3e, 3.8e: closed-form recovery, the watch-cost,
the mana price of violence, incapacitation with a floor."""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from genome_core import vitals as V

DAY = 86400.0


class TestClosedForm(unittest.TestCase):
    def test_recovery_is_derived_never_ticked(self):
        p = {"genotype": {"reStamina": 1.0, "Immune Vigilance": 0.0},
             "stamina": 0.0, "stamina_at": 0.0, "stamina_max": 1.0}
        half = V.stamina_now(p, DAY)
        self.assertAlmostEqual(half, 0.5, delta=0.02)
        self.assertAlmostEqual(V.stamina_now(p, 2 * DAY), 1.0, delta=0.02)

    def test_rule_3_8e_vigilance_taxes_recovery(self):
        lax = {"genotype": {"reStamina": 1.0, "Immune Vigilance": 100.0},
               "stamina": 0.2, "stamina_at": 0.0, "stamina_max": 1.0}
        vigilant = {**lax,
                    "genotype": {"reStamina": 1.0,
                                 "Immune Vigilance": 9900.0}}
        self.assertGreater(V.stamina_now(lax, DAY),
                           V.stamina_now(vigilant, DAY))

    def test_cap_is_the_burned_maximum(self):
        p = {"genotype": {"reStamina": 1.0}, "stamina": 0.5,
             "stamina_at": 0.0, "stamina_max": 0.6}
        self.assertAlmostEqual(V.stamina_now(p, 10 * DAY), 0.6)


class TestIncapacitation(unittest.TestCase):
    def test_downed_until_the_floor_then_up(self):
        p = {"genotype": {"reStamina": 1.0, "Immune Vigilance": 0.0},
             "stamina": 0.0, "stamina_at": 0.0, "stamina_max": 1.0}
        self.assertTrue(V.incapacitated(p, 60.0))
        self.assertFalse(V.incapacitated(p, DAY))

    def test_zero_maximum_is_death_not_incapacitation(self):
        self.assertFalse(V.incapacitated(
            {"stamina": 0.0, "stamina_max": 0.0}, 1.0))


class TestMana(unittest.TestCase):
    def test_attack_price_exists_and_recovers(self):
        p = {"genotype": {"reMana": 1.0}, "mana": 1.0, "mana_at": 0.0}
        spent = V.set_mana(p, V.mana_now(p, 0.0) - V.MANA_ATTACK_COST, 0.0)
        self.assertAlmostEqual(spent["mana"], 0.7)
        self.assertGreater(V.mana_now(spent, DAY), 0.9)


if __name__ == "__main__":
    unittest.main()
