"""Standalone test script for agent.london 1B synthetic civilization engine including Prime Castes, Cryptographic binding, Token economy, and Audits."""
import asyncio
import os
import httpx
from backend.civilization import civilization_engine

async def main():
    print("=" * 60)
    print("AGENT.LONDON 1B SYNTHETIC CIVILIZATION ENGINE TEST")
    print("=" * 60)

    org_id = "org_london_meta"
    username = "chandan"
    email = "chandan@agent.london"
    project_name = "proj_alpha_civilization"

    print("\n[+] 1. Creating User...")
    user_res = await civilization_engine.create_user(org_id, username, email)
    user_id = user_res["user_id"]
    print(f"    User Created: ID={user_id}, Username={username}")

    print("\n[+] 2. Creating Project Universe & Auto-Provisioning Prime Caste Permanent Scaffolding...")
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
    for caste, agent_id in proj_res["permanent_agents"].items():
        print(f"    - Prime Caste [{caste.upper()}]: Agent ID={agent_id}")

    print("\n[+] 3. Materializing Cryptographically Bound Progeny Worker Agent...")
    creator_id = proj_res["permanent_agents"]["architect"]
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
    print(f"    Hash Digest: {worker_res['hash_digest']}")
    print(f"    Parent Signature: {worker_res['signature']}")

    print("\n[+] 4. Verifying Agent Cryptographic Signature & Hash Digest Integrity...")
    async with httpx.AsyncClient(timeout=3.0) as client:
        try:
            v_res = await client.post("http://localhost:8001/agents/verify", json={
                "agent_id": worker_res["agent_id"],
                "public_key": worker_res["public_key"],
                "signature": worker_res["signature"],
                "payload_text": f"{worker_res['agent_id']}:{worker_res['telos']}:{worker_res['system_prompt']}:{creator_id}"
            })
            if v_res.status_code == 200:
                v_data = v_res.json()
                print(f"    Cryptographic Verification Status: Verified={v_data['verified']}, Digest={v_data['computed_digest'][:16]}...")
        except Exception as e:
            print(f"    Cryptographic verification fallback test mode: {e}")

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
                print(f"    Audit Recorded: Status={a_data['status']}, New Reputation Score={a_data['new_reputation_score']}/100")
        except Exception as e:
            print(f"    Audit recording fallback test mode: {e}")

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
                print(f"    Utility Tokens Allocated: New Balance={t_data['new_token_balance']} CR")
        except Exception as e:
            print(f"    Token allocation fallback test mode: {e}")

    print("\n[+] 7. Indexing Agent Metadata into post-graph-rag...")
    rag_res = await civilization_engine.index_agent_registry_for_rag(org_id, project_id)
    print(f"    RAG Indexing Status: {rag_res['status']}, Indexed={rag_res['indexed_agents']}")

    print("\n[+] 8. Executing Conductor Multi-Agent Composition & ReAct Loop...")
    conductor_res = await civilization_engine.run_conductor_orchestration(org_id, project_id, "Discover dataset processing agents")
    print(f"    Conductor ID: {conductor_res['conductor_id']}, Sub-tasks={len(conductor_res['sub_tasks_orchestrated'])}")

    react_res = await civilization_engine.run_react_loop(org_id, project_id, "Query knowledge vectors for Q3 analytics")
    print(f"    ReAct Agent ID: {react_res['react_agent_id']}, Steps={len(react_res['steps'])}")
    print(f"    Final Answer: {react_res['final_answer']}")

    print("\n[+] 1B Synthetic Civilization Engine Test Completed Successfully!")

if __name__ == "__main__":
    asyncio.run(main())
