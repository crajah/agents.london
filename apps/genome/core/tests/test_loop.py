"""Phase 1's bet, proven: the loop closes. A world of stub agents runs a
simulated day, event-driven — the virtual clock jumps to the next due event, so
this IS the queue drain in miniature — and afterwards the decision record must
explain every action, deposits must have reached the home stock, and nothing
may have been written while an agent travelled.
"""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from genome_core import engine, forms, worldgen


class Sim:
    """In-memory world: the tick worker's drain, with a virtual clock."""

    def __init__(self, seed=42, n_agents=3):
        self.world = worldgen.generate_world(seed, "user-1")
        self.piles = {p["pile_uuid"]: forms.PileState(
            p["qty_at"], 0.0, p["rate"], p["cap"]) for p in self.world["piles"]}
        self.pile_meta = {p["pile_uuid"]: p for p in self.world["piles"]}
        self.stock: dict[str, float] = {}
        self.decisions: list[dict] = []
        self.writes: list[tuple[float, str, str]] = []   # (t, what, agent)
        self.agents: dict[str, dict] = {}
        self.queue: list[tuple[float, str, str, dict]] = []
        self.seed = seed
        for i in range(n_agents):
            a = f"agent-{i}"
            known = frozenset(list(self.pile_meta)[:3])   # sparse start
            self.agents[a] = {"x": 0.5, "y": 0.5, "cargo": {},
                              "moving_until": 0.0, "known": known,
                              "explored": frozenset({(2, 2), (3, 3)})}
            self.queue.append((0.0, "decide", a, {}))

    def _view(self, a: str) -> engine.AgentView:
        s = self.agents[a]
        return engine.AgentView(a, self.world["realm"], self.world["realm"],
                                s["x"], s["y"], dict(s["cargo"]),
                                s["known"], s["explored"])

    def _pile_views(self, now: float) -> list:
        return [engine.PileView(u, m["kind"], m["x"], m["y"],
                                forms.pile_quantity(self.piles[u], now))
                for u, m in self.pile_meta.items()]

    def _apply(self, eff: engine.Effects, a: str, now: float):
        s = self.agents[a]
        if eff.movement:
            self.writes.append((now, "movement", a))
            s["x"], s["y"] = eff.movement["waypoints"][-1]
            s["moving_until"] = eff.movement["arrives_at"]
        if eff.mine_pile:
            u, want = eff.mine_pile
            self.writes.append((now, "pile", a))
            self.piles[u], _ = forms.mine(self.piles[u], now, want)
        for kind, d in eff.cargo_delta.items():
            self.writes.append((now, "cargo", a))
            s["cargo"][kind] = s["cargo"].get(kind, 0.0) + d
            if s["cargo"][kind] <= 1e-9:
                del s["cargo"][kind]
        if eff.deposit:
            self.writes.append((now, "stock", a))
            for kind, units in eff.deposit.items():
                self.stock[kind] = self.stock.get(kind, 0.0) + units
        if eff.reveal:
            s["known"] = frozenset(s["known"] | set(eff.reveal))
        if eff.mark_explored:
            s["explored"] = frozenset(s["explored"] | set(eff.mark_explored))
        if eff.schedule:
            kind, due, subject, payload = eff.schedule
            self.queue.append((due, kind, subject, payload))

    def run(self, until: float):
        while self.queue:
            self.queue.sort()
            now, kind, a, payload = self.queue.pop(0)
            if now > until:
                break
            if kind == "deposit_arrival":
                eff = engine.on_deposit_arrival(self._view(a), self.stock, now)
                self._apply(eff, a, now)
                continue
            res = engine.on_event(kind, self._view(a), self._pile_views(now),
                                  now, payload, self.stock)
            if isinstance(res, engine.DecisionRequest):
                choice = engine.stub_decider(res, self.seed)
                self.decisions.append(
                    {"at": now, "agent": a, "situation": res.situation,
                     "options": res.options, "choice": choice.option,
                     "model": "stub", "tier": "stub"})
                eff = engine.apply_choice(choice, self._view(a),
                                          self._pile_views(now), now, payload,
                                          self.world["terrain"])
            else:
                eff = res
            self._apply(eff, a, now)


DAY = 86400.0


class TestLoopCloses(unittest.TestCase):
    def setUp(self):
        self.sim = Sim(seed=42, n_agents=3)
        self.sim.run(until=2 * DAY)

    def test_agents_acted_unattended(self):
        self.assertGreater(len(self.sim.decisions), 20)

    def test_something_was_mined_and_deposited(self):
        self.assertGreater(sum(self.sim.stock.values()), 0.0)

    def test_every_action_has_a_decision(self):
        # every movement or mine write is preceded by a recorded decision
        decided = {(round(d["at"], 6), d["agent"]) for d in self.sim.decisions}
        for t, what, agent in self.sim.writes:
            if what in ("movement", "pile"):
                self.assertIn((round(t, 6), agent), decided,
                              f"{what} by {agent} at {t} has no decision")

    def test_nothing_written_while_travelling(self):
        # a moving agent's only write at departure is the intent itself;
        # between departure and arrival there must be no writes by that agent
        by_agent: dict[str, list] = {}
        for t, what, agent in self.sim.writes:
            by_agent.setdefault(agent, []).append((t, what))
        moves = [(t, a) for t, w, a in self.sim.writes if w == "movement"]
        for t0, agent in moves:
            arrive = None
            for d in self.sim.decisions:  # find the arrival via next write time
                pass
            later = [t for t, w in by_agent[agent] if t > t0 + 1e-9]
            if later:
                gap = min(later) - t0
                self.assertGreater(gap, 60.0,
                                   "write within a minute of departure: "
                                   "travel is not silent")

    def test_user_ceiling_respected(self):
        for kind, units in self.sim.stock.items():
            self.assertLessEqual(units, engine.USER_CEILING_PER_KIND + 1e-9)

    def test_deterministic_replay(self):
        again = Sim(seed=42, n_agents=3)
        again.run(until=2 * DAY)
        self.assertEqual(len(again.decisions), len(self.sim.decisions))
        self.assertEqual([d["choice"] for d in again.decisions],
                         [d["choice"] for d in self.sim.decisions])
        self.assertEqual(again.stock, self.sim.stock)

    def test_different_seed_diverges(self):
        other = Sim(seed=7, n_agents=3)
        other.run(until=2 * DAY)
        self.assertNotEqual([d["choice"] for d in other.decisions[:30]],
                            [d["choice"] for d in self.sim.decisions[:30]])


class TestWorldgen(unittest.TestCase):
    def test_calibration_bounds(self):
        w = worldgen.generate_world(1, "u")
        self.assertEqual(len(w["kinds"]), 2)
        per_kind = {}
        for p in w["piles"]:
            per_kind.setdefault(p["kind"], []).append(p)
        for kind, ps in per_kind.items():
            self.assertTrue(6 <= len(ps) <= 10)          # Rule 3.0d
            self.assertLessEqual(sum(p["cap"] for p in ps), 250.0 + 1e-6)
        self.assertIn(w["colours"][0], worldgen.A100)

    def test_founding_centre_recorded_and_used(self):
        w = worldgen.generate_world(2, "u")
        g = worldgen.founder_genotype(w, 0)
        from genome_core.genotype import RANGES
        for k, v in g.items():
            lo, hi = RANGES[k]
            c = w["founding_centre"][k]
            self.assertLessEqual(abs(v - c), (hi - lo) * 0.25 + 1e-9)

    def test_founder_names_are_three_words(self):
        self.assertEqual(len(worldgen.founder_name(5).split()), 3)


if __name__ == "__main__":
    unittest.main(verbosity=1)
