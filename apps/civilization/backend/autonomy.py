"""The founders that run without being asked.

Four of the roster carry a duty cycle: the Anomaly Detector watches runs
against each agent's own baseline, the Proving Ground evaluates published
agents against what they promised and proposes better versions, the Adversary
attacks conclusions the civilisation has published, and the Quarantine Warden
takes out of circulation what fails. Their prompts describe those duties; this
module is what actually wakes them.

The distinction matters. A prompt that says "you run every fifteen minutes" in
a system where nothing schedules anything is a description of a system that
does not exist — and the agents would still be, in practice, functions someone
calls. So each cycle here does four real things: it gathers evidence from the
records rather than from a description, it asks the founder to judge that
evidence, it applies the decision through the same registry APIs a human would
use, and it writes down what happened so the cycle can be audited afterwards.

Three properties are deliberate:

**Bounded.** Each duty has a per-cycle subject budget from its `Duty`
declaration. A duty that tried to be exhaustive in one pass would starve the
others and spend the project's tokens on completeness nobody asked for.

**Honest about quiet.** A cycle that finds nothing records a quiet cycle. The
failure mode of an autonomous evaluator is manufacturing findings to justify
having run, and it is worse than not running at all — the findings are acted on.

**Reversible.** The only destructive-looking effect is dormancy, which
withdraws an agent from discovery while leaving every record it produced and
every lineage edge below it intact. Nothing here deletes anything.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import deque
from typing import Any, Dict, List, Optional, Tuple

import httpx

try:
    from backend.founders import AUTONOMOUS, founder, founder_prompt
    from backend.env_config import DEFAULT_LLM_MODEL
except ImportError:                       # running from inside backend/
    from founders import AUTONOMOUS, founder, founder_prompt
    from env_config import DEFAULT_LLM_MODEL

logger = logging.getLogger(__name__)

AGENT_REGISTRY_URL = os.getenv("AGENT_REGISTRY_URL", "http://localhost:8001")
LITELLM_URL = os.getenv("LITELLM_URL", os.getenv("OPENAI_API_BASE", "http://localhost:4000/v1"))
API_KEY = os.getenv("OPENAI_API_KEY", "sk-local")

# Off is a legitimate deployment. A CI run or a laptop should not be spending
# tokens on duty cycles nobody is watching.
AUTONOMY_ENABLED = os.getenv("AUTONOMY_ENABLED", "true").strip().lower() in ("1", "true", "yes")

# How often the scheduler wakes to see whose interval has elapsed. Duties
# declare their own intervals; this is only the granularity of the check.
TICK_SECONDS = int(os.getenv("AUTONOMY_TICK_SECONDS", "60"))

# What a duty needs before it is worth running at all.
MIN_RUNS_FOR_EVALUATION = 1


class Cycle:
    """One duty cycle, and what came of it."""

    def __init__(self, org_id: str, project_id: str, founder_id: str):
        self.org_id = org_id
        self.project_id = project_id
        self.founder_id = founder_id
        self.started_at = time.time()
        self.finished_at: Optional[float] = None
        self.quiet = True
        self.subjects = 0
        self.findings: List[Dict[str, Any]] = []
        self.effects: List[Dict[str, Any]] = []
        self.error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "org_id": self.org_id, "project_id": self.project_id,
            "founder_id": self.founder_id,
            "started_at": self.started_at, "finished_at": self.finished_at,
            "duration_secs": (round(self.finished_at - self.started_at, 2)
                              if self.finished_at else None),
            "quiet": self.quiet, "subjects": self.subjects,
            "findings": self.findings, "effects": self.effects,
            "error": self.error,
        }


async def _registry(method: str, path: str, **kwargs) -> Optional[httpx.Response]:
    url = f"{AGENT_REGISTRY_URL.rstrip('/')}{path}"
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            return await client.request(method, url, **kwargs)
    except Exception as e:
        logger.warning("autonomy could not reach the agent registry at %s: %s", url, e)
        return None


async def _ask(founder_id: str, evidence: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Put the evidence to the founder and read its judgement.

    The founder's own system prompt is used — the same text it was registered
    with — so a duty cycle and a direct invocation are the same agent, and an
    improvement to the prompt improves both.
    """
    prompt = founder_prompt(founder_id)
    if not prompt:
        return None
    body = {
        "model": DEFAULT_LLM_MODEL,
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content":
                "This is a duty cycle. Here is the evidence gathered from the "
                "records since your last cycle. Judge only what is here; if it "
                "shows nothing worth acting on, say so with quiet: true.\n\n"
                + json.dumps(evidence, indent=2, default=str)[:24000]
                + "\n\nRespond with your JSON object only."},
        ],
        "max_tokens": 2000,
        "response_format": {"type": "json_object"},
    }
    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            res = await client.post(f"{LITELLM_URL.rstrip('/')}/chat/completions",
                                    headers={"Authorization": f"Bearer {API_KEY}"},
                                    json=body)
        if res.status_code != 200:
            logger.warning("duty cycle for %s: model router returned %s",
                           founder_id, res.status_code)
            return None
        text = res.json()["choices"][0]["message"]["content"]
        return json.loads(text)
    except Exception as e:
        logger.warning("duty cycle for %s could not be judged: %s", founder_id, e)
        return None


# ------------------------------------------------------------------- evidence

async def _gather(founder_id: str, org_id: str, project_id: str,
                  budget: int) -> Tuple[Dict[str, Any], int]:
    """What this duty looks at, read from the records.

    Returns the evidence and how many subjects it covers. Zero subjects means
    the cycle has nothing to judge, and is reported quiet without a model call —
    an empty project should not cost tokens every fifteen minutes.
    """
    runs_res = await _registry("GET", "/runs",
                               params={"org_id": org_id, "project_id": project_id,
                                       "limit": 60})
    runs = runs_res.json().get("runs", []) if runs_res is not None and runs_res.status_code == 200 else []

    agents_res = await _registry("GET", "/agents",
                                 params={"org_id": org_id, "project_id": project_id})
    agents = agents_res.json().get("agents", []) if agents_res is not None and agents_res.status_code == 200 else []

    # Founding agents are excluded from evaluation and quarantine: they are the
    # civilisation's constitution in agent form, and an evaluator that can
    # quarantine the Arbiter can quarantine the thing that would overrule it.
    population = [a for a in agents
                  if a.get("role") != "permanent_prime_scaffolding"][:budget]

    if founder_id == "anomaly-detector":
        if not runs:
            return {}, 0
        return {"window": "runs recorded most recently",
                "runs": [{"run_id": r.get("run_id"), "pipeline_id": r.get("pipeline_id"),
                          "status": r.get("status"), "halt_reason": r.get("halt_reason"),
                          "started_at": r.get("started_at"),
                          "duration_ms": r.get("duration_ms"),
                          "steps": r.get("executed_steps")}
                         for r in runs[:budget * 4]]}, min(len(runs), budget * 4)

    if founder_id == "proving-ground":
        if not population or len(runs) < MIN_RUNS_FOR_EVALUATION:
            return {}, 0
        return {"agents": [{"agent_id": a.get("agent_id"), "version": a.get("version"),
                            "telos": a.get("telos"),
                            "reputation_score": a.get("reputation_score"),
                            "capabilities": a.get("capabilities")}
                           for a in population],
                "runs": [{"run_id": r.get("run_id"), "status": r.get("status"),
                          "halt_reason": r.get("halt_reason"),
                          "pipeline_id": r.get("pipeline_id")} for r in runs[:40]]}, len(population)

    if founder_id == "adversary":
        if not runs:
            return {}, 0
        return {"conclusions": [{"run_id": r.get("run_id"), "status": r.get("status"),
                                 "output": str(r.get("output"))[:1500],
                                 "pipeline_id": r.get("pipeline_id")}
                                for r in runs if r.get("status") == "succeeded"][:budget],
                "recently_published": [{"agent_id": a.get("agent_id"),
                                        "version": a.get("version"),
                                        "telos": a.get("telos")} for a in population]}, budget

    if founder_id == "quarantine-warden":
        failing = [r for r in runs if r.get("status") not in (None, "succeeded")]
        if not failing:
            return {}, 0
        return {"failing_runs": [{"run_id": r.get("run_id"), "status": r.get("status"),
                                  "halt_reason": r.get("halt_reason"),
                                  "pipeline_id": r.get("pipeline_id"),
                                  "agents": r.get("agents")} for r in failing[:30]],
                "population": [{"agent_id": a.get("agent_id"), "version": a.get("version"),
                                "reputation_score": a.get("reputation_score"),
                                "lifecycle": a.get("lifecycle")} for a in population]}, len(failing)

    return {}, 0


# -------------------------------------------------------------------- effects

async def _apply(founder_id: str, decision: Dict[str, Any], org_id: str,
                 project_id: str, cycle: Cycle) -> None:
    """Turn a judgement into the change it calls for, through the real APIs."""
    if founder_id == "quarantine-warden":
        action = (decision.get("action") or "NO_ACTION").upper()
        subject = decision.get("subject") or {}
        agent_id = subject.get("agent_id")
        if action == "QUARANTINE" and agent_id:
            # Dependents first: quarantining an agent that published pipelines
            # pin breaks those pipelines, and that decision is the Arbiter's.
            deps = await _registry("GET", f"/agents/{agent_id}/dependents",
                                   params={"org_id": org_id, "project_id": project_id,
                                           "version": subject.get("version") or "1.0.0"})
            dependents = (deps.json().get("dependents", [])
                          if deps is not None and deps.status_code == 200 else [])
            if dependents:
                cycle.effects.append({
                    "action": "ESCALATED", "agent_id": agent_id,
                    "reason": "published pipelines pin this agent",
                    "dependents": dependents})
                return
            res = await _registry("POST", f"/agents/{agent_id}/lifecycle",
                                  json={"org_id": org_id, "project_id": project_id,
                                        "lifecycle": "dormant"})
            cycle.effects.append({
                "action": "QUARANTINED" if res is not None and res.status_code == 200
                          else "QUARANTINE_FAILED",
                "agent_id": agent_id,
                "detail": (res.text[:200] if res is not None else "registry unreachable"),
                "release_condition": decision.get("release_condition")})
        elif action == "RELEASE" and agent_id:
            res = await _registry("POST", f"/agents/{agent_id}/lifecycle",
                                  json={"org_id": org_id, "project_id": project_id,
                                        "lifecycle": "active"})
            cycle.effects.append({
                "action": "RELEASED" if res is not None and res.status_code == 200
                          else "RELEASE_FAILED",
                "agent_id": agent_id})

    elif founder_id == "proving-ground":
        # Reputation is the effect a duty cycle may have on its own; a version
        # bump is a publication, and publication is the Progenitor's.
        for finding in decision.get("findings", [])[:5]:
            agent_id = finding.get("agent_id")
            if not agent_id:
                continue
            severity = str(finding.get("severity", "")).lower()
            delta = {"high": -5.0, "medium": -2.0, "low": -0.5}.get(severity, -1.0)
            res = await _registry("POST", f"/agents/{agent_id}/audit",
                                  json={"org_id": org_id, "project_id": project_id,
                                        "auditor_agent_id": "proving-ground",
                                        "passed_compliance": False,
                                        "reputation_delta": delta,
                                        "notes": str(finding.get("defect"))[:500]})
            cycle.effects.append({
                "action": "REPUTATION_ADJUSTED" if res is not None and res.status_code == 200
                          else "AUDIT_FAILED",
                "agent_id": agent_id, "delta": delta,
                "defect": finding.get("defect")})
        for proposal in decision.get("proposals", [])[:5]:
            # Recorded, not applied. Adoption is the Evolution Driver's decision
            # and publication is the Progenitor's; an evaluator that could
            # rewrite published agents on its own judgement is an evaluator with
            # no check on it.
            cycle.effects.append({"action": "PROPOSAL_RECORDED", **proposal})

    elif founder_id == "adversary":
        for attack in decision.get("attacks", [])[:8]:
            cycle.effects.append({"action": "FINDING_RECORDED", **attack})
        if str(decision.get("verdict", "")).upper() == "REFUTED":
            cycle.effects.append({
                "action": "ESCALATED_TO_CRITIC",
                "conclusion": str(decision.get("conclusion"))[:400],
                "objection": str(decision.get("strongest_objection"))[:400]})

    elif founder_id == "anomaly-detector":
        for anomaly in decision.get("anomalies", [])[:10]:
            cycle.effects.append({"action": "ANOMALY_RECORDED", **anomaly})


# ------------------------------------------------------------------ scheduler

class AutonomyScheduler:
    """Wakes the duty-bearing founders, and remembers what they did."""

    CYCLES_TABLE = "autonomy_cycles"

    def __init__(self, client_factory=None, history: int = 200):
        self._client_factory = client_factory
        self._watchlist: Dict[Tuple[str, str], float] = {}
        self._last_run: Dict[Tuple[str, str, str], float] = {}
        self._cycles: deque = deque(maxlen=history)
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._ready: set = set()

    # ---- lifecycle

    def watch(self, org_id: str, project_id: str) -> None:
        """Add a project to the watchlist. Called when one is created or used."""
        key = (org_id, project_id)
        if key not in self._watchlist:
            logger.info("autonomy is now watching %s/%s", org_id, project_id)
        self._watchlist[key] = time.time()

    def unwatch(self, org_id: str, project_id: str) -> None:
        self._watchlist.pop((org_id, project_id), None)

    @property
    def watching(self) -> List[Dict[str, str]]:
        return [{"org_id": o, "project_id": p} for (o, p) in self._watchlist]

    @property
    def cycles(self) -> List[Dict[str, Any]]:
        return [c.to_dict() for c in reversed(self._cycles)]

    def status(self) -> Dict[str, Any]:
        return {
            "enabled": AUTONOMY_ENABLED,
            "running": self._running,
            "tick_seconds": TICK_SECONDS,
            "watching": self.watching,
            "duties": [{"founder_id": f.id, "name": f.name,
                        "interval_seconds": f.duty.interval_seconds,
                        "watches": f.duty.watches, "effect": f.duty.effect,
                        "budget_per_cycle": f.duty.budget_per_cycle}
                       for f in AUTONOMOUS],
            "cycles_recorded": len(self._cycles),
        }

    async def start(self) -> None:
        if not AUTONOMY_ENABLED:
            logger.info("autonomy is disabled by configuration; no duty cycles will run")
            return
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="autonomy-scheduler")
        logger.info("autonomy scheduler started: %d duties, %ds tick",
                    len(AUTONOMOUS), TICK_SECONDS)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                # Expected: this is how the loop is told to end at shutdown.
                pass
            self._task = None

    # ---- the loop

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                # A duty that raises must not take the scheduler down with it;
                # the next tick should still happen.
                logger.exception("autonomy tick failed; continuing")
            await asyncio.sleep(TICK_SECONDS)

    async def _tick(self) -> None:
        now = time.time()
        for (org_id, project_id) in list(self._watchlist):
            for f in AUTONOMOUS:
                key = (org_id, project_id, f.id)
                last = self._last_run.get(key, 0.0)
                if now - last < f.duty.interval_seconds:
                    continue
                self._last_run[key] = now
                await self.run_once(org_id, project_id, f.id)

    # ---- one cycle

    async def run_once(self, org_id: str, project_id: str,
                       founder_id: str) -> Dict[str, Any]:
        """Run one duty cycle now. Also the manual trigger behind the API."""
        f = founder(founder_id)
        if not f or not f.duty:
            return {"error": f"{founder_id} is not a duty-bearing founder"}

        cycle = Cycle(org_id, project_id, founder_id)
        try:
            evidence, subjects = await _gather(founder_id, org_id, project_id,
                                               f.duty.budget_per_cycle)
            cycle.subjects = subjects
            if subjects == 0:
                # Nothing to judge. Recorded as a quiet cycle without spending a
                # model call on an empty project.
                cycle.quiet = True
            else:
                decision = await _ask(founder_id, evidence)
                if decision is None:
                    cycle.error = "the founder could not be reached to judge the evidence"
                else:
                    cycle.quiet = bool(decision.get("quiet", False))
                    cycle.findings = (decision.get("findings")
                                      or decision.get("anomalies")
                                      or decision.get("attacks") or [])
                    if not cycle.quiet:
                        await _apply(founder_id, decision, org_id, project_id, cycle)
                    if cycle.findings or cycle.effects:
                        cycle.quiet = False
        except Exception as e:
            logger.exception("duty cycle %s failed in %s/%s", founder_id, org_id, project_id)
            cycle.error = str(e)
        finally:
            cycle.finished_at = time.time()
            self._cycles.append(cycle)
            await self._persist(cycle)

        return cycle.to_dict()

    # ---- the record

    async def _persist(self, cycle: Cycle) -> None:
        """Write the cycle where it can be read back.

        A duty whose only trace is a log line cannot be audited, and the whole
        argument for letting these agents act without being asked is that their
        actions are on the record.
        """
        if not self._client_factory:
            return
        try:
            client = await self._client_factory(cycle.org_id)
            if cycle.org_id not in self._ready:
                await client.create_vertex_table(self.CYCLES_TABLE, realm=cycle.org_id)
                self._ready.add(cycle.org_id)
            await client.add_vertex(table_name=self.CYCLES_TABLE, realm=cycle.org_id,
                                    space=cycle.project_id, payload=cycle.to_dict())
        except Exception as e:
            logger.warning("could not persist the %s cycle: %s", cycle.founder_id, e)


scheduler = AutonomyScheduler()
