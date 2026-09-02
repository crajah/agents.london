"""Portage — construction-spec Rules 3.10–3.13. The lift needs the full crew
of distinct users; pledges expire; set-down releases the carriers and moves
the thing; a crossing re-raises it aloft in the destination realm."""
import asyncio
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from genome_core import construction as C


class FakeRow:
    def __init__(self, payload):
        self.id = 1
        self.payload = payload


class FakeClient:
    def __init__(self, site):
        self.rows = {("w", site["key"]): dict(site)}
        self.added = []

    async def find_vertices(self, table, realm=None, filters=None, **k):
        pl = self.rows.get((realm, (filters or {}).get("key")))
        return [FakeRow(pl)] if pl else []

    async def upsert_vertex(self, table, realm=None, vertex_id=None,
                            payload=None, **k):
        self.rows[(realm, payload["key"])] = dict(payload)

    async def add_vertex(self, table, realm=None, payload=None, **k):
        self.added.append((realm, dict(payload)))
        self.rows[(realm, payload["key"])] = dict(payload)


def forge(**over):
    return {"key": "s1", "name": "forge", "complete": True, "x": 0.5,
            "y": 0.5, "required_users": 3, "porters": {}, **over}


class TestTakeUp(unittest.TestCase):
    def test_lift_waits_for_distinct_users(self):
        fc = FakeClient(forge())
        r1 = asyncio.run(C.take_up(fc, "w", "s1", "userA", "a1", 100.0))
        self.assertFalse(r1["carried"])
        # a second agent of the SAME user adds nothing (Rule 3.10 mirrors 3.4)
        r2 = asyncio.run(C.take_up(fc, "w", "s1", "userA", "a2", 101.0))
        self.assertFalse(r2["carried"])
        asyncio.run(C.take_up(fc, "w", "s1", "userB", "b1", 102.0))
        r4 = asyncio.run(C.take_up(fc, "w", "s1", "userC", "c1", 103.0))
        self.assertTrue(r4["carried"])

    def test_stale_pledges_expire(self):
        fc = FakeClient(forge())
        asyncio.run(C.take_up(fc, "w", "s1", "userA", "a1", 0.0))
        asyncio.run(C.take_up(fc, "w", "s1", "userB", "b1", 10.0))
        # userA's pledge is an hour dead by the time userC arrives
        r = asyncio.run(C.take_up(fc, "w", "s1", "userC", "c1", 5000.0))
        self.assertFalse(r["carried"])

    def test_incomplete_or_manifested_never_lifts(self):
        for bad in ({"complete": False}, {"manifested": True},
                    {"destroyed": True}, {"name": "cache"}):
            fc = FakeClient(forge(**bad))
            r = asyncio.run(C.take_up(fc, "w", "s1", "u", "a1", 0.0))
            self.assertIn("error", r)


class TestSetDownAndCross(unittest.TestCase):
    def test_set_down_moves_and_releases(self):
        fc = FakeClient(forge(carried=True,
                              porters={"a1": {"user": "uA", "at": 0.0}}))
        r = asyncio.run(C.set_down(fc, "w", "s1", 0.2, 0.3, "test"))
        self.assertEqual(r["porters"], ["a1"])
        after = fc.rows[("w", "s1")]
        self.assertFalse(after["carried"])
        self.assertEqual((after["x"], after["y"]), (0.2, 0.3))
        self.assertEqual(after["porters"], {})

    def test_cross_retires_origin_and_raises_at_destination(self):
        site = forge(carried=True,
                     porters={"a1": {"user": "uA", "at": 0.0}})
        fc = FakeClient(site)
        asyncio.run(C.portage_cross(fc, "w", "w2", site, [0.7, 0.8]))
        origin = fc.rows[("w", "s1")]
        self.assertTrue(origin["destroyed"])
        self.assertEqual(origin["portaged_to"], "w2")
        dest = fc.rows[("w2", "s1")]
        self.assertTrue(dest["carried"])            # still aloft on arrival
        self.assertEqual((dest["x"], dest["y"]), (0.7, 0.8))
        self.assertNotIn("destroyed", dest)


class TestNeverDismantled(unittest.TestCase):
    def test_rule_3_13_no_dismantle_surface_exists(self):
        # the exploit-closing rule: no function anywhere turns a construction
        # back into resources
        self.assertFalse([n for n in dir(C) if "dismantle" in n.lower()])


if __name__ == "__main__":
    unittest.main()
