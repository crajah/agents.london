"""Determinism harness (BUILD testing strategy): the same seed and the same
scripted decisions reproduce the same world, so any divergence is traceable
to a code change rather than to chance. Everything here runs the PURE layer
twice and diffs -- no storage, no clock, no model."""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from genome_core import combat, engine, worldgen
from genome_core.genotype import RANGES
from genome_core.skills import roll_capability

G = {k: 5000.0 for k in RANGES}


def scripted_run(seed: int) -> list:
    """A fixed journey: decide -> travel -> arrive -> mine -> deposit,
    driven by the stub decider. Returns the full effects trace."""
    agent = engine.AgentView(f"agent-{seed}", "home", "home", 0.5, 0.5,
                             {}, frozenset(), frozenset())
    piles = [engine.PileView(f"p{i}", i % 2, 0.2 + i * 0.1, 0.3, 20.0)
             for i in range(4)]
    trace = []
    now = 1_000_000.0
    payload: dict = {}
    for step in range(12):
        res = engine.on_event("decide", agent, piles, now, payload,
                              {"0": 3.0}, [], {"genotype": dict(G),
                                               "time_scale": 1.0})
        choice = engine.stub_decider(res, seed)
        eff = engine.apply_choice(choice, agent, piles, now, res.context,
                                  [], 1.0, {"genotype": dict(G)})
        trace.append((choice.option, choice.target, eff.movement,
                      eff.mine_pile, eff.schedule))
        now += 100.0
    return trace


class TestDeterminism(unittest.TestCase):
    def test_same_seed_same_world(self):
        for seed in (7, 8):
            self.assertEqual(worldgen.generate_world(seed, "u"),
                             worldgen.generate_world(seed, "u"))

    def test_different_seeds_differ(self):
        self.assertNotEqual(worldgen.generate_world(1, "u")["piles"],
                            worldgen.generate_world(2, "u")["piles"])

    def test_scripted_journey_replays_exactly(self):
        self.assertEqual(scripted_run(42), scripted_run(42))

    def test_combat_replays_exactly(self):
        a = combat.Fighter("a", dict(G), 1.0, 1.0, {"1": 5.0})
        d = combat.Fighter("d", dict(G), 1.0, 1.0, {"2": 3.0})
        self.assertEqual(combat.resolve(a, d, "duel-1"),
                         combat.resolve(a, d, "duel-1"))
        self.assertNotEqual(
            combat.resolve(a, d, "duel-1")["p_attacker"], 0.0)

    def test_capability_lottery_replays_exactly(self):
        self.assertEqual([roll_capability(f"x{i}") for i in range(50)],
                         [roll_capability(f"x{i}") for i in range(50)])


if __name__ == "__main__":
    unittest.main()
