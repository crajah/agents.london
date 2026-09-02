"""Cost regression — execution-spec Rule 8.3: an agentic loop must not
silently multiply spend. Every decision costs EXACTLY ONE router call; a
change that makes a decider retry, chain or reflect fails here, loudly."""
import json
import pathlib
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from genome_core import decider, engine
from genome_core.genotype import RANGES

G = {k: 5000.0 for k in RANGES}


def _response(content):
    class R:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, *a):
            return json.dumps({
                "choices": [{"message": {"content": content}}],
                "usage": {"total_tokens": 10}}).encode()
    r = R()
    # json.load(r) reads via r.read()
    return r


class TestOneCallPerDecision(unittest.TestCase):
    def _run(self, fn, *args, content='{"choice": "wait"}', **kw):
        calls = []

        def fake_urlopen(req, timeout=None):
            calls.append(req)
            return _response(content)

        with mock.patch("urllib.request.urlopen", fake_urlopen):
            fn(*args, **kw)
        return len(calls)

    def test_llm_decider_costs_exactly_one_call(self):
        req = engine.DecisionRequest("a1", "at_large", ("wait", "mine_here"),
                                     {"cargo_total": 0.0, "reachable": [],
                                      "at_pile": None})
        n = self._run(decider.llm_decider, req, G)
        self.assertEqual(n, 1)

    def test_garbage_reply_still_costs_one_call(self):
        # the fallback is non-strategic AND free: no retry, no second call
        req = engine.DecisionRequest("a1", "at_large", ("wait",),
                                     {"cargo_total": 0.0, "reachable": [],
                                      "at_pile": None})
        n = self._run(decider.llm_decider, req, G,
                      content="I simply cannot decide today.")
        self.assertEqual(n, 1)

    def test_negotiation_turn_costs_exactly_one_call(self):
        req = engine.DecisionRequest(
            "a1", "negotiate", tuple(
                __import__("genome_core.negotiation",
                           fromlist=["ACTIONS"]).ACTIONS),
            {"neg_key": "n1", "turn": 1, "max_turns": 6,
             "last_offer": None, "my_cargo": {}, "cargo_total": 0.0,
             "at_pile": None, "reachable": []})
        n = self._run(decider.negotiate_decider, req, G,
                      content='{"choice": "walk_away"}')
        self.assertEqual(n, 1)

    def test_market_turn_costs_exactly_one_call(self):
        req = engine.DecisionRequest(
            "a1", "market", ("list", "fill", "collect", "withdraw", "leave"),
            {"board": [], "my_cargo": {}, "cargo_total": 0.0,
             "at_pile": None, "reachable": []})
        n = self._run(decider.market_decider, req, G,
                      content='{"choice": "leave"}')
        self.assertEqual(n, 1)


if __name__ == "__main__":
    unittest.main()
