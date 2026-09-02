"""A2A word — Rules 9.1c/9.1d, 13.5a/13.5b, 6.10b."""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from genome_core import word as W


class TestAddressability(unittest.TestCase):
    def test_meeting_and_introduction_grant_reach(self):
        p = W.meet({"key": "a"}, "b")
        self.assertEqual(p["addressable"], ["b"])
        p = W.introduce(p, "c")               # told of c: addressable
        self.assertEqual(p["addressable"], ["b", "c"])
        p = W.introduce(p, "a")               # never oneself
        self.assertNotIn("a", p["addressable"])

    def test_rolodex_is_bounded_newest_kept(self):
        p = {"addressable": [f"u{i}" for i in range(W.MAX_ADDRESSABLE)]}
        p = W.meet(p, "fresh")
        self.assertEqual(len(p["addressable"]), W.MAX_ADDRESSABLE)
        self.assertEqual(p["addressable"][-1], "fresh")
        self.assertNotIn("u0", p["addressable"])


class TestRelayDecay(unittest.TestCase):
    def test_6_10b_each_hop_folds_weaker(self):
        moves = []
        for relays in (0, 1, 2, 3):
            p = W.fold_testimony({"key": "x"}, "s", "Honesty", 9000.0,
                                 relays, owner_sourced=False)
            moves.append(p["opinions"]["s"]["Honesty"]["estimate"] - 5000.0)
        self.assertTrue(moves[0] > moves[1] > moves[2] > moves[3] > 0)

    def test_owner_sourced_folds_weaker_still(self):
        plain = W.fold_testimony({}, "s", "Honesty", 9000.0, 1, False)
        marked = W.fold_testimony({}, "s", "Honesty", 9000.0, 1, True)
        self.assertLess(marked["opinions"]["s"]["Honesty"]["estimate"],
                        plain["opinions"]["s"]["Honesty"]["estimate"])


class TestLoyalty(unittest.TestCase):
    def test_13_5b_loyalty_disposes_deterministically(self):
        loyal = {"genotype": {"Loyalty": 9900.0}}
        loose = {"genotype": {"Loyalty": 100.0}}
        leaks_loyal = sum(W.would_relay_confidence(loyal, f"s{i}")
                          for i in range(200))
        leaks_loose = sum(W.would_relay_confidence(loose, f"s{i}")
                          for i in range(200))
        self.assertLess(leaks_loyal, 20)
        self.assertGreater(leaks_loose, 150)
        self.assertEqual(W.would_relay_confidence(loyal, "same"),
                         W.would_relay_confidence(loyal, "same"))


class TestHeard(unittest.TestCase):
    def test_bounded_and_marked(self):
        p = {}
        for i in range(10):
            p = W.hear(p, f"claim {i}", "agent:z", relays=i,
                       owner_sourced=(i % 2 == 0))
        self.assertEqual(len(p["heard"]), W.MAX_HEARD)
        self.assertEqual(p["heard"][-1]["text"], "claim 9")
        self.assertTrue(any(h["owner_sourced"] for h in p["heard"]))


class TestStrongest(unittest.TestCase):
    def test_extremity_times_weight_wins(self):
        p = {"opinions": {
            "meek": {"Honesty": {"estimate": 5100.0, "weight": 9.0}},
            "vivid": {"Aggression": {"estimate": 9500.0, "weight": 3.0}}}}
        subject, locus, _ = W.strongest_opinion(p)
        self.assertEqual((subject, locus), ("vivid", "Aggression"))
        self.assertIsNone(W.strongest_opinion({}))


if __name__ == "__main__":
    unittest.main()
