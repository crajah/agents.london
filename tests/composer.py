"""Turning one natural-language goal into a published, runnable pipeline.

This is the orchestration the spec exists to make possible, written out in the
open so the tests can assert on each stage:

    a goal in English
      → decomposed into ordered sub-goals            (the model)
      → each sub-goal matched to a registered agent  (RAG over the agent graph)
      → the matches composed into a pipeline         (steps and dependencies)
      → published                                    (validated, pinned, hashed)
      → executed                                     (a run, in the graph)

Nothing here is special to the tests. It is the shape any orchestrator would
take, and it uses only the registries' public HTTP surface — which is the point:
if this needs a private hook, the surface is wrong.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

import httpx

DECOMPOSE_SYSTEM = """\
You break a goal into an ordered list of independent processing stages.

Reply with ONLY a JSON array of objects, no prose and no code fences. Each
object has:
  "step": a short snake_case identifier
  "need": one sentence describing the CAPABILITY required, written as a
          description of what a worker does — not as an instruction

Produce between 2 and 4 stages. Order them so each stage consumes the previous
stage's output.

Example for "clean up this data and chart it":
[{"step":"clean","need":"Cleans and normalises messy tabular data."},
 {"step":"chart","need":"Produces charts and visual summaries from data."}]
"""


def parse_json_array(text: str) -> List[Dict[str, Any]]:
    """Pull a JSON array out of a model's reply.

    Models wrap JSON in fences and prose even when told not to, and a test that
    fails because of a stray ``` is a test that reports the wrong problem. The
    first well-formed array wins.
    """
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    if fenced:
        text = fenced.group(1).strip()
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1:
        raise ValueError(f"no JSON array in model reply: {text[:300]!r}")
    return json.loads(text[start:end + 1])


async def decompose(goal: str, router: str, key: str, model: str,
                    timeout: float = 120.0) -> List[Dict[str, str]]:
    """Ask the model to break one goal into ordered capability needs."""
    async with httpx.AsyncClient(timeout=timeout) as http:
        res = await http.post(
            f"{router.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": model, "temperature": 0.0, "max_tokens": 400,
                  "messages": [{"role": "system", "content": DECOMPOSE_SYSTEM},
                               {"role": "user", "content": goal}]})
    res.raise_for_status()
    stages = parse_json_array(res.json()["choices"][0]["message"]["content"])
    out = []
    for index, stage in enumerate(stages):
        step = str(stage.get("step") or f"stage_{index}")
        step = re.sub(r"[^a-z0-9_]+", "_", step.lower()).strip("_") or f"stage_{index}"
        need = str(stage.get("need") or "").strip()
        if need:
            out.append({"step": step, "need": need})
    return out


async def find_agent(agents: httpx.AsyncClient, need: str, org_id: str,
                     project_id: str) -> Optional[Dict[str, Any]]:
    """The best registered agent for one capability need — RAG over the graph.

    This is `GET /discover`, the spec's §10 "by vector" path: the caller says
    what it needs in its own words and the registry answers from the embeddings
    of every published agent's telos and description.
    """
    res = await agents.get("/discover", params={
        "q": need, "kind": "agent", "org_id": org_id,
        "project_id": project_id, "top_k": 1})
    res.raise_for_status()
    results = res.json()["results"]
    return results[0] if results else None


def linear_pipeline(*, pipeline_id: str, slug: str, name: str, telos: str,
                    org_id: str, project_id: str,
                    stages: List[Dict[str, Any]],
                    input_schema: Dict[str, Any],
                    output_schema: Dict[str, Any],
                    version: str = "1.0.0") -> Dict[str, Any]:
    """Compose discovered agents into a chain.

    Each edge carries `payload_map: {"result": "prompt"}`, so one step's
    declared output feeds the next step's declared input. The registry checks
    that mapping against both agents' schemas at publish time (§9, rejection
    7): a chain that could not pass data is rejected before it can run and
    produce a plausible wrong answer.
    """
    steps = {
        stage["step"]: {"version_id": f"agv_{stage['agent']['id']}_{stage['agent']['version']}",
                        "alias": stage["agent"]["slug"]}
        for stage in stages
    }
    dependencies = [
        {"from_step": stages[i]["step"], "to_step": stages[i + 1]["step"],
         "relationship": "depends_on", "payload_map": {"result": "prompt"}}
        for i in range(len(stages) - 1)
    ]
    return {
        "org_id": org_id, "project_id": project_id,
        "identity": {"pipeline_id": pipeline_id, "name": name, "slug": slug,
                     "telos": telos, "description": telos},
        "version": {
            "pipeline_id": pipeline_id, "version": version,
            "steps": steps, "dependencies": dependencies,
            "entry_steps": [stages[0]["step"]],
            "exit_steps": [stages[-1]["step"]],
            "input_schema": input_schema, "output_schema": output_schema,
            "execution": {"max_iterations": 20, "concurrency": 1,
                          "on_limit": "halt_and_return"},
            "capabilities": sorted({c for stage in stages
                                    for c in stage["agent"].get("capabilities", [])}),
        },
    }


class Composition:
    """What a single prompt produced, with every intermediate step kept.

    The stages and the discovery results are retained deliberately: a test that
    can only assert on the final answer cannot say *why* a composition was
    wrong, and "the pipeline ran" is a much weaker claim than "these three
    agents were chosen, in this order, for these reasons".
    """

    def __init__(self, goal: str, stages: List[Dict[str, Any]],
                 registration: Dict[str, Any], slug: str, version: str):
        self.goal = goal
        self.stages = stages
        self.registration = registration
        self.slug = slug
        self.version = version

    @property
    def chosen(self) -> List[str]:
        return [stage["agent"]["id"] for stage in self.stages]

    @property
    def step_order(self) -> List[str]:
        return [stage["step"] for stage in self.stages]

    def __repr__(self) -> str:
        pairs = ", ".join(f"{s['step']}->{s['agent']['slug']}" for s in self.stages)
        return f"<Composition {self.slug}@{self.version}: {pairs}>"


async def compose_from_prompt(
        *, goal: str, agents: httpx.AsyncClient, org_id: str, project_id: str,
        router: str, key: str, model: str, pipeline_id: str, slug: str,
        input_schema: Dict[str, Any], output_schema: Dict[str, Any],
        stages: Optional[List[Dict[str, str]]] = None) -> Composition:
    """One goal in, one published pipeline out.

    `stages` may be supplied to skip the model's decomposition — used by the
    test that wants to isolate discovery and composition from the variability
    of an LLM planning step. Left None, the decomposition is real too.
    """
    if stages is None:
        stages = await decompose(goal, router, key, model)
    if len(stages) < 2:
        raise AssertionError(f"decomposition produced too few stages: {stages}")

    resolved: List[Dict[str, Any]] = []
    seen_steps = set()
    for stage in stages:
        found = await find_agent(agents, stage["need"], org_id, project_id)
        if found is None:
            raise AssertionError(
                f"no agent found for {stage['need']!r}; discovery returned nothing")
        step = stage["step"]
        # Step identity is the step, not the agent (§3.4), so the same agent may
        # legitimately appear twice — but two steps cannot share a name.
        while step in seen_steps:
            step = f"{step}_2"
        seen_steps.add(step)
        resolved.append({"step": step, "need": stage["need"], "agent": found})

    body = linear_pipeline(
        pipeline_id=pipeline_id, slug=slug, name=slug.replace("-", " ").title(),
        telos=goal, org_id=org_id, project_id=project_id, stages=resolved,
        input_schema=input_schema, output_schema=output_schema)

    res = await agents.post("/pipelines", json=body)
    if res.status_code != 200:
        raise AssertionError(f"pipeline registration failed: {res.text}")
    return Composition(goal, resolved, res.json(), slug, "1.0.0")
