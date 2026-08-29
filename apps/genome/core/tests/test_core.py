"""Phase 0/1 core tests. Property tests for the closed forms (a stored value
that could be derived is a defect), the budget invariant, the fail-closed
realm guard, and the calibrated life-history curves."""
import math
import pathlib
import random
import sys
import unittest

# Locate genome_core relative to THIS file, so the suite runs from any cwd.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from genome_core import forms, genotype as G, opinion, store


class TestForms(unittest.TestCase):
    def test_position_endpoints_and_monotone(self):
        m = forms.Movement(0.1, 0.1, 0.9, 0.5, 1000.0,
                           forms.arrival_time(0.1, 0.1, 0.9, 0.5, 1000.0))
        self.assertEqual(forms.position(m, 0), (0.1, 0.1))
        self.assertEqual(forms.position(m, m.arrives_at + 5), (0.9, 0.5))
        # distance from start is monotone in t (property, 200 samples)
        last = -1.0
        for i in range(200):
            t = 1000.0 + (m.arrives_at - 1000.0) * i / 199
            x, y = forms.position(m, t)
            d = math.dist((0.1, 0.1), (x, y))
            self.assertGreaterEqual(d, last - 1e-12)
            last = d

    def test_crossing_takes_six_hours(self):
        t = forms.arrival_time(0.0, 0.0, 1.0, 0.0, 0.0)
        self.assertAlmostEqual(t, 6 * 3600, places=3)  # calibration Rule 1.2

    def test_pile_regen_clamps_and_halts(self):
        p = forms.PileState(qty_at=10.0, measured_at=0.0, rate=0.01, cap=40.0)
        self.assertAlmostEqual(forms.pile_quantity(p, 1000.0), 20.0)
        self.assertAlmostEqual(forms.pile_quantity(p, 10_000.0), 40.0)  # cap
        self.assertAlmostEqual(forms.pile_quantity(p, 1000.0, True), 10.0)  # 4.14

    def test_mine_is_the_only_write(self):
        p = forms.PileState(10.0, 0.0, 0.01, 40.0)
        p2, taken = forms.mine(p, 1000.0, want=7.5)
        self.assertAlmostEqual(taken, 7.5)
        self.assertAlmostEqual(p2.qty_at, 12.5)
        self.assertEqual(p2.measured_at, 1000.0)
        _, over = forms.mine(p2, 1000.0, want=99.0)
        self.assertAlmostEqual(over, 12.5)  # cannot take what is not there


class TestGenotype(unittest.TestCase):
    def _random_genotype(self, seed):
        r = random.Random(seed)
        return {k: r.uniform(*G.RANGES[k]) for k in G.RANGES}

    def test_budget_invariant(self):
        # Σ expressed over budgeted loci == B, for any genotype (Rule 3.22)
        for seed in range(25):
            g = self._random_genotype(seed)
            e = G.expressed(g)
            b = len(G.BUDGETED) / 2.0
            self.assertAlmostEqual(sum(e[k] for k in G.BUDGETED), b, places=9)

    def test_norm_never_zero(self):
        for k, (lo, _hi) in G.RANGES.items():
            self.assertGreater(G.norm(k, lo), 0.0)  # Rule 2.2

    def test_dilution_is_real(self):
        # adding a budgeted locus lowers everyone's shares — the migration
        # hazard BUILD.md names; asserted so it is never a surprise
        g = self._random_genotype(1)
        e1 = G.expressed(g)["Intelligence"]
        g2 = dict(g); g2["NewLocus"] = 5000.0
        G.RANGES["NewLocus"] = (0, 10000)
        try:
            e2 = G.expressed(g2)["Intelligence"]
        finally:
            del G.RANGES["NewLocus"]
        self.assertLess(abs(e2 - e1 * (len(G.BUDGETED)/2 + 0.5) /
                            (len(G.BUDGETED)/2)) / e1, 0.35)

    def test_attrition_reaches_zero(self):
        # Rule 3.8d needs zero reachable; calibration 3.0b: ~15 wins mid-range
        self.assertGreater(G.stamina_max(1.0, 5, 5000, 14, 5000), 0.0)
        self.assertEqual(G.stamina_max(1.0, 5, 5000, 30, 5000), 0.0)

    def test_maturation_tradeoff(self):
        young_mana = G.mana_max(1.0, 5, 8000)
        old_mana = G.mana_max(1.0, 85, 8000)
        self.assertGreater(young_mana, old_mana)  # Rule 3.8a
        self.assertGreaterEqual(old_mana, 0.1)    # floor


class TestOpinion(unittest.TestCase):
    def test_surprise_asymmetry(self):
        # Rule 6.10a: a lie from the trusted moves more than from the suspected
        trusted = opinion.Opinion(9000.0, 10.0)
        suspected = opinion.Opinion(1500.0, 10.0)
        d_trust = trusted.estimate - opinion.update_event(trusted, False, 5000, 0.1).estimate
        d_susp = suspected.estimate - opinion.update_event(suspected, False, 5000, 0.1).estimate
        self.assertGreater(d_trust, d_susp * 2)

    def test_theta_is_the_opponent(self):
        # honesty when the lie was worth a lot is strong evidence
        op = opinion.Opinion(5000.0, 5.0)
        cheap = opinion.update_event(op, True, theta=1000, k=0.1).estimate - 5000
        costly = opinion.update_event(op, True, theta=9000, k=0.1).estimate - 5000
        self.assertGreater(costly, cheap)

    def test_decay_toward_neutral(self):
        op = opinion.Opinion(9000.0, 10.0)
        d = opinion.decay_toward(op, 5000.0, rate=0.1, dt=30.0)
        self.assertLess(d.estimate, 9000.0)
        self.assertGreater(d.estimate, 5000.0)


class _FakeClient:
    """Captures post-graph calls: every call must carry a non-empty realm."""
    def __init__(self):
        self.calls = []

    def _record(self, method, kw):
        assert kw.get("realm"), "realm must always be present"
        self.calls.append((method, kw))

    async def upsert_vertex(self, table, **kw): self._record("upsert", kw)
    async def add_vertex_data(self, table, **kw): self._record("append", kw)
    async def add_edge(self, table, **kw): self._record("edge", kw)
    async def get_vertices(self, table, **kw): self._record("get", kw); return []
    async def create_vertex_table(self, *a, **kw):
        assert kw.get("realm"), "DDL must name its realm"
    async def create_edge_table(self, *a, **kw): pass


def _run(coro):
    import asyncio
    return asyncio.run(coro)


class TestStoreGuard(unittest.TestCase):
    def test_missing_scope_fails_closed(self):
        s = store.GenomeStore(_FakeClient())
        for call in (s.agents_in(None), s.agents_in(""),
                     s.due_events(None, "t"), s.put_agent(None, {}),
                     s.set_presence("w1", None, True),
                     s.record_decision("", {})):
            with self.assertRaises(store.UnscopedError):
                _run(call)
        with self.assertRaises(store.UnscopedError):
            _run(store.ensure_world_realm(_FakeClient(), None))

    def test_world_realm_is_one_to_one(self):
        # a world's data lives in a realm named by the world itself
        c = _FakeClient(); s = store.GenomeStore(c)
        _run(s.put_pile("world-1", "pile-9", {"kind": 3}))
        _run(s.schedule("world-1", "ev-1", "t1", "arrival", "a-1", {}))
        self.assertTrue(all(kw["realm"] == "world-1" for _, kw in c.calls))

    def test_agent_data_lives_in_agents_realm_with_agent_space(self):
        c = _FakeClient(); s = store.GenomeStore(c)
        _run(s.put_agent("agent-7", {"alive": True}))
        _run(s.record_decision("agent-7", {"choice": "mine"}))
        for _, kw in c.calls:
            self.assertEqual(kw["realm"], store.AGENTS_REALM)
            self.assertEqual(kw["space"], "agent-7")

    def test_decisions_and_movement_append_only(self):
        c = _FakeClient(); s = store.GenomeStore(c)
        _run(s.record_decision("agent-7", {"choice": "mine"}))
        _run(s.set_movement("agent-7", {"to_x": 1.0}))
        self.assertEqual([m for m, _ in c.calls], ["append", "append"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
