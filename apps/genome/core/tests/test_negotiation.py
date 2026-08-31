"""Execution-spec §7: six turns, binding acceptance, death by empty purse."""
import unittest

from genome_core import negotiation as N


class TestNegotiation(unittest.TestCase):
    def _open(self):
        return N.open_state("alice", "bob", 0.0)

    def test_opener_moves_first_and_turns_alternate(self):
        s = self._open()
        self.assertEqual(N.whose_turn(s), "alice")
        s, out = N.apply_turn(s, "alice", "propose",
                              {"give": {"3": 2}, "want": {"7": 1}},
                              {"3": 5.0}, {"7": 4.0})
        self.assertEqual(out["kind"], "continue")
        self.assertEqual(N.whose_turn(s), "bob")

    def test_out_of_turn_dies(self):
        s = self._open()
        _, out = N.apply_turn(s, "bob", "propose",
                              {"give": {"1": 1}, "want": {}}, {}, {})
        self.assertEqual(out["kind"], "dead")

    def test_acceptance_binds_and_swaps(self):
        s = self._open()
        s, _ = N.apply_turn(s, "alice", "propose",
                            {"give": {"3": 2}, "want": {"7": 1}},
                            {"3": 5.0}, {"7": 4.0})
        s, out = N.apply_turn(s, "bob", "accept", None,
                              {"7": 4.0}, {"3": 5.0})
        self.assertEqual(out["kind"], "exchange")
        self.assertEqual(out["gains"]["bob"], {"3": 2.0})
        self.assertEqual(out["gains"]["alice"], {"7": 1.0})
        self.assertEqual(s["status"], "done")

    def test_empty_purse_kills_not_halves(self):
        s = self._open()
        s, _ = N.apply_turn(s, "alice", "propose",
                            {"give": {"3": 9}, "want": {"7": 1}},
                            {"3": 2.0}, {"7": 4.0})
        s, out = N.apply_turn(s, "bob", "accept", None,
                              {"7": 4.0}, {"3": 2.0})   # alice lacks 9
        self.assertEqual(out["kind"], "dead")
        self.assertIn("afford", out["why"])
        self.assertEqual(s["status"], "dead")

    def test_six_turns_and_it_dies(self):
        s = self._open()
        actors = ["alice", "bob"] * 3
        for i, who in enumerate(actors):
            s, out = N.apply_turn(s, who, "counter" if i else "propose",
                                  {"give": {"1": 1}, "want": {"2": 1}},
                                  {"1": 9.0}, {"2": 9.0})
        self.assertEqual(out["kind"], "dead")
        self.assertIn("six turns", out["why"])

    def test_walk_away_ends_it(self):
        s = self._open()
        s, _ = N.apply_turn(s, "alice", "propose",
                            {"give": {"3": 1}, "want": {"7": 1}},
                            {"3": 5.0}, {"7": 4.0})
        s, out = N.apply_turn(s, "bob", "walk_away", None, {}, {})
        self.assertEqual(out["kind"], "dead")
        self.assertEqual(s["status"], "dead")

    def test_fallback_first_move_proposes_top_holding(self):
        s = self._open()
        act, off = N.fallback_turn(s, "alice", {"3": 5.0, "7": 1.0})
        self.assertEqual(act, "propose")
        self.assertEqual(off["give"], {"3": 1.0})

    def test_fallback_facing_offer_walks(self):
        s = self._open()
        s, _ = N.apply_turn(s, "alice", "propose",
                            {"give": {"3": 1}, "want": {}}, {"3": 2.0}, {})
        act, _ = N.fallback_turn(s, "bob", {"9": 3.0})
        self.assertEqual(act, "walk_away")


if __name__ == "__main__":
    unittest.main()
