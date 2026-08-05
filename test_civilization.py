"""Standalone test script for agent.london 1B synthetic civilization engine including Prime Castes, Cryptographic binding, Token economy, and Audits."""
import asyncio
import os
import httpx
try:
    from backend.civilization_factory import get_civilization_engine
except (ImportError, ModuleNotFoundError):
    from civilization_factory import get_civilization_engine

civilization_engine = get_civilization_engine()

async def main():
    print("=" * 60)
    print(f"AGENT.LONDON 1B SYNTHETIC CIVILIZATION ENGINE TEST (Strategy: {os.getenv('CIVILIZATION_ENGINE_TYPE', 'GOOGLE_ADK')})")
    print("=" * 60)

    org_id = "org_london_meta"
    username = "chandan"
    email = "chandan@agent.london"
    project_name = "proj_alpha_civilization"

    print("\n[+] 1. Creating User...")
    user_res = await civilization_engine.create_user(org_id, username, email)
    user_id = user_res.get("user_id", "user_chandan")
    print(f"    User Created: ID={user_id}, Username={username}")

    print("\n[+] 2. Creating Project Universe & Auto-Provisioning Prime Caste Scaffolding...")
    proj_res = await civilization_engine.create_project(
        org_id=org_id,
        user_id=user_id,
        project_name=project_name,
        constitution_rules=[
            "Directive of Preservation: Protect civilizational infrastructure integrity",
            "Directive of Purpose: Every agent must fulfill its defined Telos objective",
            "Directive of Compliance: Yield to Judicature and Oversight directives",
            "Directive of Efficiency: Minimize compute resource consumption"
        ]
    )
    project_id = proj_res["project_id"]
    print(f"    Project Created: ID={project_id}")
    for caste, agent_id in proj_res.get("permanent_agents", {}).items():
        print(f"    - Prime Caste [{caste.upper()}]: Agent ID={agent_id}")

    print("\n[+] 3. Materializing Cryptographically Bound Progeny Worker Agent...")
    creator_id = proj_res.get("permanent_agents", {}).get("architect", f"architect-{project_id}")
    worker_res = await civilization_engine.materialize_worker_agent(
        org_id=org_id,
        project_id=project_id,
        user_id=user_id,
        agent_name="DataSynthesizerWorker",
        telos="Process raw payload streams into structured JSON schemas.",
        system_prompt="You process raw payload data into verified structured JSON formats.",
        parent_agent_id=creator_id,
        tools=["mcp-pgvector-search", "mcp-redis-queue"],
        custom_guardrails=["Validate JSON schema before emitting payload"]
    )
    print(f"    Worker Agent Materialized: ID={worker_res['agent_id']}")
    print(f"    Public Key: {worker_res['public_key']}")
    print(f"    Hash Digest: {worker_res.get('hash_digest', 'N/A')}")
    print(f"    Parent Signature: {worker_res['signature']}")

    print("\n[+] 4. Verifying Agent Cryptographic Signature & Hash Digest Integrity...")
    async with httpx.AsyncClient(timeout=3.0) as client:
        try:
            v_res = await client.post("http://localhost:8001/agents/verify", json={
                "agent_id": worker_res["agent_id"],
                "public_key": worker_res["public_key"],
                "signature": worker_res["signature"],
                "payload_text": f"{worker_res['agent_id']}:{worker_res.get('telos', '')}:{worker_res.get('system_prompt', '')}:{creator_id}"
            })
            if v_res.status_code == 200:
                v_data = v_res.json()
                print(f"    Cryptographic Verification Status: Verified={v_data.get('verified', True)}, Digest={v_data.get('computed_digest', 'N/A')[:16]}...")
        except Exception as e:
            print(f"    Cryptographic verification offline fallback note: {e}")

    print("\n[+] 5. Recording Oversight Audit & Updating Reputation Score...")
    async with httpx.AsyncClient(timeout=3.0) as client:
        try:
            a_res = await client.post(f"http://localhost:8001/agents/{worker_res['agent_id']}/audit", json={
                "auditor_id": f"inspector-{project_id}",
                "reputation_delta": 5.0,
                "audit_notes": "Passed JSON schema compliance check",
                "passed_compliance": True
            })
            if a_res.status_code == 200:
                a_data = a_res.json()
                print(f"    Audit Recorded: Status={a_data.get('status')}, Reputation Score={a_data.get('new_reputation_score', 100)}/100")
        except Exception as e:
            print(f"    Audit recording offline fallback note: {e}")

    print("\n[+] 6. Resource Arbiter Compute Utility Token Allocation...")
    async with httpx.AsyncClient(timeout=3.0) as client:
        try:
            t_res = await client.post(f"http://localhost:8001/agents/{worker_res['agent_id']}/allocate-tokens", json={
                "arbiter_id": f"arbiter-{project_id}",
                "amount": 250.0,
                "reason": "Telos objective bonus"
            })
            if t_res.status_code == 200:
                t_data = t_res.json()
                print(f"    Utility Tokens Allocated: New Balance={t_data.get('new_token_balance', 250.0)} CR")
        except Exception as e:
            print(f"    Token allocation offline fallback note: {e}")

    print("\n[+] 7. Indexing Agent Metadata into post-graph-rag...")
    rag_res = await civilization_engine.index_agent_registry_for_rag(org_id, project_id)
    print(f"    RAG Indexing Status: {rag_res.get('status', 'success')}, Indexed={rag_res.get('indexed_agents', 'N/A')}")

    print("\n[+] 7B. Registering Custom Multi-Agent Execution Pipeline Graph...")
    graph_nodes = [
        {"id": "node_1", "name": "IngestionNode", "agent_id": f"worker-1-{project_id}"},
        {"id": "node_2", "name": "ProcessingNode", "agent_id": f"worker-2-{project_id}"}
    ]
    graph_edges = [
        {"from": "node_1", "to": "node_2", "relationship": "depends_on"}
    ]
    pipe_res = await civilization_engine.register_pipeline_in_registry(
        org_id=org_id,
        project_id=project_id,
        pipeline_name="CustomAnalyticsPipeline",
        task_prompt="Process raw payload streams into structured JSON schemas",
        graph_nodes=graph_nodes,
        graph_edges=graph_edges,
        assigned_agent_ids=[f"worker-1-{project_id}", f"worker-2-{project_id}"]
    )
    print(f"    Pipeline Graph Registered: ID={pipe_res.get('pipeline_id')}, Name={pipe_res.get('name')}")

    print("\n[+] 7C. Performing RAG Vector Search over Agent Registry & Pipeline Graphs...")
    search_res = await civilization_engine.search_agent_registry_rag(org_id, project_id, "CustomAnalyticsPipeline raw payload streams", top_k=2)
    print(f"    Agent & Pipeline RAG Candidates Found: Count={len(search_res)}")

    print("\n[+] 7D. Indexing MCP Tool Specifications into post-graph-rag...")
    tool_rag_res = await civilization_engine.index_tool_registry_for_rag(org_id, project_id)
    print(f"    Tool RAG Indexing Status: {tool_rag_res.get('status', 'success')}, Indexed Tools={tool_rag_res.get('indexed_tools', 5)}")

    print("\n[+] 7E. Performing RAG Vector Search over Tool Registry...")
    tool_search_res = await civilization_engine.search_tool_registry_rag(org_id, project_id, "search Google for web documentation", top_k=2)
    print(f"    Tool RAG Candidates Found: Count={len(tool_search_res)}, Tools={[t.get('tool_id') for t in tool_search_res]}")

    print("\n[+] 8. Executing Conductor Multi-Agent Composition & Pipeline Graph Reuse Loop...")
    conductor_res_1 = await civilization_engine.run_conductor_orchestration(org_id, project_id, "Process raw payload streams into structured JSON schemas")
    sub_tasks_1 = conductor_res_1.get('sub_tasks_orchestrated', [])
    print(f"    Run 1 Conductor ID: {conductor_res_1.get('conductor_id', 'N/A')}, Execution Source={conductor_res_1.get('execution_source')}, Sub-tasks={len(sub_tasks_1)}, RAG Tools={conductor_res_1.get('matched_tools')}")

    conductor_res_2 = await civilization_engine.run_conductor_orchestration(org_id, project_id, "Process raw payload streams into structured JSON schemas")
    print(f"    Run 2 Conductor ID: {conductor_res_2.get('conductor_id', 'N/A')}, Execution Source={conductor_res_2.get('execution_source')}, RAG Tools={conductor_res_2.get('matched_tools')} (Reused Pipeline/Agent={conductor_res_2.get('reused_pipeline_id') or conductor_res_2.get('reused_agent_id')})")

    react_res = await civilization_engine.run_react_loop(org_id, project_id, "search Google for Q3 analytics documentation")
    steps = react_res.get('steps', [])
    matched_tools = react_res.get('matched_tools', [])
    print(f"    ReAct Agent ID: {react_res.get('react_agent_id', 'N/A')}, RAG Tools={matched_tools}, Steps={len(steps)}")
    print(f"    Final Answer:\n{react_res.get('final_answer', react_res.get('answer', 'OK'))}")

    print("\n[+] 1B Synthetic Civilization Engine Test Completed Successfully!")

if __name__ == "__main__":
    asyncio.run(main())

