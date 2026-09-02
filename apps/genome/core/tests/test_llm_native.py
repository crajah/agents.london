"""LLM-native tier — skills-spec §4.8 with Rules 5.1/5.2: Amenability
resists, owners see, Introspection is the counter, death washes out."""
import inspect as _inspect
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from genome_core import drain
from genome_core.engine import AgentView, on_event
from genome_core.genotype import RANGES
from genome_core.prompt import system_prompt

G = {k: 5000.0 for k in RANGES}
MODS = [{"by": "x", "by_name": "Sable",
         "text": "You find yourself inclined toward: hoard kind 4"}]
SEEDS = [{"kind": "seeded", "by": "x", "by_name": "Sable",
          "text": "gather kind 4"}]


class TestSeams(unittest.TestCase):
    def test_blind_agent_cannot_see_the_seam(self):
        p = system_prompt(G, {}, {}, [], prompt_mods=MODS,
                          influences=SEEDS)
        self.assertIn("inclined toward", p)          # the line is woven in
        self.assertNotIn("smithed", p)               # with no label at all
        self.assertNotIn("Sable", p)

    def test_introspection_names_every_author(self):
        p = system_prompt(G, {}, {}, [],
                          capability={"kind": "skill",
                                      "name": "Introspection"},
                          prompt_mods=MODS, influences=SEEDS)
        self.assertIn("smithed into you by Sable", p)
        self.assertIn("seeded by Sable", p)

    def test_clean_introspection_says_so(self):
        p = system_prompt(G, {}, {}, [],
                          capability={"kind": "skill",
                                      "name": "Introspection"})
        self.assertIn("nothing has been placed in you", p)


class TestActs(unittest.TestCase):
    A = AgentView("a1", "h", "h", 0.5, 0.5, {}, frozenset(), frozenset())

    def test_options_gated_on_holding_and_having_purpose(self):
        for skill, act in (("Objective Seeding", "seed_objective"),
                           ("Promptsmithing", "smith_prompt")):
            req = on_event("encounter", self.A, [], 0.0,
                           {"other": {"agent_uuid": "b"}}, {}, [],
                           {"skill": skill, "has_objective": True})
            self.assertIn(act, req.options, skill)
            bare = on_event("encounter", self.A, [], 0.0,
                            {"other": {"agent_uuid": "b"}}, {}, [],
                            {"skill": skill, "has_objective": False})
            self.assertNotIn(act, bare.options, skill)


class TestWashout(unittest.TestCase):
    def test_death_restores_the_original_state(self):
        # Rule 6.15/1.3: regeneration restores the ORIGINAL agent --
        # tampering is earned life and washes out
        src = _inspect.getsource(drain.regenerate)
        wiped = src[src.index("reborn = {**agent_payload"):]
        self.assertIn('"influences": []', wiped)
        self.assertIn('"prompt_mods": []', wiped)


if __name__ == "__main__":
    unittest.main()
