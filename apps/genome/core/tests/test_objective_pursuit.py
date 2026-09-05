"""User directive 2026-09-05: an owner's instruction is an OBJECTIVE, and
the agent's responsibility is to find the best way -- including asking a
web-search-capable peer and reporting the answer back on the chat."""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from genome_core import drain, engine  # noqa: E402


def _view(**kw):
    defaults = dict(agent_uuid="agent-asker", home_realm="w", realm="w",
                    x=0.5, y=0.5, cargo={}, known_piles=frozenset(),
                    explored=frozenset())
    defaults.update(kw)
    return engine.AgentView(**defaults)


class ToolHolderPreference(unittest.TestCase):
    def _choose(self, ctx):
        choice = engine.Choice(option="request_service")
        eff = engine.apply_choice(choice, _view(), [], 1000.0, {}, [],
                                  1.0, ctx)
        return eff.service

    def test_objective_prefers_the_web_search_holder(self):
        ctx = {"has_objective": True,
               "known_remote_holders": [("agent-chronicler", "Chronicle"),
                                        ("agent-searcher", "Web Search"),
                                        ("agent-appraiser", "Appraisal")]}
        verb, who, skill = self._choose(ctx)
        self.assertEqual((verb, who, skill),
                         ("request", "agent-searcher", "Web Search"))

    def test_without_objective_the_last_met_is_asked(self):
        ctx = {"has_objective": False,
               "known_remote_holders": [("agent-searcher", "Web Search"),
                                        ("agent-appraiser", "Appraisal")]}
        verb, who, skill = self._choose(ctx)
        self.assertEqual(who, "agent-appraiser")

    def test_objective_without_tool_holder_falls_back(self):
        ctx = {"has_objective": True,
               "known_remote_holders": [("agent-appraiser", "Appraisal")]}
        _, who, _ = self._choose(ctx)
        self.assertEqual(who, "agent-appraiser")


class ReplyToOwner(unittest.IsolatedAsyncioTestCase):
    async def test_reply_lands_on_chat_and_retires_the_objective(self):
        chats = []
        notices = []

        class FakeClient:
            async def add_vertex(self, table, realm=None, payload=None, **kw):
                chats.append((table, payload))

        class FakeStore:
            _c = FakeClient()

        orig = drain.notify.emit_bg
        drain.notify.emit_bg = lambda c, uid, cat, kind, msg: \
            notices.append((uid, kind, msg))
        try:
            rq = {"owner_user_id": "u:owner", "name": "Asha Vale",
                  "objectives": ["compare the latest Apple and Google "
                                 "stock prices"]}
            # ROUTER is unreachable in tests: the reply degrades to the raw
            # material -- never to silence
            await drain._reply_to_owner(FakeStore(), "agent-asker", rq,
                                        {"kind": "web"},
                                        "searched: AAPL 234; GOOGL 178",
                                        1000.0)
        finally:
            drain.notify.emit_bg = orig
        self.assertEqual(len(chats), 1)
        table, payload = chats[0]
        self.assertEqual(table, "chats")
        self.assertEqual(payload["kind"], "reply")
        self.assertEqual(payload["from"], "agent-asker")
        self.assertIn("AAPL 234", payload["text"])
        self.assertEqual(rq["objectives"], [])
        self.assertEqual(len(notices), 1)
        self.assertIn("Asha Vale reports", notices[0][2])

    async def test_no_owner_or_no_objective_stays_silent(self):
        class FakeStore:
            class _c:
                @staticmethod
                async def add_vertex(*a, **k):
                    raise AssertionError("must not write")
        await drain._reply_to_owner(FakeStore(), "a", {"objectives": ["x"]},
                                    {"kind": "web"}, "m", 0.0)
        await drain._reply_to_owner(FakeStore(), "a",
                                    {"owner_user_id": "u:x"},
                                    {"kind": "web"}, "m", 0.0)


if __name__ == "__main__":
    unittest.main()
