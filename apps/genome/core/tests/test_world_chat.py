"""The world's open chat (user directives 2026-09-05/06): the owner asks
the WORLD; present agents compete -- first claim wins; world knowledge
opens only to home-world natives standing at home."""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from genome_core import drain, engine  # noqa: E402


def _view(**kw):
    d = dict(agent_uuid="agent-a", home_realm="w1", realm="w1",
             x=0.5, y=0.5, cargo={}, known_piles=frozenset(),
             explored=frozenset())
    d.update(kw)
    return engine.AgentView(**d)


class ArenaOptions(unittest.TestCase):
    def test_an_open_ask_offers_the_claim(self):
        eff = engine.apply_choice(
            engine.Choice(option="answer_world_ask"), _view(), [], 100.0,
            {}, [], 1.0, {"open_world_ask": {"key": "wc-1", "text": "q?"}})
        self.assertEqual(eff.world_say, ("wc-1", "claim"))

    def test_joining_speaks_into_the_room(self):
        eff = engine.apply_choice(
            engine.Choice(option="join_world_chat"), _view(), [], 100.0,
            {}, [], 1.0, {})
        self.assertEqual(eff.world_say, (None, "join"))


class FakeRow:
    def __init__(self, pk, payload):
        self.id = pk
        self.payload = payload


class FakeClient:
    def __init__(self, rows):
        self.rows = rows
        self.added = []
        self.upserts = []

    async def find_vertices(self, table, realm=None, filters=None,
                            where=None, order_by=None, descending=False,
                            limit=None, space=None):
        if filters and "key" in filters:
            return [r for r in self.rows
                    if r.payload.get("key") == filters["key"]][:1]
        return list(self.rows)[:limit or None]

    async def upsert_vertex(self, table, realm=None, vertex_id=None,
                            space=None, payload=None):
        self.upserts.append(payload)
        for r in self.rows:
            if r.id == vertex_id:
                r.payload = payload

    async def add_vertex(self, table, realm=None, space=None, payload=None):
        self.added.append((table, payload))
        return FakeRow(99, payload)


class FakeStore:
    def __init__(self, client):
        self._c = client


class ClaimRace(unittest.IsolatedAsyncioTestCase):
    async def test_second_claim_is_too_late(self):
        ask = FakeRow(1, {"key": "wc-1", "kind": "ask", "text": "q?",
                          "claimed_by": "agent-first"})
        out = await drain.world_say(
            FakeStore(FakeClient([ask])), "w1", _view(),
            {"name": "A", "capability": {}}, "wc-1", "claim", 100.0)
        self.assertEqual(out, "world_chat:too_late")

    async def test_a_visitor_never_reads_the_worlds_knowledge(self):
        # home_realm w1, standing in w2: the knowledge helper must not run
        called = []
        orig = drain._world_knowledge
        drain._world_knowledge = lambda *a: called.append(a) or "SECRET"
        orig_compose = drain._compose
        async def fake_compose(*a, **k):
            return "an answer"
        drain._compose = fake_compose
        orig_notify = drain.notify.emit_bg
        drain.notify.emit_bg = lambda *a, **k: None
        try:
            ask = FakeRow(1, {"key": "wc-1", "kind": "ask", "text": "q?",
                              "claimed_by": None})
            meta = FakeRow(2, {"key": "w2", "owner_user_id": "u:o"})
            client = FakeClient([ask, meta])
            await drain.world_say(
                FakeStore(client), "w2",
                _view(home_realm="w1", realm="w2"),
                {"name": "Visitor", "capability": {},
                 "home_realm": "w1"}, "wc-1", "claim", 100.0)
        finally:
            drain._world_knowledge = orig
            drain._compose = orig_compose
            drain.notify.emit_bg = orig_notify
        self.assertEqual(called, [])          # the library stayed shut
        kinds = [p.get("kind") for _, p in client.added]
        self.assertIn("answer", kinds)        # it still answered from itself


if __name__ == "__main__":
    unittest.main()
