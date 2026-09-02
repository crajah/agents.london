"""Coordination tier — skills-spec §4.7: Amenability gates, rarity tracks
reach (5.3), owners see every modification (5.2 via the notify path)."""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from genome_core import skills as S
from genome_core.engine import AgentView, Choice, on_event, apply_choice


class TestAmenabilityGate(unittest.TestCase):
    def test_disposition_decides_deterministically(self):
        biddable = {"genotype": {"Amenability": 9900.0}}
        stubborn = {"genotype": {"Amenability": 100.0}}
        led = sum(S.amenable(biddable, f"s{i}") for i in range(200))
        free = sum(S.amenable(stubborn, f"s{i}") for i in range(200))
        self.assertGreater(led, 180)
        self.assertLess(free, 20)
        self.assertEqual(S.amenable(biddable, "same"),
                         S.amenable(biddable, "same"))


class TestRarity(unittest.TestCase):
    def test_rule_5_3_coordination_is_rarer(self):
        from collections import Counter
        rolls = Counter()
        for i in range(8000):
            r = S.roll_capability(f"r{i}")
            if r:
                rolls[r["name"]] += 1
        coord = sum(rolls[n] for n in S.WEIGHTS)
        common = rolls["Porterage"]
        # each coordination skill arrives ~4x less often than a common one
        self.assertLess(rolls["Master Orchestrator"], common * 0.5)
        self.assertGreater(coord, 0)


class TestActs(unittest.TestCase):
    A = AgentView("a1", "h", "h", 0.5, 0.5, {}, frozenset(), frozenset())

    def test_orchestrator_sees_enlist_until_crew_full(self):
        ctx = {"skill": "Master Orchestrator", "crew_size": 0}
        req = on_event("encounter", self.A, [], 0.0,
                       {"other": {"agent_uuid": "b"}}, {}, [], ctx)
        self.assertIn("enlist", req.options)
        full = on_event("encounter", self.A, [], 0.0,
                        {"other": {"agent_uuid": "b"}}, {}, [],
                        {**ctx, "crew_size": 6})
        self.assertNotIn("enlist", full.options)

    def test_delegation_needs_an_objective_to_hand(self):
        req = on_event("encounter", self.A, [], 0.0,
                       {"other": {"agent_uuid": "b"}}, {}, [],
                       {"skill": "Delegation", "has_objective": True})
        self.assertIn("delegate_task", req.options)
        bare = on_event("encounter", self.A, [], 0.0,
                        {"other": {"agent_uuid": "b"}}, {}, [],
                        {"skill": "Delegation", "has_objective": False})
        self.assertNotIn("delegate_task", bare.options)

    def test_convoke_and_answer(self):
        ctx = {"skill": "Convocation", "neighbours": [(0.5, 0.52)],
               "genotype": {}, "time_scale": 1.0}
        req = on_event("decide", self.A, [], 0.0, {}, {}, [], ctx)
        self.assertIn("convoke", req.options)
        eff = apply_choice(Choice("convoke"), self.A, [], 0.0, {}, [], 1.0,
                           ctx)
        self.assertTrue(eff.convoke)
        called = on_event("decide", self.A, [], 0.0,
                          {"convoked_to": [0.8, 0.8],
                           "convoked_by": "Asha"}, {}, [],
                          {"genotype": {}, "time_scale": 1.0})
        self.assertIn("answer_convocation", called.options)
        self.assertEqual(called.context["convoked_by"], "Asha")
        walk = apply_choice(Choice("answer_convocation"), self.A, [], 0.0,
                            {"convoked_to": [0.8, 0.8]}, [], 1.0,
                            {"genotype": {}})
        self.assertIsNotNone(walk.movement)


if __name__ == "__main__":
    unittest.main()
