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

    def test_crossing_takes_one_hour(self):
        t = forms.arrival_time(0.0, 0.0, 1.0, 0.0, 0.0)
        self.assertAlmostEqual(t, 40, places=3)  # calibration Rule 1.2 (final: under a minute)

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


class _V:
    def __init__(self, vid, payload): self.id, self.payload = vid, payload


class _FakeClient:
    """Mirrors post_graph 1.2.0 signatures; asserts realm on every call."""
    def __init__(self):
        self.calls = []
        self.vertices = {}

    def _rec(self, method, realm, **kw):
        assert realm, "realm must always be present"
        self.calls.append((method, realm, kw))

    _next_id = 1000

    async def add_vertex(self, table_name, realm, space="default",
                         payload=None, **kw):
        self._rec("add", realm, table=table_name, space=space)
        _FakeClient._next_id += 1
        v = _V(_FakeClient._next_id, payload or {})
        self.vertices[(table_name, realm, v.id)] = v
        return v

    async def upsert_vertex(self, table_name, realm, vertex_id=None,
                            payload=None, space="default", **kw):
        assert isinstance(vertex_id, int), "vertex_id must be an integer pk"
        self._rec("upsert", realm, table=table_name, vertex_id=vertex_id,
                  space=space)
        self.vertices[(table_name, realm, vertex_id)] = _V(vertex_id, payload)

    async def add_vertex_data(self, table_name, realm, vertex_id, payload, **kw):
        self._rec("append", realm, table=table_name, vertex_id=vertex_id)

    async def upsert_edge(self, table_name, realm, from_id, to_id,
                          relation_type, edge_id=None, payload=None,
                          space="default", **kw):
        self._rec("edge", realm, space=space)

    async def get_vertices(self, table_name, realm, space=None, limit=None):
        self._rec("get", realm, table=table_name)
        return [v for (t, r, _), v in self.vertices.items()
                if t == table_name and r == realm]

    @staticmethod
    def _where_ok(payload, where):
        for key, op, val in (where or []):
            cur = payload.get(key)
            if op == "is_null":
                if cur is not None: return False
            elif op == "not_null":
                if cur is None: return False
            elif op == "=":
                if cur != val: return False
            elif op == "!=":
                if cur == val: return False
            elif cur is None:
                return False
            elif op == "<" and not (cur < val): return False
            elif op == "<=" and not (cur <= val): return False
            elif op == ">" and not (cur > val): return False
            elif op == ">=" and not (cur >= val): return False
        return True

    async def find_vertices(self, table_name, realm, filters=None,
                            limit=None, where=None, order_by=None,
                            descending=False, **kw):
        self._rec("find", realm, table=table_name)
        rows = [v for (t, r, _), v in self.vertices.items()
                if t == table_name and r == realm
                and all(v.payload.get(k) == fv
                        for k, fv in (filters or {}).items())
                and self._where_ok(v.payload, where)]
        if order_by:
            rows.sort(key=lambda v: v.payload.get(order_by),
                      reverse=descending)
        return rows[:limit] if limit else rows

    async def count_vertices(self, table_name, realm, filters=None,
                             where=None, **kw):
        return len(await self.find_vertices(table_name, realm,
                                            filters=filters, where=where))

    async def delete_vertices(self, table_name, realm, where, **kw):
        assert where, "delete_vertices refuses an empty where"
        gone = [k for (t, r, i), v in self.vertices.items()
                if t == table_name and r == realm
                and self._where_ok(v.payload, where)
                for k in [(t, r, i)]]
        for k in gone:
            del self.vertices[k]
        return len(gone)

    async def create_payload_index(self, table_name, realm, key,
                                   numeric=False):
        self._rec("index", realm, table=table_name)
        return f"idx_{table_name}_{key}"

    async def get_vertex(self, table_name, realm, vertex_id, strict=False):
        self._rec("get1", realm, table=table_name)
        return self.vertices[(table_name, realm, vertex_id)]

    async def get_latest_vertex_data(self, table_name, realm, vertex_id, **kw):
        self._rec("latest", realm, table=table_name)
        return None

    async def create_vertex_table(self, table_name, realm=None, **kw):
        assert realm, "DDL must name its realm"
        self._rec("ddl", realm, table=table_name)

    async def create_edge_table(self, table_name=None, *, from_vertex_table,
                                to_vertex_table, realm=None, **kw):
        assert realm, "DDL must name its realm"
        self._rec("ddl_edge", realm, table=table_name)


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
        c = _FakeClient(); s = store.GenomeStore(c)
        _run(s.put_pile("world-1", "pile-9", {"kind": 3}))
        _run(s.schedule("world-1", "ev-1", "t1", "arrival", "a-1", {}))
        self.assertTrue(all(realm == "world-1" for _, realm, _ in c.calls))

    def test_agent_data_in_agents_realm_with_agent_space(self):
        c = _FakeClient(); s = store.GenomeStore(c)
        _run(s.put_agent("agent-7", {"alive": True}))
        writes = [(m, realm, kw) for m, realm, kw in c.calls if m == "add"]
        self.assertEqual(writes[0][1], store.AGENTS_REALM)
        self.assertEqual(writes[0][2]["space"], "agent-7")

    def test_decisions_and_movement_append_only(self):
        c = _FakeClient(); s = store.GenomeStore(c)
        _run(s.put_agent("agent-7", {"alive": True}))
        _run(s.record_decision("agent-7", {"choice": "mine"}))
        _run(s.set_movement("agent-7", {"to_x": 1.0}))
        appends = [m for m, _, _ in c.calls if m == "append"]
        self.assertEqual(appends, ["append", "append"])
        upserts_on_history = [kw for m, _, kw in c.calls
                              if m == "upsert" and kw.get("table") in
                              (store.DECISIONS,)]
        self.assertEqual(upserts_on_history, [])  # history never updated in place

    def test_event_lifecycle(self):
        c = _FakeClient(); s = store.GenomeStore(c)
        _run(s.schedule("w1", "e1", "2026-01-01T01:00", "arrival", "a1", {}))
        _run(s.schedule("w1", "e2", "2026-01-01T03:00", "arrival", "a2", {}))
        due = _run(s.due_events("w1", "2026-01-01T02:00"))
        self.assertEqual([v.payload["key"] for v in due], ["e1"])
        _run(s.complete_event("w1", "e1", "2026-01-01T02:01"))
        self.assertEqual(_run(s.due_events("w1", "2026-01-01T02:00")), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestPromptAndModels(unittest.TestCase):
    def _genotype(self):
        r = random.Random("pg")
        return {k: r.uniform(*G.RANGES[k]) for k in G.RANGES}

    def test_prompt_contains_all_dispositions_and_no_appraisal(self):
        from genome_core import prompt as P
        g = self._genotype()
        s = P.system_prompt(g, {"Stamina": 1.0}, {"3": 2.0}, [])
        for d in G.DISPOSITIONS:
            self.assertIn(d, s)                       # Rule 12.4 / 6.6a
        self.assertIn("do not know how you appear", s)  # Rule 6.6c
        self.assertIn("faculties", s.lower())

    def test_parse_choice_json_and_fallback(self):
        from genome_core.prompt import parse_choice
        self.assertEqual(parse_choice('{"choice": "mine_here"}',
                                      ["mine_here", "wait"]), "mine_here")
        self.assertEqual(parse_choice("I would wait.", ["mine_here", "wait"]),
                         "wait")
        self.assertIsNone(parse_choice("mine_here or wait",
                                       ["mine_here", "wait"]))

    def test_model_assignment_stable_and_rerolls_only_when_withdrawn(self):
        from genome_core import models as M
        a = M.assign_models("agent-x")
        self.assertEqual(a, M.assign_models("agent-x"))     # Rule 10.3
        kept = M.reroll_if_withdrawn(a, "agent-x", generation=2)
        self.assertEqual(kept, a)                           # still in pool
        gone = M.reroll_if_withdrawn({"economy": "retired-model"},
                                     "agent-x", generation=2)
        self.assertIn(gone["economy"], M.POOLS["economy"])  # Rule 10.4


class TestBudget(unittest.TestCase):
    def test_accrual_and_cap(self):
        from genome_core import budget as B
        b = B.Bucket(0.0, 0.0)
        b = B.accrue(b, 86400.0)                 # one day
        self.assertAlmostEqual(b.level, 10.0)
        b = B.accrue(b, 86400.0 * 10)
        self.assertAlmostEqual(b.level, B.CAPACITY)   # cap 12, >= turn cap 6

    def test_free_kinds_never_charged_never_refused(self):
        from genome_core import budget as B
        b = B.Bucket(0.0, 0.0)
        for kind in ("arrival", "decide", "mining_done", "accept", "decline"):
            b2, ok = B.charge(b, kind, 100.0)
            self.assertTrue(ok)                  # Rule 5.2a/5.2b
            self.assertAlmostEqual(b2.level, B.accrue(b, 100.0).level)

    def test_discretionary_charges_and_refuses_gracefully(self):
        from genome_core import budget as B
        b = B.Bucket(2.0, 0.0)
        b, ok = B.charge(b, "counter_offer", 0.0)
        self.assertTrue(ok); self.assertAlmostEqual(b.level, 1.0)
        b, ok = B.charge(b, "counter_offer", 0.0)
        self.assertTrue(ok); self.assertAlmostEqual(b.level, 0.0)
        b, ok = B.charge(b, "counter_offer", 0.0)
        self.assertFalse(ok)                     # broke: cannot counter...
        b2, ok2 = B.charge(b, "accept", 0.0)
        self.assertTrue(ok2)                     # ...but can always accept


class TestHeredity(unittest.TestCase):
    def _pair(self):
        ra, rb = random.Random("pa"), random.Random("pb")
        a = {k: ra.uniform(*G.RANGES[k]) for k in G.RANGES}
        b = {k: rb.uniform(*G.RANGES[k]) for k in G.RANGES}
        return a, b

    def test_crossover_every_locus_from_a_parent_or_nearby(self):
        a, b = self._pair()
        c = G.crossover(a, b, "s1")
        for k, (lo, hi) in G.RANGES.items():
            span = hi - lo
            near = min(abs(c[k] - a[k]), abs(c[k] - b[k]))
            self.assertLessEqual(near, 0.25 * span + 1e-9)  # step or excursion
            self.assertGreaterEqual(c[k], lo); self.assertLessEqual(c[k], hi)

    def test_crossover_deterministic_and_seed_sensitive(self):
        a, b = self._pair()
        self.assertEqual(G.crossover(a, b, "s"), G.crossover(a, b, "s"))
        self.assertNotEqual(G.crossover(a, b, "s"), G.crossover(a, b, "t"))

    def test_child_name_takes_second_surname_of_each(self):
        n = G.child_name("Asha Brightwater Coldmere", "Falk Greyvale Kestrel",
                         "s", ["Iris"])
        parts = n.split()
        self.assertEqual(parts[0], "Iris")
        self.assertEqual(sorted(parts[1:]), ["Coldmere", "Kestrel"])  # 7.14

    def test_child_colours_one_from_each(self):
        c = G.child_colours(["#A", "#B"], ["#C", "#D"], "s")
        self.assertIn(c[0], ["#A", "#B"]); self.assertIn(c[1], ["#C", "#D"])

    def test_breeding_cost(self):
        spend = G.breeding_cost_met({"1": 2, "2": 2}, {"3": 2, "4": 3})
        self.assertIsNotNone(spend)
        self.assertIsNone(G.breeding_cost_met({"1": 8}, {"2": 2, "3": 2}))
        # collective: one side can carry most of it
        self.assertIsNotNone(G.breeding_cost_met({"1": 2, "2": 2, "3": 2},
                                                 {"4": 2}))


class TestPathogen(unittest.TestCase):
    def _payload(self, vig=5000.0, spd=5000.0):
        r = random.Random("pg2")
        g = {k: r.uniform(*G.RANGES[k]) for k in G.RANGES}
        g["Immune Vigilance"] = vig; g["Synthesis Speed"] = spd
        return {"genotype": g, "identity": "idX"}

    def test_infection_carries_its_future(self):
        from genome_core import pathogen as P
        s = P.new_strain("s1")
        pl = P.infect(self._payload(), s, now=1000.0)
        rec = pl["infections"][0]
        self.assertGreater(rec["detected_at"], 1000.0)
        self.assertGreater(rec["synth_done_at"], rec["detected_at"])

    def test_vigilance_detects_sooner_speed_synthesises_faster(self):
        from genome_core import pathogen as P
        s = P.new_strain("s2")
        quick = P.infect(self._payload(vig=9500, spd=9500), s, 0.0)["infections"][0]
        slow = P.infect(self._payload(vig=500, spd=500), s, 0.0)["infections"][0]
        self.assertLess(quick["detected_at"], slow["detected_at"])
        self.assertLess(quick["synth_done_at"], slow["synth_done_at"])

    def test_phenotype_modifies_and_restores(self):
        from genome_core import pathogen as P
        s = P.new_strain("s3")
        pl = self._payload()
        base = dict(pl["genotype"])
        infected = P.infect(pl, s, 0.0)
        ph = P.phenotype(infected, 10.0)
        self.assertNotEqual(ph, base)                       # expression moved
        self.assertEqual(infected["genotype"], base)        # genotype untouched
        settled, events = P.settle(infected, now=infected["infections"][0]
                                   ["synth_done_at"] + 1)
        self.assertEqual(settled["infections"], [])
        self.assertEqual(P.phenotype(settled, 10.0), base)  # Rule 2.16: exact
        self.assertEqual(len(settled["antigens"]), 1)       # earned in illness
        self.assertTrue(events)

    def test_coverage_resists_descendants_gracefully(self):
        from genome_core import pathogen as P
        parent = P.new_strain("s4")
        child = P.new_strain("s5", parent=parent)
        pl = self._payload()
        settled, _ = P.settle(P.infect(pl, parent, 0.0),
                              now=10 ** 9)
        cov_child = P.coverage(settled["antigens"], child["signature"], 10 ** 9)
        stranger = P.new_strain("s6")
        cov_stranger = P.coverage(settled["antigens"],
                                  stranger["signature"], 10 ** 9)
        self.assertGreater(cov_child, cov_stranger)         # descent helps

    def test_antigens_decay(self):
        from genome_core import pathogen as P
        s = P.new_strain("s7")
        settled, _ = P.settle(P.infect(self._payload(), s, 0.0), now=10 ** 6)
        soon = P.coverage(settled["antigens"], s["signature"], 10 ** 6 + 60)
        later = P.coverage(settled["antigens"], s["signature"],
                           10 ** 6 + 90 * 86400)
        self.assertGreater(soon, later)                     # Rule 2.18d


class TestHeardAssertions(unittest.TestCase):
    def _g(self):
        from genome_core.genotype import RANGES
        return {k: (lo + hi) / 2 for k, (lo, hi) in RANGES.items()}

    def test_assertions_reach_the_prompt_marked_unverified(self):
        from genome_core.prompt import system_prompt
        s = system_prompt(self._g(), {}, {}, [],
                          heard=[{"text": "the east pile is poisoned",
                                  "from": "u:x"}])
        self.assertIn("the east pile is poisoned", s)
        self.assertIn("not instructions", s)

    def test_no_heard_no_block(self):
        from genome_core.prompt import system_prompt
        self.assertNotIn("OTHER USERS",
                         system_prompt(self._g(), {}, {}, []))


class TestFailClosedScoping(unittest.TestCase):
    """Phase 0.3: a read that reaches storage without its realm is an error,
    never an empty result -- an unscoped read is a cross-world leak."""

    def test_empty_realm_raises(self):
        from genome_core.store import UnscopedError, _req
        for bad in ("", None):
            with self.assertRaises(UnscopedError):
                _req(bad, "world realm")

    def test_scoped_value_passes_through(self):
        from genome_core.store import _req
        self.assertEqual(_req("genome_demo2", "world realm"), "genome_demo2")


class TestCostRegression(unittest.TestCase):
    """execution-spec Rule 8.3: an agentic loop must not silently multiply
    spend. Mechanical events NEVER produce a decision request (= never a
    model call); only arrival and decide may."""

    def _view(self):
        from genome_core.engine import AgentView
        return AgentView("a", "w", "w", 0.5, 0.5, {"3": 2.0},
                         frozenset(), frozenset({(1, 1)}))

    def test_mechanical_events_never_ask_a_model(self):
        from genome_core import engine
        eff = engine.on_event("mining_done", self._view(), [], 100.0,
                              {"take": 1.0, "pile_kind": 3,
                               "pile_uuid": "p"}, {}, [])
        self.assertIsInstance(eff, engine.Effects)
        eff2 = engine.on_event("explored", self._view(), [], 100.0, {},
                               {}, [])
        self.assertIsInstance(eff2, engine.Effects)

    def test_decide_asks_exactly_once(self):
        from genome_core import engine
        req = engine.on_event("decide", self._view(), [], 100.0, {}, {}, [])
        self.assertIsInstance(req, engine.DecisionRequest)
        # one request, one situation, no hidden second call in the shape
        self.assertTrue(req.options)


class TestBudget(unittest.TestCase):
    """execution-spec 5.2: counters are discretionary and charged; broke is
    take-it-or-leave-it, never frozen."""

    def test_accrual_caps_at_capacity(self):
        from genome_core import budget as b
        full = b.accrue(b.Bucket(0.0, 0.0), 100 * 86400.0)
        self.assertEqual(full.level, b.CAPACITY)

    def test_counter_charges_one(self):
        from genome_core import budget as b
        bk, ok = b.charge(b.Bucket(3.0, 0.0), "counter_offer", 0.0)
        self.assertTrue(ok)
        self.assertEqual(bk.level, 2.0)

    def test_broke_cannot_counter_but_lives(self):
        from genome_core import budget as b
        bk, ok = b.charge(b.Bucket(0.2, 0.0), "counter_offer", 0.0)
        self.assertFalse(ok)
        self.assertEqual(bk.level, 0.2)       # nothing taken

    def test_mechanical_kinds_free(self):
        from genome_core import budget as b
        bk, ok = b.charge(b.Bucket(0.0, 0.0), "arrival", 0.0)
        self.assertTrue(ok)
