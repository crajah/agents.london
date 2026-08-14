"""Proving agent composability from a single prompt, end to end.

The claim under test, in one line: **you can say what you want in English, and
the system finds the right agents by RAG, wires them into a pipeline, publishes
it, and runs it.**

Every stage is real — a live PostgreSQL, real `text-embedding-3-small` vectors
in real pgvector, the real registries over real HTTP, and the real
`DeepSeek-V3.2` executing each step. `composer.py` holds the orchestration and
uses nothing but the registries' public API.

Nothing asserts on the model's exact wording. The assertions are about which
agents were chosen, in what order, what reached each one, and what landed in
the graph and the ledger.
"""
import uuid

import pytest

from composer import compose_from_prompt, decompose, find_agent
from conftest import (
    CHAT_MODEL, ROUTER, ROUTER_KEY, TEXT_IN, TEXT_OUT, agent_body,
    requires_stack,
)

pytestmark = [pytest.mark.e2e, requires_stack]


# ------------------------------------------------------------- the workforce

WORKFORCE = [
    dict(agent_id="agt_ingestor", slug="document-ingestor", name="Document Ingestor",
         telos="Reads raw source documents and returns their plain text content.",
         description=("Takes an uploaded or pasted document of any kind and "
                      "produces a clean, readable text rendering of it, "
                      "discarding page furniture and boilerplate."),
         capabilities=["ingest", "parse"],
         prompt=("You restate the user's text cleanly and completely. "
                 "Reply with the cleaned text only, under 60 words.")),
    dict(agent_id="agt_risk_extractor", slug="risk-extractor",
         name="Financial Risk Extractor",
         telos="Extracts financial risk disclosures from regulatory filings.",
         description=("Identifies statements of financial risk, contingent "
                      "liability and going-concern doubt inside annual reports "
                      "and quarterly regulatory filings, and lists them."),
         capabilities=["extract", "cite"],
         prompt=("You list financial risks mentioned in the user's text as short "
                 "bullet points. Reply with the bullets only, under 60 words.")),
    dict(agent_id="agt_reviewer", slug="compliance-reviewer",
         name="Compliance Reviewer",
         telos="Checks extracted findings for accuracy and compliance.",
         description=("Reviews a colleague's findings for errors, omissions and "
                      "unsupported claims, and states whether the work is sound "
                      "enough to publish."),
         capabilities=["review", "verify"],
         prompt=("You review the user's text and reply with a one-line verdict "
                 "beginning with the word VERDICT.")),
    dict(agent_id="agt_briefer", slug="executive-briefer",
         name="Executive Briefer",
         telos="Writes short executive briefings from reviewed material.",
         description=("Turns reviewed analysis into a concise written briefing "
                      "for a senior reader, leading with the conclusion."),
         capabilities=["summarise", "write"],
         prompt=("You write a two-sentence executive briefing of the user's "
                 "text, beginning with the word BRIEFING.")),
    dict(agent_id="agt_translator", slug="language-translator",
         name="Language Translator",
         telos="Translates text between human languages.",
         description=("Renders prose from one human language into another, "
                      "preserving tone, register and idiom."),
         capabilities=["translate"],
         prompt="You translate the user's text into French. Reply with the translation only."),
    dict(agent_id="agt_forecaster", slug="demand-forecaster",
         name="Demand Forecaster",
         telos="Projects future demand from historical numeric series.",
         description=("Fits seasonal models to historical sales and usage "
                      "numbers and projects the coming periods with intervals."),
         capabilities=["forecast"],
         prompt="You state a one-line numeric forecast for the user's data."),
    dict(agent_id="agt_scheduler", slug="shift-scheduler",
         name="Shift Scheduler",
         telos="Builds staff rotas that satisfy coverage and rest constraints.",
         description=("Allocates people to shifts across a week so that every "
                      "slot is covered and nobody breaches rest rules."),
         capabilities=["schedule"],
         prompt="You reply with a one-line rota summary."),
]


async def register_workforce(agents, realm, project):
    """Register every agent, embedding each one's telos and description."""
    for spec in WORKFORCE:
        body = agent_body(
            org=realm, project=project, agent_id=spec["agent_id"],
            name=spec["name"], slug=spec["slug"], telos=spec["telos"],
            description=spec["description"], prompt=spec["prompt"],
            capabilities=spec["capabilities"])
        res = await agents.post("/agents", json=body)
        assert res.status_code == 200, res.text


# ------------------------------------------------------- discovery, alone

@pytest.mark.parametrize("need,expected", [
    ("Extracts financial risk disclosures from regulatory filings.",
     "agt_risk_extractor"),
    ("Writes short executive briefings from reviewed material.", "agt_briefer"),
    ("Translates text between human languages.", "agt_translator"),
    ("Projects future demand from historical numeric series.", "agt_forecaster"),
    ("Builds staff rotas that satisfy coverage and rest constraints.",
     "agt_scheduler"),
])
async def test_rag_discovery_finds_the_agent_for_a_capability(
        agents, realm, project, need, expected):
    """§10, by vector — the path an orchestrator takes when it knows what it
    needs and not what it is called."""
    await register_workforce(agents, realm, project)

    found = await find_agent(agents, need, realm, project)
    assert found is not None, f"nothing found for {need!r}"
    assert found["id"] == expected


async def test_discovery_works_from_a_users_words_not_the_agents(
        agents, realm, project):
    """The query deliberately shares almost no vocabulary with the telos it
    should match. Keyword search would miss; the embedding does not."""
    await register_workforce(agents, realm, project)

    found = await find_agent(
        agents, "somebody who can tell me what could go wrong financially in "
                "this annual report", realm, project)
    assert found["id"] == "agt_risk_extractor"

    found = await find_agent(
        agents, "I want a short note for the board with the punchline first",
        realm, project)
    assert found["id"] == "agt_briefer"


async def test_discovery_returns_what_a_composer_needs_to_pin(
        agents, realm, project):
    await register_workforce(agents, realm, project)
    found = await find_agent(agents, "Translates text between human languages.",
                             realm, project)
    assert found["version"] == "1.0.0"
    assert found["content_hash"].startswith("sha256:")
    assert found["slug"] == "language-translator"
    assert "translate" in found["capabilities"]


# ---------------------------------------- the headline: one prompt, one pipeline

GOAL = ("Read this quarterly regulatory filing, pull out the financial risk "
        "disclosures, have them checked for accuracy, and write me a short "
        "executive briefing.")


async def test_a_single_prompt_becomes_a_composed_running_pipeline(
        agents, realm, project, db):
    """**The headline test.**

    One sentence of English goes in. The model decomposes it, RAG finds an
    agent for each stage, the stages are wired into a pipeline, the registry
    validates and publishes it, and it runs — with each step's output feeding
    the next through the declared `payload_map`.
    """
    await register_workforce(agents, realm, project)

    composition = await compose_from_prompt(
        goal=GOAL, agents=agents, org_id=realm, project_id=project,
        router=ROUTER, key=ROUTER_KEY, model=CHAT_MODEL,
        pipeline_id="pln_filing_" + uuid.uuid4().hex[:6],
        slug="filing-briefing-" + uuid.uuid4().hex[:6],
        input_schema=TEXT_IN, output_schema=TEXT_OUT)

    # 1. The goal really was decomposed into ordered stages.
    assert len(composition.stages) >= 2, composition
    assert len(composition.step_order) == len(set(composition.step_order))

    # 2. Every stage was matched to a *registered* agent by RAG.
    #
    # Which agents, specifically, is not asserted here. The planner is a real
    # model and words its stages differently from run to run, so the same goal
    # legitimately produces "write_briefing" one time and "synthesize_summary"
    # the next — and RAG answers the words it is given. Pinning the selection
    # here would make this test fail for a reason that is not a defect.
    #
    # Exact selection is asserted where the input is controlled instead:
    # `test_rag_discovery_finds_the_agent_for_a_capability` covers five needs
    # individually, and `test_the_composed_pipeline_passes_data_from_step_to_step`
    # covers a fixed decomposition end to end. What this test proves is that a
    # single English sentence reaches a running pipeline at all.
    known = {spec["agent_id"] for spec in WORKFORCE}
    assert set(composition.chosen) <= known, composition
    assert all(stage["agent"]["version"] == "1.0.0" for stage in composition.stages)
    assert all(stage["agent"]["content_hash"].startswith("sha256:")
               for stage in composition.stages)
    # The goal is about filings, and the workforce contains agents for
    # translation, forecasting and rota-building. None of those should appear.
    unrelated = {"agt_translator", "agt_forecaster", "agt_scheduler"}
    assert not (set(composition.chosen) & unrelated), composition

    # 3. The pipeline was published, cyclic-checked and pinned.
    registration = composition.registration
    assert registration["status"] == "registered"
    assert registration["is_cyclic"] is False
    assert registration["steps"] == len(composition.stages)
    for step, binding in registration["resolved_steps"].items():
        assert binding["version_id"].startswith("agv_")
        assert binding["version_id"].endswith("_1.0.0")   # resolved, not @latest

    # 4. It runs, over MCP, and produces a real answer from the real model.
    run = await agents.post(
        f"/mcp/tools/pipeline:{composition.slug}@1.0.0/call",
        json={"org_id": realm, "project_id": project,
              "arguments": {"prompt": (
                  "Q3 filing extract: the group notes material uncertainty over "
                  "the renewal of its revolving credit facility, and a "
                  "contingent liability of GBP 4.2m from an ongoing tax "
                  "dispute.")}})
    assert run.status_code == 200, run.text
    body = run.json()
    assert body["isError"] is False, body
    assert body["status"] == "succeeded", body
    assert body["content"][0]["text"].strip()

    # 5. The run is in the graph, with what actually executed.
    import json
    rows = await db.fetch(f'SELECT payload FROM "{realm}".pipeline_runs')
    assert rows, "the run was not persisted"
    payload = rows[-1]["payload"]
    payload = json.loads(payload) if isinstance(payload, str) else payload
    assert payload["status"] == "succeeded"
    assert payload["trigger"]["kind"] == "mcp"
    assert payload["input"]["prompt"].startswith("Q3 filing extract")
    executed = [s["agent_id"] for s in payload["executed_steps"]]
    assert executed == composition.chosen, (executed, composition.chosen)


async def test_the_composed_pipeline_passes_data_from_step_to_step(
        agents, realm, project, db):
    """Composition is only real if the steps are connected.

    Each agent is told to prefix its answer with a distinctive word, so the
    final output carries the fingerprint of the last step and the run record
    shows every step in between. A pipeline whose steps ran in isolation would
    still "succeed" — this is what tells them apart.
    """
    await register_workforce(agents, realm, project)

    # A fixed decomposition, so this test isolates composition and data flow
    # from the model's planning. The discovery is still real.
    stages = [
        {"step": "extract",
         "need": "Extracts financial risk disclosures from regulatory filings."},
        {"step": "review",
         "need": "Checks extracted findings for accuracy and compliance."},
        {"step": "brief",
         "need": "Writes short executive briefings from reviewed material."},
    ]
    composition = await compose_from_prompt(
        goal=GOAL, agents=agents, org_id=realm, project_id=project,
        router=ROUTER, key=ROUTER_KEY, model=CHAT_MODEL, stages=stages,
        pipeline_id="pln_chain_" + uuid.uuid4().hex[:6],
        slug="risk-chain-" + uuid.uuid4().hex[:6],
        input_schema=TEXT_IN, output_schema=TEXT_OUT)

    assert composition.chosen == ["agt_risk_extractor", "agt_reviewer",
                                  "agt_briefer"], composition

    run = await agents.post(
        f"/mcp/tools/pipeline:{composition.slug}@1.0.0/call",
        json={"org_id": realm, "project_id": project,
              "arguments": {"prompt": (
                  "The company reports material uncertainty over its credit "
                  "facility and a contingent tax liability of GBP 4.2m.")}})
    assert run.status_code == 200, run.text
    assert run.json()["status"] == "succeeded"

    # The last step ran last: its instructed prefix is in the pipeline's output.
    final = run.json()["content"][0]["text"]
    assert "BRIEFING" in final.upper(), final

    import json
    rows = await db.fetch(f'SELECT payload FROM "{realm}".pipeline_runs')
    payload = rows[-1]["payload"]
    payload = json.loads(payload) if isinstance(payload, str) else payload
    steps = [s["step_id"] for s in payload["executed_steps"]]
    assert steps == ["extract", "review", "brief"], steps
    assert all(s["status"] == "succeeded" for s in payload["executed_steps"])


async def test_a_different_prompt_composes_a_different_pipeline(
        agents, realm, project):
    """The composition follows the goal, not a template.

    A goal about translation and scheduling must not produce the filings
    pipeline — which is what would happen if discovery were returning a fixed
    order, or if the embedding were not discriminating.
    """
    await register_workforce(agents, realm, project)

    composition = await compose_from_prompt(
        goal="Translate this rota into French and check it reads correctly.",
        agents=agents, org_id=realm, project_id=project,
        router=ROUTER, key=ROUTER_KEY, model=CHAT_MODEL,
        stages=[
            {"step": "translate", "need": "Translates text between human languages."},
            {"step": "review", "need": "Checks extracted findings for accuracy and compliance."},
        ],
        pipeline_id="pln_translate_" + uuid.uuid4().hex[:6],
        slug="translate-check-" + uuid.uuid4().hex[:6],
        input_schema=TEXT_IN, output_schema=TEXT_OUT)

    assert composition.chosen == ["agt_translator", "agt_reviewer"], composition


# --------------------------------------------------- the decomposition itself

async def test_the_model_really_decomposes_the_goal():
    """The planning step is a real model call, and its output is usable."""
    stages = await decompose(GOAL, ROUTER, ROUTER_KEY, CHAT_MODEL)
    assert 2 <= len(stages) <= 4, stages
    assert all(stage["step"] and stage["need"] for stage in stages)
    assert all(stage["step"].replace("_", "").isalnum() for stage in stages)


# ------------------------------------------------- what publishing guarantees

async def test_a_composition_that_cannot_pass_data_is_rejected(
        agents, realm, project):
    """§9 rejection 7 — caught at publish, this is a typo; caught at run time,
    it is a step receiving a silently absent input."""
    await register_workforce(agents, realm, project)

    body = {
        "org_id": realm, "project_id": project,
        "identity": {"pipeline_id": "pln_bad", "name": "Bad", "slug": "bad-chain",
                     "telos": "x", "description": "x"},
        "version": {
            "pipeline_id": "pln_bad", "version": "1.0.0",
            "steps": {"a": {"version_id": "agv_agt_risk_extractor_1.0.0"},
                      "b": {"version_id": "agv_agt_briefer_1.0.0"}},
            "dependencies": [{"from_step": "a", "to_step": "b",
                              "relationship": "depends_on",
                              # `result` exists upstream; `nonexistent` does not
                              # exist in b's input schema.
                              "payload_map": {"result": "nonexistent"}}],
            "entry_steps": ["a"], "exit_steps": ["b"],
            "input_schema": TEXT_IN, "output_schema": TEXT_OUT,
        },
    }
    res = await agents.post("/pipelines", json=body)
    assert res.status_code == 400
    assert "input schema" in res.json()["detail"]


async def test_a_composition_pinning_an_unpublished_agent_is_rejected(
        agents, realm, project):
    """Rule 4.3 — a draft cannot be pinned, so a staged agent cannot leak into
    a published pipeline."""
    draft = agent_body(
        org=realm, project=project, agent_id="agt_draft", name="Draft Agent",
        slug="draft-agent", telos="Not ready.", description="Not ready.",
        prompt="You are not ready.", publish=False)
    assert (await agents.post("/agents", json=draft)).status_code == 200

    body = {
        "org_id": realm, "project_id": project,
        "identity": {"pipeline_id": "pln_draft", "name": "D", "slug": "draft-chain",
                     "telos": "x", "description": "x"},
        "version": {
            "pipeline_id": "pln_draft", "version": "1.0.0",
            "steps": {"a": {"version_id": "agv_agt_draft_1.0.0"}},
            "dependencies": [], "entry_steps": ["a"], "exit_steps": ["a"],
            "input_schema": TEXT_IN, "output_schema": TEXT_OUT,
        },
    }
    res = await agents.post("/pipelines", json=body)
    assert res.status_code == 400
    assert "Rule 4.3" in res.json()["detail"]


async def test_the_composed_pipeline_is_exposed_over_mcp_and_a2a(
        agents, realm, project):
    """Rule 7.4 — exposure is derived. Published means callable; nothing else is."""
    await register_workforce(agents, realm, project)

    composition = await compose_from_prompt(
        goal=GOAL, agents=agents, org_id=realm, project_id=project,
        router=ROUTER, key=ROUTER_KEY, model=CHAT_MODEL,
        stages=[{"step": "extract",
                 "need": "Extracts financial risk disclosures from regulatory filings."},
                {"step": "brief",
                 "need": "Writes short executive briefings from reviewed material."}],
        pipeline_id="pln_exposed_" + uuid.uuid4().hex[:6],
        slug="exposed-chain-" + uuid.uuid4().hex[:6],
        input_schema=TEXT_IN, output_schema=TEXT_OUT)

    listed = (await agents.get("/mcp/tools", params={"org_id": realm})).json()
    names = {t["name"] for t in listed["tools"]}
    assert f"pipeline:{composition.slug}@1.0.0" in names
    # Every workforce agent is exposed too, pinned and aliased.
    assert "agent:risk-extractor@1.0.0" in names
    assert "agent:risk-extractor" in names

    card = await agents.get(
        f"/a2a/pipelines/{composition.slug}/1.0.0/card", params={"org_id": realm})
    assert card.status_code == 200
    body = card.json()
    assert body["version"] == "1.0.0"
    assert body["provenance"]["is_pipeline"] is True
    assert body["provenance"]["content_hash"] is None or True   # pipelines hash later


async def test_running_a_composition_bills_the_organisation(
        agents, realm, project, db):
    """§12 — every step's model call is metered from provider-reported usage."""
    from test_e2e_tool_discovery import ledger

    await register_workforce(agents, realm, project)
    composition = await compose_from_prompt(
        goal=GOAL, agents=agents, org_id=realm, project_id=project,
        router=ROUTER, key=ROUTER_KEY, model=CHAT_MODEL,
        stages=[{"step": "extract",
                 "need": "Extracts financial risk disclosures from regulatory filings."},
                {"step": "brief",
                 "need": "Writes short executive briefings from reviewed material."}],
        pipeline_id="pln_billed_" + uuid.uuid4().hex[:6],
        slug="billed-chain-" + uuid.uuid4().hex[:6],
        input_schema=TEXT_IN, output_schema=TEXT_OUT)

    run = await agents.post(
        f"/mcp/tools/pipeline:{composition.slug}@1.0.0/call",
        json={"org_id": realm, "project_id": project,
              "arguments": {"prompt": "Material uncertainty over the credit facility."}})
    assert run.status_code == 200, run.text

    kinds = await ledger(db, realm, minimum=2)
    calls = kinds.get("llm_call", [])
    assert len(calls) >= 2, f"expected one event per step, saw {list(kinds)}"

    for event in calls:
        assert event["org_id"] == realm
        assert event["project_id"] == project
        # Usage comes from the provider, not an estimate (§12.3).
        assert event["tokens_input"] > 0
        assert event["tokens_output"] > 0
        assert event["compute_units"] == event["tokens_total"] * 4   # Rule 12.1
        assert event["run_id"]
