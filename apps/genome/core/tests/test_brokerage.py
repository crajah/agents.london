"""Capability brokerage — Rules 8.6-8.8: the holder performs, the result is
testimony, honesty is the provider's and credulity the receiver's."""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from genome_core import skills as S
from genome_core.engine import AgentView, Choice, on_event, apply_choice
from genome_core.genotype import RANGES

G_HONEST = {**{k: 5000.0 for k in RANGES}, "Honesty": 9999.0}
G_LIAR = {**{k: 5000.0 for k in RANGES}, "Honesty": 1.0}


class TestHonestyGate(unittest.TestCase):
    def test_honest_appraisal_is_true_liar_inverts(self):
        stock = {"3": 1.0, "7": 50.0, "9": 2.0, "12": 40.0}
        honest = S.perform({"key": "h", "genotype": G_HONEST}, "Appraisal",
                           "req1", world_stock=stock)
        liar = S.perform({"key": "l", "genotype": G_LIAR}, "Appraisal",
                         "req1", world_stock=stock)
        self.assertIn("3", honest["scarce"])
        self.assertIn("7", honest["deep"])
        self.assertIn("3", liar["deep"])        # inverted, consistently

    def test_liar_lies_the_same_way_twice(self):
        p = {"key": "l", "genotype": G_LIAR,
             "known_piles": ["p1", "p2", "p3"]}
        a = S.perform(p, "Prospecting", "reqX")
        b = S.perform(p, "Prospecting", "reqX")
        self.assertEqual(a["piles"], b["piles"])
        self.assertNotEqual(a["piles"], ["p1", "p2", "p3"])

    def test_honest_prospector_shares_the_real_map(self):
        p = {"key": "h", "genotype": G_HONEST,
             "known_piles": ["p1", "p2"]}
        self.assertEqual(S.perform(p, "Prospecting", "r")["piles"],
                         ["p1", "p2"])

    def test_chronicle_inversion(self):
        p = {"key": "l", "genotype": G_LIAR,
             "opinions": {"s": {"Honesty": {"estimate": 9000.0,
                                            "weight": 4.0}}}}
        claims = S.perform(p, "Chronicle", "r")["claims"]
        self.assertAlmostEqual(claims[0]["estimate"], 1000.0)


class TestActs(unittest.TestCase):
    A = AgentView("a1", "h", "h", 0.5, 0.5, {}, frozenset(), frozenset())

    def test_request_offered_only_with_known_remote_holder(self):
        base = {"genotype": {}, "time_scale": 1.0}
        req = on_event("decide", self.A, [], 0.0, {}, {}, [], base)
        self.assertNotIn("request_service", req.options)
        ctx = {**base, "known_remote_holders": [("b2", "Appraisal")]}
        req2 = on_event("decide", self.A, [], 0.0, {}, {}, [], ctx)
        self.assertIn("request_service", req2.options)
        eff = apply_choice(Choice("request_service"), self.A, [], 0.0,
                           dict(req2.context), [], 1.0, ctx)
        self.assertEqual(eff.service, ("request", "b2", "Appraisal"))

    def test_holder_side_event_and_answers(self):
        req = on_event("service_request", self.A, [], 0.0,
                       {"requester": "r9", "skill": "Chronicle",
                        "credit": 2}, {}, [], {})
        self.assertEqual(req.options,
                         ("perform_service", "refuse_service"))
        self.assertEqual(req.context["favours_owed_to_me"], 2)
        eff = apply_choice(Choice("perform_service"), self.A, [], 0.0,
                           {"requester": "r9", "skill": "Chronicle"},
                           [], 1.0, {})
        self.assertEqual(eff.service, ("perform", "r9", "Chronicle"))
        eff2 = apply_choice(Choice("refuse_service"), self.A, [], 0.0,
                            {"requester": "r9", "skill": "Chronicle"},
                            [], 1.0, {})
        self.assertEqual(eff2.service[0], "refuse")


if __name__ == "__main__":
    unittest.main()
