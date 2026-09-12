"""Redis-backed event queue (scale rewrite Phase 2, 2026-09-13).

A sorted-set DELAY queue plus an atomic Lua CLAIM, so any worker pulls the
oldest DUE events continuously -- draining no longer bound to a realm shard nor
gated by the tick cycle. Redis is single-threaded, so the claim script
(ZRANGEBYSCORE due -> ZREM -> return) is atomic by construction: no two workers
ever get the same event, without SKIP LOCKED, leases, or consumer groups.

Postgres stays the DURABLE source of truth: every event is still written to the
events table, and this queue is REBUILT from PG's undone events on startup (or a
Redis flush). Losing Redis therefore loses no game-state -- it self-heals. That
matches how this Redis is run (best-effort, no strong persistence).

Per-agent serialization: the claim pulls whole SUBJECTS (all of one agent's due
members together, oldest-subject-first), so one agent's turn goes to one worker,
in due order -- the same guarantee the old per-realm drain gave.
"""
from __future__ import annotations

import json
import os

SCHED_KEY = os.getenv("GENOME_REDIS_SCHED", "genome:sched")

# Atomic claim: gather the oldest DUE members, restricted to the SUBJECTS of the
# very oldest few, remove them, and return them. Single Lua = single atomic step
# on Redis's one thread, so competing workers never collide.
#   KEYS[1] = sorted set   ARGV[1] = now (epoch)   ARGV[2] = max subjects
_CLAIM_LUA = """
local due = redis.call('ZRANGEBYSCORE', KEYS[1], '-inf', ARGV[1], 'WITHSCORES')
if #due == 0 then return {} end
local want = tonumber(ARGV[2])
local subjects, seen, out = {}, {}, {}
-- first pass: pick up to `want` distinct subjects from the oldest due members
for i = 1, #due, 2 do
  local m = due[i]
  local ok, obj = pcall(cjson.decode, m)
  local subj = ok and obj['subject'] or m
  if not seen[subj] then
    if #subjects >= want then break end
    seen[subj] = true
    subjects[#subjects + 1] = subj
  end
end
-- second pass: claim EVERY due member of those subjects (whole-agent turn)
for i = 1, #due, 2 do
  local m = due[i]
  local ok, obj = pcall(cjson.decode, m)
  local subj = ok and obj['subject'] or m
  if seen[subj] then
    redis.call('ZREM', KEYS[1], m)
    out[#out + 1] = m
  end
end
return out
"""


class RedisQueue:
    def __init__(self) -> None:
        self._r = None
        self._claim = None

    async def connect(self) -> bool:
        """Best-effort connect. Returns False (and stays disabled) if Redis is
        unreachable -- the caller falls back to the Postgres claim path."""
        try:
            import redis.asyncio as aioredis
        except Exception:
            return False
        host = os.getenv("REDIS_HOST", "redis-master")
        port = int(os.getenv("REDIS_PORT", "6379"))
        password = os.getenv("REDIS_PASSWORD") or None
        try:
            self._r = aioredis.Redis(
                host=host, port=port, password=password, db=0,
                socket_timeout=2.0, socket_connect_timeout=2.0,
                health_check_interval=30, decode_responses=True)
            await self._r.ping()
            self._claim = self._r.register_script(_CLAIM_LUA)
            return True
        except Exception:
            self._r = None
            return False

    @property
    def ready(self) -> bool:
        return self._r is not None

    @staticmethod
    def member(realm: str, subject: str, ev_payload: dict) -> str:
        """Queue member: realm + subject (top-level, for the Lua subject pass) +
        the FULL event payload the consumer feeds straight to drain_one."""
        return json.dumps({"realm": realm, "subject": subject or "",
                           "ev": ev_payload})

    async def schedule(self, realm: str, subject: str, due_epoch: float,
                       ev_payload: dict) -> None:
        """Mirror a scheduled event into the delay queue (write-through). The
        member carries all the consumer needs, so draining reads no PG row."""
        if not self._r:
            return
        try:
            await self._r.zadd(SCHED_KEY,
                               {self.member(realm, subject, ev_payload):
                                float(due_epoch)})
        except Exception:
            pass                       # PG is the source of truth; queue is a cache

    async def claim(self, now_epoch: float, max_subjects: int = 64) -> list[dict]:
        """Atomically claim (and remove) the oldest due events, whole-subject.
        Returns decoded event dicts ({realm,key,subject,kind,due_at,payload})."""
        if not self._claim:
            return []
        try:
            raw = await self._claim(keys=[SCHED_KEY],
                                    args=[f"{now_epoch:.3f}", int(max_subjects)])
        except Exception:
            return []
        out = []
        for m in raw or []:
            try:
                out.append(json.loads(m))
            except Exception:
                continue
        return out

    async def depth(self) -> int:
        if not self._r:
            return 0
        try:
            return int(await self._r.zcard(SCHED_KEY))
        except Exception:
            return 0

    async def reseed(self, members: list[tuple[str, float]]) -> int:
        """Rebuild the queue from PG's undone events (startup / Redis loss).
        members: list of (member_json, due_epoch). Idempotent -- ZADD upserts."""
        if not self._r or not members:
            return 0
        try:
            await self._r.zadd(SCHED_KEY, {m: s for m, s in members})
            return len(members)
        except Exception:
            return 0

    async def close(self) -> None:
        if self._r:
            try:
                await self._r.aclose()
            except Exception:
                pass


# --- module singleton: every genome service inits this once at startup, so
# store.schedule() mirrors write-through without threading a handle per store.
_Q: "RedisQueue | None" = None


async def init() -> bool:
    """Connect the process-wide queue (call once per service at startup, only
    when GENOME_QUEUE=redis). Returns True if Redis is reachable."""
    global _Q
    q = RedisQueue()
    if await q.connect():
        _Q = q
        return True
    _Q = None
    return False


def queue() -> "RedisQueue | None":
    """The connected queue, or None (Redis mode off / unreachable)."""
    return _Q if (_Q is not None and _Q.ready) else None
