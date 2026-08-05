"""Standalone integration test for the agent.london civilization engine.

Tests: user creation, project provisioning, agent materialization with progeny lineage,
agent versioning/iteration, RAG indexing/search, conductor orchestration, ReAct tool loops,
and the LLM-driven prompt router.

Designed to run locally without Kubernetes — gracefully handles missing Redis, LiteLLM,
and agent-registry microservice.
"""
import asyncio
import os
import sys
import httpx

# Ensure local dev defaults — avoid 30s timeouts to unreachable K8s cluster URLs
os.environ.setdefault("OPENAI_API_BASE", "http://localhost:4000/v1")
os.environ.setdefault("CIVILIZATION_ENGINE_TYPE", "NATIVE")
os.environ.setdefault("RAG_EMBEDDING_MODEL", "text-embedding-3-small")
os.environ.setdefault("RAG_EMBEDDING_DIM", "1536")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))

from civilization_factory import get_civilization_engine

civilization_engine = get_civilization_engine()

PASS = 0
FAIL = 0


def report(label, success, detail=""):
    global PASS, FAIL
    status = "PASS" if success else "FAIL"
    if success:
        PASS += 1
    else:
        FAIL += 1
    print(f"  [{status}] {label}" + (f" — {detail}" if detail else ""))


async def main():
    print("=" * 70)
    print(f"AGENT.LONDON CIVILIZATION ENGINE INTEGRATION TEST")
    print(f"Engine: {os.getenv('CIVILIZATION_ENGINE_TYPE', 'NATIVE')}")
    print(f"LiteLLM: {os.getenv('OPENAI_API_BASE')}")
    print("=" * 70)

    org_id = "org_test_run"
    username = "test_user"
    email = "test@agent.london"
    project_name = "proj_test_civilization"

    # ── 1. User Creation ────────────────────────────────────────────────
    print("\n[1] User Creation")
    try:
        user_res = await civilization_engine.create_user(org_id, username, email)
        user_id = user_res.get("user_id", f"user_{username}")
        report("create_user", True, f"user_id={user_id}")
    except Exception as e:
        user_id = f"user_{username}"
        report("create_user", False, str(e))

    # ── 2. Project Creation & Prime Agent Provisioning ──────────────────
    print("\n[2] Project Creation")
    try:
        proj_res = await civilization_engine.create_project(
            org_id=org_id, user_id=user_id, project_name=project_name,
            constitution_rules=["Protect infrastructure integrity", "Every agent must fulfill its Telos"]
        )
        project_id = proj_res.get("project_id", project_name)
        prime_count = proj_res.get("prime_agents_count", len(proj_res.get("agents", [])))
        report("create_project", True, f"project_id={project_id}, prime_agents={prime_count}")
    except Exception as e:
        project_id = project_name
        report("create_project", False, str(e))

    # ── 3. Agent Materialization with Progeny Lineage ───────────────────
    print("\n[3] Agent Materialization (Progeny)")
    worker_res = {}
    try:
        creator_id = f"prime-orchestrator-{project_id}"
        worker_res = await civilization_engine.materialize_worker_agent(
            org_id=org_id, project_id=project_id, user_id=user_id,
            agent_name="DataSynthesizerWorker",
            telos="Process raw payload streams into structured JSON schemas.",
            system_prompt="You process raw payload data into verified structured JSON formats.",
            parent_agent_id=creator_id,
            tools=["mcp-pgvector-search", "mcp-redis-queue"]
        )
        agent_id = worker_res.get("agent_id", "unknown")
        lineage = worker_res.get("lineage", {})
        report("materialize_worker_agent", True, f"agent_id={agent_id}, parent={lineage.get('parent_agent_id', 'N/A')}")
    except Exception as e:
        report("materialize_worker_agent", False, str(e))

    # ── 4. Agent Iteration (Versioning) ─────────────────────────────────
    print("\n[4] Agent Iteration (Version 2)")
    try:
        iterated = await civilization_engine.iterate_agent(
            org_id=org_id, project_id=project_id,
            original_agent_id=worker_res.get("agent_id", "unknown"),
            improved_prompt="You are an advanced data processor. Parse, validate, and transform raw payloads into strictly typed JSON with schema verification.",
            improved_tools=["mcp-pgvector-search", "mcp-redis-queue", "mcp-sql-query"],
            iteration_reason="Enhanced schema validation capability"
        )
        report("iterate_agent", True, f"v2_id={iterated.get('agent_id')}, iteration_of={iterated.get('iteration_of')}")
    except Exception as e:
        report("iterate_agent", False, str(e))

    # ── 5. Agent Registry Microservice (if running) ─────────────────────
    print("\n[5] Agent Registry Microservice")
    async with httpx.AsyncClient(timeout=3.0) as client:
        # Verify signature
        try:
            v_res = await client.post("http://localhost:8001/agents/verify", json={
                "agent_id": worker_res.get("agent_id", "test"),
                "public_key": worker_res.get("public_key", "ed25519:test"),
                "signature": worker_res.get("signature", "ed25519:test_sig"),
                "payload_text": "test_payload"
            })
            report("verify_signature", v_res.status_code == 200, f"status={v_res.status_code}")
        except Exception as e:
            report("verify_signature", False, f"registry offline: {type(e).__name__}")

        # Audit agent
        try:
            a_res = await client.post(f"http://localhost:8001/agents/{worker_res.get('agent_id', 'test')}/audit", json={
                "auditor_id": f"inspector-{project_id}",
                "reputation_delta": 5.0,
                "audit_notes": "Passed JSON compliance check",
                "passed_compliance": True
            })
            report("audit_agent", a_res.status_code == 200, f"status={a_res.status_code}")
        except Exception as e:
            report("audit_agent", False, f"registry offline: {type(e).__name__}")

    # ── 6. RAG Indexing ─────────────────────────────────────────────────
    print("\n[6] RAG Indexing & Search")
    try:
        rag_res = await civilization_engine.index_agent_registry_for_rag(org_id, project_id)
        report("index_agent_registry_rag", True, f"status={rag_res.get('status', 'ok')}")
    except Exception as e:
        report("index_agent_registry_rag", False, str(e))

    try:
        search_res = await civilization_engine.search_agent_registry_rag(org_id, project_id, "data processing JSON", top_k=2)
        report("search_agent_registry_rag", True, f"candidates={len(search_res)}")
    except Exception as e:
        report("search_agent_registry_rag", False, str(e))

    try:
        tool_rag_res = await civilization_engine.index_tool_registry_for_rag(org_id, project_id)
        report("index_tool_registry_rag", True, f"status={tool_rag_res.get('status', 'ok')}")
    except Exception as e:
        report("index_tool_registry_rag", False, str(e))

    try:
        tool_search = await civilization_engine.search_tool_registry_rag(org_id, project_id, "Google search", top_k=2)
        report("search_tool_registry_rag", True, f"tools={len(tool_search)}")
    except Exception as e:
        report("search_tool_registry_rag", False, str(e))

    # ── 7. Pipeline Registration ────────────────────────────────────────
    print("\n[7] Pipeline Registration")
    try:
        pipe_res = await civilization_engine.register_pipeline_in_registry(
            org_id=org_id, project_id=project_id,
            pipeline_name="TestAnalyticsPipeline",
            task_prompt="Process raw payload streams into structured JSON schemas",
            graph_nodes=[
                {"id": "n1", "name": "Ingest", "agent_id": f"signal-router-{project_id}"},
                {"id": "n2", "name": "Process", "agent_id": worker_res.get("agent_id", "worker")}
            ],
            graph_edges=[{"from": "n1", "to": "n2", "relationship": "depends_on"}],
            assigned_agent_ids=[f"signal-router-{project_id}", worker_res.get("agent_id", "worker")]
        )
        report("register_pipeline", True, f"pipeline_id={pipe_res.get('pipeline_id')}")
    except Exception as e:
        report("register_pipeline", False, str(e))

    # ── 8. Conductor Orchestration ──────────────────────────────────────
    print("\n[8] Conductor Orchestration")
    try:
        cond_res = await civilization_engine.run_conductor_orchestration(org_id, project_id, "Process raw payload streams into JSON")
        source = cond_res.get("execution_source", "unknown")
        has_answer = bool(cond_res.get("final_answer"))
        report("conductor_orchestration", has_answer, f"source={source}, has_answer={has_answer}")
    except Exception as e:
        report("conductor_orchestration", False, str(e))

    # ── 9. ReAct Tool Loop ──────────────────────────────────────────────
    print("\n[9] ReAct Tool Loop")
    try:
        react_res = await civilization_engine.run_react_loop(org_id, project_id, "search Google for Q3 analytics")
        steps = len(react_res.get("steps", []))
        has_answer = bool(react_res.get("final_answer"))
        report("react_loop", has_answer, f"steps={steps}, tools={react_res.get('matched_tools', [])}")
    except Exception as e:
        report("react_loop", False, str(e))

    # ── 10. LLM Prompt Router ───────────────────────────────────────────
    print("\n[10] LLM Prompt Router (process_user_prompt_with_llm)")
    try:
        router_res = await civilization_engine.process_user_prompt_with_llm(
            org_id=org_id, project_id=project_id,
            user_prompt="What is the capital of France?",
            isolation_mode="isolated"
        )
        mode = router_res.get("mode", "unknown")
        has_answer = bool(router_res.get("final_answer"))
        report("prompt_router", has_answer, f"mode={mode}, has_answer={has_answer}")
    except Exception as e:
        report("prompt_router", False, str(e))

    # ── Summary ─────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    total = PASS + FAIL
    print(f"RESULTS: {PASS}/{total} passed, {FAIL}/{total} failed")
    if FAIL == 0:
        print("ALL TESTS PASSED")
    else:
        print(f"FAILURES: {FAIL} test(s) need attention")
    print("=" * 70)

    return FAIL == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
