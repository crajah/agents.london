"""Capabilities — skills-spec §1: one roll, a quarter plain, luck not
inheritance, part of what regeneration restores."""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from genome_core import skills as S


class TestBirthRoll(unittest.TestCase):
    def test_rule_1_1a_a_quarter_born_plain(self):
        rolls = [S.roll_capability(f"agent-{i}") for i in range(4000)]
        plain = sum(1 for r in rolls if r is None)
        self.assertAlmostEqual(plain / 4000, 0.25, delta=0.03)

    def test_at_most_one_capability(self):
        for i in range(50):
            r = S.roll_capability(f"a{i}")
            if r is not None:
                self.assertEqual(set(r), {"kind", "name"})
                pool = S.CATALOGUE if r["kind"] == "skill" else S.TOOLS
                self.assertIn(r["name"], pool)

    def test_deterministic_per_agent(self):
        self.assertEqual(S.roll_capability("x"), S.roll_capability("x"))

    def test_rule_1_2a_no_transfer_surface_exists(self):
        self.assertFalse([n for n in dir(S)
                          if "transfer" in n or "give" in n or "trade" in n])


class TestSurvival(unittest.TestCase):
    def test_rule_1_3_regeneration_keeps_the_capability(self):
        # regenerate() wipes only the EARNED keys; capability is not among
        # them -- assert against the actual wipe list in drain.regenerate
        import inspect
        from genome_core import drain
        src = inspect.getsource(drain.regenerate)
        wiped = src[src.index("reborn = {**agent_payload"):
                    src.index("reborn.pop(")]
        self.assertNotIn("capability", wiped)


class TestSelfKnowledge(unittest.TestCase):
    def test_describe_both_states(self):
        self.assertIn("Porterage",
                      S.describe({"capability": {"kind": "skill",
                                                 "name": "Porterage"}}))
        self.assertIn("no capability", S.describe({"capability": None}))


if __name__ == "__main__":
    unittest.main()


class TestToolLottery(unittest.TestCase):
    def test_rule_1_1_one_class_or_the_other(self):
        from collections import Counter
        kinds = Counter()
        for i in range(4000):
            r = S.roll_capability(f"tl{i}")
            if r:
                kinds[r["kind"]] += 1
                if r["kind"] == "tool":
                    self.assertIn(r["name"], S.TOOLS)
        self.assertAlmostEqual(
            kinds["tool"] / (kinds["tool"] + kinds["skill"]),
            S.TOOL_SHARE, delta=0.05)

    def test_tools_are_remote_capable_by_definition(self):
        for name in S.TOOLS:
            self.assertTrue(S.remote_capable(name))

    def test_withdrawn_tool_still_describes_without_crashing(self):
        d = S.describe({"capability": {"kind": "tool", "name": "Ghost"}})
        self.assertIn("withdrawn", d)
