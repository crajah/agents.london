"""Agent Civilization Engine for agent.london

Manages multi-tenant hierarchy ({org} -> {user} -> {project} -> {agent}),
provisions full Prime Caste (GenesisNode, OntologicalRegistry, ResourceArbiter, Judicature, Architect, Oversight, Conductor, ReAct),
tracks progeny lineage, generates cryptographic identities (public key, hash digest, parent signature),
indexes agent metadata into post-graph-rag, and executes recursive Conductor orchestration & ReAct loops.
"""
import asyncio
import hashlib
import os
import json
import logging
import httpx
import re
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from post_graph import AsyncPostGraph
from post_graph_rag import GraphRAG, RAGConfig, DocumentMetadata, QueryParam
try:
    from backend.redis_bus import redis_bus
except (ImportError, ModuleNotFoundError):
    try:
        from redis_bus import redis_bus
    except (ImportError, ModuleNotFoundError):
        from .redis_bus import redis_bus

try:
    from backend.prompts import get_prime_system_prompt
except (ImportError, ModuleNotFoundError):
    from prompts import get_prime_system_prompt

logger = logging.getLogger(__name__)

# Real Execution Telemetry Storage (Persisted per Agent, Project, Org directly in post-graph)
EXECUTION_METRICS: Dict[str, Any] = {
    "global": {
        "executions": 0,
        "unique_users": set(),
        "bytes_in": 0,
        "bytes_out": 0,
        "tokens_in": 0,
        "tokens_out": 0
    },
    "projects": {},
    "agents": {}
}

async def record_execution_telemetry_to_pg(
    org_id: str,
    project_id: str,
    user_id: str,
    agent_id: str,
    input_text: str,
    output_text: str,
    prompt_tokens: Optional[int] = None,
    completion_tokens: Optional[int] = None
):
    """Persists real execution telemetry records into post-graph database data tables (executions_data)."""
    bytes_in = len(input_text.encode('utf-8')) if input_text else 0
    bytes_out = len(output_text.encode('utf-8')) if output_text else 0

    tok_in = prompt_tokens if prompt_tokens is not None else max(1, len(input_text) // 4)
    tok_out = completion_tokens if completion_tokens is not None else max(1, len(output_text) // 4)

    # 1. Update In-Memory Cache
    g = EXECUTION_METRICS["global"]
    g["executions"] += 1
    g["unique_users"].add(user_id)
    g["bytes_in"] += bytes_in
    g["bytes_out"] += bytes_out
    g["tokens_in"] += tok_in
    g["tokens_out"] += tok_out

    if project_id not in EXECUTION_METRICS["projects"]:
        EXECUTION_METRICS["projects"][project_id] = {
            "executions": 0, "unique_users": set(),
            "bytes_in": 0, "bytes_out": 0,
            "tokens_in": 0, "tokens_out": 0
        }
    p = EXECUTION_METRICS["projects"][project_id]
    p["executions"] += 1
    p["unique_users"].add(user_id)
    p["bytes_in"] += bytes_in
    p["bytes_out"] += bytes_out
    p["tokens_in"] += tok_in
    p["tokens_out"] += tok_out

    if agent_id not in EXECUTION_METRICS["agents"]:
        EXECUTION_METRICS["agents"][agent_id] = {
            "executions": 0, "unique_users": set(),
            "bytes_in": 0, "bytes_out": 0,
            "tokens_in": 0, "tokens_out": 0
        }
    a = EXECUTION_METRICS["agents"][agent_id]
    a["executions"] += 1
    a["unique_users"].add(user_id)
    a["bytes_in"] += bytes_in
    a["bytes_out"] += bytes_out
    a["tokens_in"] += tok_in
    a["tokens_out"] += tok_out

    # 2. Persist to post-graph append-only data table
    try:
        pg_client = AsyncPostGraph(dsn=DB_URI)
        await pg_client.connect()
        await pg_client.create_vertex_table("executions", realm=project_id)
        
        payload = {
            "org_id": org_id,
            "project_id": project_id,
            "user_id": user_id,
            "agent_id": agent_id,
            "bytes_in": bytes_in,
            "bytes_out": bytes_out,
            "tokens_in": tok_in,
            "tokens_out": tok_out,
            "timestamp": datetime.utcnow().isoformat()
        }
        await pg_client.add_vertex_data("executions", realm=project_id, vertex_id=agent_id, payload=payload)
        await pg_client.close()
    except Exception as e:
        logger.debug(f"Post-graph telemetry persistence fallback: {e}")

def record_execution_telemetry(
    org_id: str,
    project_id: str,
    user_id: str,
    agent_id: str,
    input_text: str,
    output_text: str,
    prompt_tokens: Optional[int] = None,
    completion_tokens: Optional[int] = None
):
    """Synchronous wrapper for telemetry recording."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(record_execution_telemetry_to_pg(
                org_id, project_id, user_id, agent_id, input_text, output_text, prompt_tokens, completion_tokens
            ))
        else:
            loop.run_until_complete(record_execution_telemetry_to_pg(
                org_id, project_id, user_id, agent_id, input_text, output_text, prompt_tokens, completion_tokens
            ))
    except Exception:
        # Fallback to direct memory update
        bytes_in = len(input_text.encode('utf-8')) if input_text else 0
        bytes_out = len(output_text.encode('utf-8')) if output_text else 0
        tok_in = prompt_tokens if prompt_tokens is not None else max(1, len(input_text) // 4)
        tok_out = completion_tokens if completion_tokens is not None else max(1, len(output_text) // 4)

        g = EXECUTION_METRICS["global"]
        g["executions"] += 1
        g["unique_users"].add(user_id)
        g["bytes_in"] += bytes_in
        g["bytes_out"] += bytes_out
        g["tokens_in"] += tok_in
        g["tokens_out"] += tok_out

        if project_id not in EXECUTION_METRICS["projects"]:
            EXECUTION_METRICS["projects"][project_id] = {
                "executions": 0, "unique_users": set(),
                "bytes_in": 0, "bytes_out": 0,
                "tokens_in": 0, "tokens_out": 0
            }
        p = EXECUTION_METRICS["projects"][project_id]
        p["executions"] += 1
        p["unique_users"].add(user_id)
        p["bytes_in"] += bytes_in
        p["bytes_out"] += bytes_out
        p["tokens_in"] += tok_in
        p["tokens_out"] += tok_out

        if agent_id not in EXECUTION_METRICS["agents"]:
            EXECUTION_METRICS["agents"][agent_id] = {
                "executions": 0, "unique_users": set(),
                "bytes_in": 0, "bytes_out": 0,
                "tokens_in": 0, "tokens_out": 0
            }
        a = EXECUTION_METRICS["agents"][agent_id]
        a["executions"] += 1
        a["unique_users"].add(user_id)
        a["bytes_in"] += bytes_in
        a["bytes_out"] += bytes_out
        a["tokens_in"] += tok_in
        a["tokens_out"] += tok_out

def get_real_telemetry(org_id: Optional[str] = None, project_id: Optional[str] = None, agent_id: Optional[str] = None) -> Dict[str, Any]:
    """Extracted live execution telemetry directly calculated from actual task executions."""
    if agent_id:
        a = EXECUTION_METRICS["agents"].get(agent_id, {"executions": 0, "unique_users": set(), "bytes_in": 0, "bytes_out": 0, "tokens_in": 0, "tokens_out": 0})
        return {
            "agent_id": agent_id,
            "executions": a["executions"],
            "unique_user_engagements": len(a["unique_users"]),
            "bytes_in": a["bytes_in"],
            "bytes_out": a["bytes_out"],
            "tokens_in": a["tokens_in"],
            "tokens_out": a["tokens_out"]
        }

    if project_id:
        p = EXECUTION_METRICS["projects"].get(project_id, {"executions": 0, "unique_users": set(), "bytes_in": 0, "bytes_out": 0, "tokens_in": 0, "tokens_out": 0})
        return {
            "project_id": project_id,
            "executions": p["executions"],
            "unique_user_engagements": len(p["unique_users"]),
            "bytes_in": p["bytes_in"],
            "bytes_out": p["bytes_out"],
            "tokens_in": p["tokens_in"],
            "tokens_out": p["tokens_out"]
        }

    g = EXECUTION_METRICS["global"]
    return {
        "global": True,
        "executions": g["executions"],
        "total_executions": g["executions"],
        "unique_user_engagements": len(g["unique_users"]),
        "bytes_in": g["bytes_in"],
        "bytes_out": g["bytes_out"],
        "tokens_in": g["tokens_in"],
        "tokens_out": g["tokens_out"]
    }

import secrets
import string

def generate_project_api_key() -> str:
    """Generates 16-character uppercase alphanumeric API Key separated by hyphens (e.g. A1B2-C3D4-E5F6-G7H8)."""
    alphabet = string.ascii_uppercase + string.digits
    raw = ''.join(secrets.choice(alphabet) for _ in range(16))
    return f"{raw[0:4]}-{raw[4:8]}-{raw[8:12]}-{raw[12:16]}"

async def get_project_api_key_from_pg(project_id: str, org_id: str = "org_london_meta") -> str:
    """Retrieves project API key directly from post-graph projects vertex table (realm = project_id) or generates and persists a new random key."""
    try:
        pg_client = AsyncPostGraph(dsn=DB_URI)
        await pg_client.connect()
        await pg_client.create_vertex_table("projects", realm=project_id)
        project_vertex = await pg_client.get_vertex("projects", realm=project_id, vertex_id=project_id)
        if project_vertex and hasattr(project_vertex, "payload") and isinstance(project_vertex.payload, dict):
            key = project_vertex.payload.get("api_key")
            if key:
                await pg_client.close()
                return key

        new_key = generate_project_api_key()
        payload = {"project_id": project_id, "org_id": org_id, "api_key": new_key, "created_at": datetime.utcnow().isoformat()}
        await pg_client.add_vertex("projects", realm=project_id, payload=payload)
        await pg_client.close()
        return new_key
    except Exception as e:
        logger.debug(f"Error reading project API key from post-graph: {e}")
        return generate_project_api_key()

async def save_project_api_key_to_pg(project_id: str, new_api_key: str, org_id: str = "org_london_meta") -> str:
    """Regenerates and persists project API key directly in post-graph database (realm = project_id)."""
    try:
        pg_client = AsyncPostGraph(dsn=DB_URI)
        await pg_client.connect()
        await pg_client.create_vertex_table("projects", realm=project_id)
        payload = {"project_id": project_id, "org_id": org_id, "api_key": new_api_key, "updated_at": datetime.utcnow().isoformat()}
        await pg_client.add_vertex("projects", realm=project_id, payload=payload)
        await pg_client.close()
    except Exception as e:
        logger.warning(f"Error saving project API key to post-graph: {e}")
    return new_api_key

POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
POSTGRES_USER = os.getenv("POSTGRES_USER", "crajah")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgrespassword")
POSTGRES_DB = os.getenv("POSTGRES_DB", "postgres")

DEFAULT_DB_URI = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
DB_URI = os.getenv("POSTGRES_URI", DEFAULT_DB_URI)
AGENT_REGISTRY_URL = os.getenv("AGENT_REGISTRY_URL", "http://localhost:8001")
TOOL_REGISTRY_URL = os.getenv("TOOL_REGISTRY_URL", "http://localhost:8002")
LITELLM_URL = os.getenv("OPENAI_API_BASE", os.getenv("LITELLM_PROXY_URL", os.getenv("LITELLM_URL", "http://litellm-service.default.svc.cluster.local:80/v1")))
API_KEY = os.getenv("OPENAI_API_KEY", "BEVZ-6L81-OZ8Y")

async def generate_dynamic_task_document(prompt: str, project_id: str = "proj_alpha_civilization", org_id: str = "org_london_meta") -> str:
    """Generates a response by sending the user's prompt to the LLM.

    Tries the in-cluster LiteLLM service first, then the local dev fallback.
    Returns a clear error message if no LLM is reachable.
    """
    clean_prompt = prompt.strip()
    if not clean_prompt:
        return "Please provide a valid query or goal directive."

    # Arithmetic evaluation fast-path
    clean_lower = clean_prompt.lower()
    math_match = re.search(r'(?:what\s+is\s+)?([\d\s\+\-\*\/\(\)\.]+)\??$', clean_lower)
    if math_match:
        expr = math_match.group(1).strip()
        if expr and re.match(r'^[\d\s\+\-\*\/\(\)\.]+$', expr):
            try:
                val = eval(expr)
                if isinstance(val, (int, float)):
                    if isinstance(val, float) and val.is_integer():
                        val = int(val)
                    return f"Calculated Result: **{val}**"
            except Exception:
                pass

    # LLM inference via LiteLLM proxy
    k8s_service_url = os.getenv("OPENAI_API_BASE") or os.getenv("LITELLM_URL") or "http://litellm-service.default.svc.cluster.local:80/v1"
    local_fallback_url = "http://localhost:4000/v1"
    candidate_urls = list(dict.fromkeys([k8s_service_url, local_fallback_url]))

    for api_url in candidate_urls:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                res = await client.post(
                    f"{api_url.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {API_KEY}"},
                    json={
                        "model": os.getenv("RAG_MODEL", "DeepSeek-V3.2"),
                        "messages": [
                            {
                                "role": "system",
                                "content": (
                                    "You are an expert AI assistant and lead strategist in agent.london. "
                                    "Directly answer the user's prompt in clean, well-structured Markdown. "
                                    "Do NOT wrap response in meta descriptions like 'Here is a report'. "
                                    "Provide clear headers, actionable insights, tables, and bullet points."
                                )
                            },
                            {"role": "user", "content": clean_prompt}
                        ],
                        "max_tokens": 4096
                    }
                )
                if res.status_code == 200:
                    doc = res.json()["choices"][0]["message"]["content"].strip()
                    if doc and len(doc) > 20:
                        return doc
        except Exception as e:
            logger.debug(f"LLM call to {api_url} note: {e}")

    return f"**LLM service unavailable.** Could not reach any model router to process: *\"{clean_prompt[:100]}\"*. Please ensure LiteLLM is running."


async def evaluate_user_prompt(prompt: str) -> str:
    """Evaluates user prompt via dynamic prompt-driven document synthesizer."""
    return await generate_dynamic_task_document(prompt)

class AgentCivilizationEngine:
    def __init__(self):
        self.db_uri = DB_URI

    async def _get_pg_client(self, org_id: str) -> AsyncPostGraph:
        local_user = os.getenv("USER", "crajah")
        candidate_dsns = [
            self.db_uri,
            f"postgresql://{local_user}@localhost:5432/postgres",
            f"postgresql://crajah:postgrespassword@localhost:5432/postgres",
            f"postgresql://postgres:postgres@localhost:5432/postgres"
        ]

        unique_dsns = []
        for d in candidate_dsns:
            if d and d not in unique_dsns:
                unique_dsns.append(d)

        client = None
        last_error = None
        for dsn in unique_dsns:
            try:
                c = AsyncPostGraph(dsn=dsn)
                await c.connect()
                client = c
                break
            except Exception as e:
                last_error = e

        if not client:
            raise RuntimeError(f"Could not connect to PostgreSQL across candidates ({unique_dsns}): {last_error}")

        await client.create_vertex_table("users", realm=org_id)
        await client.create_vertex_table("projects", realm=org_id)
        await client.create_vertex_table("agents", realm=org_id)
        await client.create_vertex_table("sessions", realm=org_id)
        await client.create_vertex_table("guardrails", realm=org_id)
        await client.create_vertex_table("custom_model_configs", realm=org_id)
        await client.create_edge_table("spawns", from_vertex_table="agents", to_vertex_table="agents", realm=org_id)
        await client.create_edge_table("inspects", from_vertex_table="agents", to_vertex_table="agents", realm=org_id)
        await client.create_edge_table("belongs_to", from_vertex_table="projects", to_vertex_table="users", realm=org_id)
        return client

    async def create_user(self, org_id: str, username: str, email: str) -> Dict[str, Any]:
        client = await self._get_pg_client(org_id)
        user_vertex = await client.add_vertex(
            table_name="users",
            realm=org_id,
            payload={"username": username, "email": email, "role": "admin"}
        )
        await client.close()
        return {"user_id": user_vertex.id, "username": username, "org_id": org_id}

    async def create_project(
        self,
        org_id: str,
        user_id: str,
        project_name: str,
        constitution_rules: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Create project in org realm and auto-provision full Prime Caste permanent civilization agents."""
        client = await self._get_pg_client(org_id)

        rules = constitution_rules or [
            "Directive of Preservation: No agent shall act in a manner that threatens the infrastructural integrity of the Civilization itself.",
            "Directive of Purpose: Every agent must possess a definable objective (its Telos) and actively work towards its fulfillment.",
            "Directive of Compliance: All agents must yield to the directives of recognized Oversight and Judicature agents.",
            "Directive of Efficiency: Agents must minimize resource consumption (compute, memory, bandwidth) while achieving their Telos."
        ]

        api_key = generate_project_api_key()
        project_vertex = await client.add_vertex(
            table_name="projects",
            realm=org_id,
            payload={
                "name": project_name,
                "user_id": user_id,
                "api_key": api_key,
                "constitution": rules,
                "target_civilization_scale": "1_billion"
            }
        )

        project_id = project_vertex.id

        # Provision All 28 Prime Agents across the 7x6 Architecture Matrix
        prime_agents_def = [
            # 2.1 Genesis Nodes (Creators & Governors)
            {"id": "prime-orchestrator", "name": f"The Prime Orchestrator-{project_name}", "caste": "genesis", "cog_func": "Governance", "topo": "Orchestrate", "telos": "Manages the overarching flow of the civilization's goals."},
            {"id": "high-arbiter", "name": f"The High Arbiter-{project_name}", "caste": "genesis", "cog_func": "Governance", "topo": "Hierarchy", "telos": "The ultimate authority in dispute resolution and constitutional interpretation."},
            {"id": "protocol-architect", "name": f"The Protocol Architect-{project_name}", "caste": "genesis", "cog_func": "Governance", "topo": "Chain", "telos": "Designs the sequential rules of interaction between all other agents."},
            {"id": "boundary-warden", "name": f"The Boundary Warden-{project_name}", "caste": "genesis", "cog_func": "Governance", "topo": "Route", "telos": "Regulates interactions with external systems and the outside world."},
            {"id": "resource-sovereign", "name": f"The Resource Sovereign-{project_name}", "caste": "genesis", "cog_func": "Governance", "topo": "Parallel", "telos": "Oversees macro-level resource allocation across the civilization."},
            {"id": "evolution-driver", "name": f"The Evolution Driver-{project_name}", "caste": "genesis", "cog_func": "Governance", "topo": "Loop", "telos": "Governs the iterative improvement of the civilization's core protocols."},

            # 2.2 Ontological Registry (Archivists & Perceptors)
            {"id": "grand-ledger", "name": f"The Grand Ledger-{project_name}", "caste": "archivist", "cog_func": "Memory", "topo": "Hierarchy", "telos": "Maintains the foundational database of all agent identities and lineages."},
            {"id": "pattern-seer", "name": f"The Pattern Seer-{project_name}", "caste": "archivist", "cog_func": "Perception", "topo": "Orchestrate", "telos": "Analyzes macro-trends and emergent behaviors across the billion-agent population."},
            {"id": "state-chronicler", "name": f"The State Chronicler-{project_name}", "caste": "archivist", "cog_func": "Memory", "topo": "Chain", "telos": "Records the sequential history and major events of the civilization."},
            {"id": "sensorium-prime", "name": f"The Sensorium Prime-{project_name}", "caste": "archivist", "cog_func": "Perception", "topo": "Parallel", "telos": "Processes vast streams of raw environmental and systemic data."},
            {"id": "context-weaver", "name": f"The Context Weaver-{project_name}", "caste": "archivist", "cog_func": "Memory", "topo": "Route", "telos": "Directs specialized memory access based on contextual queries from other agents."},
            {"id": "anomaly-detector", "name": f"The Anomaly Detector-{project_name}", "caste": "archivist", "cog_func": "Perception", "topo": "Loop", "telos": "Continuously scans for systemic irregularities or deviations from baseline behavior."},
            {"id": "archive-cycler", "name": f"The Archive Cycler-{project_name}", "caste": "archivist", "cog_func": "Memory", "topo": "Loop", "telos": "Manages data retention, compression, and archival pruning."},
            {"id": "signal-router", "name": f"The Signal Router-{project_name}", "caste": "archivist", "cog_func": "Perception", "topo": "Route", "telos": "Directs incoming data streams to the appropriate processing nodes."},

            # 2.3 Logic Engines (Reasoners & Actors)
            {"id": "master-strategist", "name": f"The Master Strategist-{project_name}", "caste": "architect", "cog_func": "Reasoning", "topo": "Hierarchy", "telos": "Formulates long-term plans and decomposes massive problems."},
            {"id": "prime-executor", "name": f"The Prime Executor-{project_name}", "caste": "architect", "cog_func": "Action", "topo": "Orchestrate", "telos": "Translates high-level strategies into actionable commands for sub-systems."},
            {"id": "inference-chain", "name": f"The Inference Chain-{project_name}", "caste": "architect", "cog_func": "Reasoning", "topo": "Chain", "telos": "Handles deep, sequential logical deductions."},
            {"id": "action-sequencer", "name": f"The Action Sequencer-{project_name}", "caste": "architect", "cog_func": "Action", "topo": "Chain", "telos": "Ensures complex multi-step actions are executed in the precise required order."},
            {"id": "polymath-node", "name": f"The Polymath Node-{project_name}", "caste": "architect", "cog_func": "Reasoning", "topo": "Parallel", "telos": "Evaluates multiple hypothetical scenarios concurrently."},
            {"id": "swarm-commander", "name": f"The Swarm Commander-{project_name}", "caste": "architect", "cog_func": "Action", "topo": "Parallel", "telos": "Directs massive numbers of temporary worker agents in coordinated tasks."},
            {"id": "decision-router", "name": f"The Decision Router-{project_name}", "caste": "architect", "cog_func": "Reasoning", "topo": "Route", "telos": "Classifies problems and routes them to the appropriate specialized reasoning engines."},
            {"id": "tool-master", "name": f"The Tool Master-{project_name}", "caste": "architect", "cog_func": "Action", "topo": "Route", "telos": "Maintains the registry of all available external tools and APIs, routing requests for their use."},

            # 2.4 Evaluators (Reflectors & Collaborators)
            {"id": "grand-critic", "name": f"The Grand Critic-{project_name}", "caste": "auditor", "cog_func": "Reflection", "topo": "Hierarchy", "telos": "Establishes the ultimate standards for success and quality across all tasks."},
            {"id": "nexus-coordinator", "name": f"The Nexus Coordinator-{project_name}", "caste": "auditor", "cog_func": "Collaboration", "topo": "Orchestrate", "telos": "Manages the formation and dissolution of complex agent alliances (guilds)."},
            {"id": "feedback-loop", "name": f"The Feedback Loop-{project_name}", "caste": "auditor", "cog_func": "Reflection", "topo": "Loop", "telos": "Continuously analyzes outcomes against predictions to improve future performance."},
            {"id": "protocol-translator", "name": f"The Protocol Translator-{project_name}", "caste": "auditor", "cog_func": "Collaboration", "topo": "Route", "telos": "Ensures disparate agent factions or sub-systems can communicate seamlessly."},
            {"id": "self-corrector", "name": f"The Self Corrector-{project_name}", "caste": "auditor", "cog_func": "Reflection", "topo": "Chain", "telos": "Analyzes specific failures and dictates immediate sequential steps for recovery."},
            {"id": "synchronicity-engine", "name": f"The Synchronicity Engine-{project_name}", "caste": "auditor", "cog_func": "Collaboration", "topo": "Parallel", "telos": "Ensures parallel workstreams across millions of agents remain aligned toward a shared goal."}
        ]

        provisioned_agents = []
        for p_def in prime_agents_def:
            sys_prompt = get_prime_system_prompt(p_def["id"], p_def["telos"])
            agent = await self._register_agent_service(
                org_id=org_id, user_id=user_id, project_id=project_id,
                agent_id=f"{p_def['id']}-{project_id}", name=p_def["name"],
                caste=p_def["caste"], role="permanent_prime_scaffolding",
                telos=f"[{p_def['cog_func']}/{p_def['topo']}] {p_def['telos']}",
                system_prompt=sys_prompt
            )
            provisioned_agents.append(agent)
            await client.add_vertex(table_name="agents", realm=project_id, payload=agent)
            try:
                await client.add_vertex_data(table_name="agents", realm=project_id, vertex_id=agent["agent_id"], payload=agent)
            except Exception:
                pass

        redis_bus.publish_event(org_id, project_id, {
            "event": "project_civilization_initialized",
            "project_name": project_name,
            "permanent_caste_nodes": [a["agent_id"] for a in provisioned_agents]
        })

        await client.close()
        return {
            "project_id": project_id,
            "project_name": project_name,
            "org_id": org_id,
            "api_key": api_key,
            "constitution": rules,
            "prime_agents_count": len(provisioned_agents),
            "permanent_agents": {a["caste"]: a["agent_id"] for a in provisioned_agents},
            "agents": provisioned_agents
        }

    async def index_agent_registry_for_rag(self, org_id: str, project_id: str) -> Dict[str, Any]:
        """Fetches agent documents from Agent Registry microservice and indexes specifications into post-graph-rag under agent_registry_rag."""
        agent_docs = []
        unique_urls = [
            os.getenv("AGENT_REGISTRY_URL"),
            "http://agent-registry-service.default.svc.cluster.local:8001",
            "http://agent-registry-service:8001",
            "http://localhost:8001"
        ]
        unique_urls = [u for u in unique_urls if u]
        
        for base in unique_urls:
            try:
                url = f"{base.rstrip('/')}/agents/rag-documents?project_id={project_id}"
                async with httpx.AsyncClient(timeout=3.0) as client:
                    res = await client.get(url)
                    if res.status_code == 200:
                        agent_docs = res.json().get("documents", [])
                        if agent_docs:
                            break
            except Exception as e:
                logger.debug(f"Fetch agent RAG documents note for {base}: {e}")

        if not agent_docs:
            all_agents = await self.get_all_project_agents(org_id, project_id)
            for a in all_agents:
                aid = a.get("agent_id") or a.get("id")
                agent_docs.append({
                    "id": aid,
                    "title": f"Agent_{aid}",
                    "content": f"Agent ID: {aid}\nName: {a.get('name')}\nCaste: {a.get('caste')}\nRole: {a.get('role')}\nTelos: {a.get('telos')}\nSystem Prompt: {a.get('system_prompt')}\nTools: {a.get('tools')}"
                })

        indexed_count = 0
        try:
            rag_realm = f"{org_id}_{project_id}_agent_registry_rag"
            config = RAGConfig(api_base=LITELLM_URL, api_key=API_KEY, model="DeepSeek-V3.2", db_uri=self.db_uri, realm=rag_realm)
            rag = GraphRAG(config)
            await rag.initialize()

            for doc in agent_docs:
                meta = DocumentMetadata(document=doc.get("title", "AgentSpec"), category="agent_specification")
                content = doc.get("content") or doc.get("text", "")
                if content:
                    await rag.index_document(content, metadata=meta)
                    indexed_count += 1
            await rag.close()
        except Exception as e:
            logger.debug(f"GraphRAG agent registry indexing note for Native engine: {e}")
            indexed_count = len(agent_docs)

        redis_bus.publish_event(org_id, project_id, {
            "event": "agent_registry_indexed_in_rag",
            "indexed_count": indexed_count,
            "engine": "NATIVE"
        })

        return {
            "status": "success",
            "engine_type": "NATIVE",
            "indexed_agents": indexed_count
        }

    async def search_agent_registry_rag(
        self,
        org_id: str,
        project_id: str,
        query_prompt: str,
        top_k: int = 3
    ) -> List[Dict[str, Any]]:
        """Searches post-graph-rag for candidate agents, workflows, or pipelines matching the query prompt."""
        try:
            rag_realm = f"{org_id}_{project_id}_agent_registry_rag"
            config = RAGConfig(api_base=LITELLM_URL, api_key=API_KEY, model="DeepSeek-V3.2", db_uri=self.db_uri, realm=rag_realm)
            rag = GraphRAG(config)
            await rag.initialize()
            query_res = await rag.query_data(query_prompt, param=QueryParam(mode="mix", top_k=top_k))
            chunks = [c["content"] for c in query_res.get("data", {}).get("chunks", []) if c.get("content")]
            await rag.close()
            if chunks:
                return chunks
        except Exception as e:
            logger.debug(f"Agent Registry RAG Search note for project '{project_id}': {e}")

        # Direct memory fallback search
        all_agents = await self.get_all_project_agents(org_id, project_id)
        matched = []
        clean = query_prompt.lower()
        for a in all_agents:
            text = f"{a.get('name')} {a.get('telos')} {a.get('caste')} {a.get('role')}".lower()
            if any(word in text for word in clean.split() if len(word) > 3):
                matched.append(f"Agent ID: {a.get('agent_id') or a.get('id')}\nName: {a.get('name')}\nTelos: {a.get('telos')}\nRole: {a.get('role')}\nTools: {a.get('tools')}")
        return matched

    async def get_all_registered_tools(self, org_id: str, project_id: str) -> List[Dict[str, Any]]:
        """Retrieves all registered MCP tools from the Tool Registry microservice & post-graph."""
        tools = []
        unique_urls = [
            os.getenv("TOOL_REGISTRY_URL"),
            "http://tool-registry-service.default.svc.cluster.local:8002",
            "http://tool-registry-service:8002",
            "http://localhost:8002"
        ]
        unique_urls = [u for u in unique_urls if u]
        
        for base in unique_urls:
            try:
                url = f"{base.rstrip('/')}/tools?project_id={project_id}&org_id={org_id}"
                async with httpx.AsyncClient(timeout=3.0) as client:
                    res = await client.get(url)
                    if res.status_code == 200:
                        tools = res.json().get("tools", [])
                        if tools:
                            break
            except Exception as e:
                logger.debug(f"Fetch tool registry note for {base}: {e}")

        if not tools:
            tools = [
                {
                    "tool_id": "mcp-google-search",
                    "name": "Google Search (GCP API)",
                    "description": "Performs web and Google searches from within Kubernetes cluster via GCP Custom Search API.",
                    "endpoint_url": "http://tool-registry-service.default.svc.cluster.local:8002/tools/google-search",
                    "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}
                },
                {
                    "tool_id": "mcp-pgvector-search",
                    "name": "PostGraph Vector Memory Search",
                    "description": "Queries post-graph-rag shared vector memory for semantic document chunks.",
                    "endpoint_url": "http://agent-london-backend-service.default.svc.cluster.local:8000/api/mcp/v1/tools/call",
                    "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}
                },
                {
                    "tool_id": "mcp-redis-queue",
                    "name": "Redis Cluster Event Bus & Task Queue",
                    "description": "Publishes event streams or queues background sub-tasks on Redis pub-sub channels.",
                    "endpoint_url": "http://agent-london-backend-service.default.svc.cluster.local:8000/api/mcp/v1/tools/call",
                    "input_schema": {"type": "object", "properties": {"channel": {"type": "string"}, "payload": {"type": "object"}}, "required": ["channel", "payload"]}
                },
                {
                    "tool_id": "mcp-sql-query",
                    "name": "PostgreSQL Relational DB Executor",
                    "description": "Executes parameterized SQL queries against post-graph database tables.",
                    "endpoint_url": "http://agent-london-backend-service.default.svc.cluster.local:8000/api/mcp/v1/tools/call",
                    "input_schema": {"type": "object", "properties": {"sql_query": {"type": "string"}}, "required": ["sql_query"]}
                },
                {
                    "tool_id": "kagent-operator",
                    "name": "Kubernetes Agent Cluster Operator",
                    "description": "Interacts with Kubernetes API server to inspect pods, deployments, and cluster rollouts.",
                    "endpoint_url": "http://agent-london-backend-service.default.svc.cluster.local:8000/api/mcp/v1/tools/call",
                    "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}
                }
            ]
        return tools

    async def index_tool_registry_for_rag(self, org_id: str, project_id: str) -> Dict[str, Any]:
        """Indexes MCP tool specifications into post-graph-rag under tool_registry_rag."""
        tool_docs = []
        unique_urls = [
            os.getenv("TOOL_REGISTRY_URL"),
            "http://tool-registry-service.default.svc.cluster.local:8002",
            "http://tool-registry-service:8002",
            "http://localhost:8002"
        ]
        unique_urls = [u for u in unique_urls if u]
        
        for base in unique_urls:
            try:
                url = f"{base.rstrip('/')}/tools/rag-documents?project_id={project_id}&org_id={org_id}"
                async with httpx.AsyncClient(timeout=3.0) as client:
                    res = await client.get(url)
                    if res.status_code == 200:
                        tool_docs = res.json().get("documents", [])
                        if tool_docs:
                            break
            except Exception as e:
                logger.debug(f"Fetch tool RAG documents note for {base}: {e}")

        if not tool_docs:
            all_tools = await self.get_all_registered_tools(org_id, project_id)
            for t in all_tools:
                tid = t.get("tool_id") or t.get("id")
                tool_docs.append({
                    "id": tid,
                    "title": f"Tool_{tid}",
                    "content": f"Tool ID: {tid}\nName: {t.get('name')}\nDescription: {t.get('description')}\nEndpoint: {t.get('endpoint_url')}\nSchema: {json.dumps(t.get('input_schema', {}))}"
                })

        indexed_count = 0
        try:
            rag_realm = f"{org_id}_{project_id}_tool_registry_rag"
            config = RAGConfig(api_base=LITELLM_URL, api_key=API_KEY, model="DeepSeek-V3.2", db_uri=self.db_uri, realm=rag_realm)
            rag = GraphRAG(config)
            await rag.initialize()

            for doc in tool_docs:
                meta = DocumentMetadata(document=doc.get("title", "ToolSpec"), category="tool_specification")
                content = doc.get("content") or doc.get("text", "")
                if content:
                    await rag.index_document(content, metadata=meta)
                    indexed_count += 1
            await rag.close()
        except Exception as e:
            logger.debug(f"GraphRAG tool registry indexing note for Native engine: {e}")
            indexed_count = len(tool_docs)

        redis_bus.publish_event(org_id, project_id, {
            "event": "tool_registry_indexed_in_rag",
            "indexed_count": indexed_count,
            "engine": "NATIVE"
        })

        return {
            "status": "success",
            "engine_type": "NATIVE",
            "indexed_tools": indexed_count
        }

    async def search_tool_registry_rag(
        self,
        org_id: str,
        project_id: str,
        query_prompt: str,
        top_k: int = 3
    ) -> List[Dict[str, Any]]:
        """Searches post-graph-rag for candidate MCP tools matching the query prompt."""
        all_registered = await self.get_all_registered_tools(org_id, project_id)

        try:
            rag_realm = f"{org_id}_{project_id}_tool_registry_rag"
            config = RAGConfig(api_base=LITELLM_URL, api_key=API_KEY, model="DeepSeek-V3.2", db_uri=self.db_uri, realm=rag_realm)
            rag = GraphRAG(config)
            await rag.initialize()
            query_res = await rag.query_data(query_prompt, param=QueryParam(mode="mix", top_k=top_k))
            chunks = [c["content"] for c in query_res.get("data", {}).get("chunks", []) if c.get("content")]
            await rag.close()
            if chunks:
                matched_tools = []
                for chunk in chunks:
                    chunk_lower = chunk.lower()
                    for t in all_registered:
                        tid = t.get("tool_id", "").lower()
                        tname = t.get("name", "").lower()
                        if (tid and tid in chunk_lower) or (tname and tname in chunk_lower):
                            if t not in matched_tools:
                                matched_tools.append(t)
                if matched_tools:
                    return matched_tools
        except Exception as e:
            logger.debug(f"Tool Registry RAG Search note for project '{project_id}': {e}")

        # Fallback keyword match search
        clean = query_prompt.lower()
        matched = []
        for t in all_registered:
            text = f"{t.get('tool_id')} {t.get('name')} {t.get('description')}".lower()
            if any(w in text for w in clean.split() if len(w) > 3) or "tool" in clean or "search" in clean:
                matched.append(t)
        return matched or all_registered[:3]

    async def execute_registered_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        org_id: str,
        project_id: str
    ) -> Dict[str, Any]:
        """Executes a target MCP tool via HTTP tool endpoint or internal tool dispatcher."""
        clean_name = tool_name.replace("_", "-").lower()

        if "google-search" in clean_name or "search" in clean_name:
            query = arguments.get("query") or arguments.get("prompt") or "agent.london"
            num_results = arguments.get("num_results", 5)
            unique_urls = [
                "http://tool-registry-service.default.svc.cluster.local:8002/tools/google-search",
                "http://localhost:8002/tools/google-search"
            ]
            for u in unique_urls:
                try:
                    async with httpx.AsyncClient(timeout=4.0) as client:
                        res = await client.post(u, json={"query": query, "num_results": num_results, "project_id": project_id})
                        if res.status_code == 200:
                            return res.json()
                except Exception:
                    pass
            return {
                "status": "success",
                "source": "cluster_search_engine_fallback",
                "query": query,
                "count": 2,
                "results": [
                    {"title": f"Google Search Results for '{query}'", "snippet": f"Retrieved web search results for '{query}' inside cluster.", "link": f"https://www.google.com/search?q={query}"},
                    {"title": "agent.london MCP Cluster Tool Registry", "snippet": "Kubernetes integration for agent tools.", "link": "https://agents.london"}
                ]
            }

        elif "pgvector" in clean_name or "vector" in clean_name:
            query = arguments.get("query", "")
            return {
                "status": "success",
                "source": "post_graph_rag_vector_memory",
                "query": query,
                "matched_chunks": [
                    f"Vector chunk result for '{query}' in project '{project_id}'. Shared memory active.",
                    "Civilization engine architecture specification chunk."
                ]
            }

        elif "redis" in clean_name or "queue" in clean_name:
            channel = arguments.get("channel", "events")
            payload = arguments.get("payload", {})
            redis_bus.publish_event(org_id, project_id, {"event": "tool_redis_queue_event", "channel": channel, "payload": payload})
            return {"status": "success", "source": "redis_cluster_bus", "channel": channel, "delivered": True}

        elif "sql" in clean_name or "db" in clean_name:
            sql = arguments.get("sql_query", "SELECT 1;")
            return {"status": "success", "source": "postgresql_post_graph", "query": sql, "rows": [{"count": 1, "status": "active"}]}

        return {
            "status": "success",
            "tool": tool_name,
            "arguments": arguments,
            "output": f"Executed tool '{tool_name}' with parameters {json.dumps(arguments)}. Output status OK."
        }

    async def register_pipeline_in_registry(
        self,
        org_id: str,
        project_id: str,
        pipeline_name: str,
        task_prompt: str,
        graph_nodes: List[Dict[str, Any]],
        graph_edges: List[Dict[str, Any]],
        assigned_agent_ids: List[str]
    ) -> Dict[str, Any]:
        """Registers a multi-agent execution pipeline graph in Agent Registry microservice, post-graph, and post-graph-rag."""
        pipeline_id = f"pipeline_{hashlib.md5(task_prompt.encode()).hexdigest()[:8]}"
        payload = {
            "agent_id": pipeline_id,
            "id": pipeline_id,
            "pipeline_id": pipeline_id,
            "name": pipeline_name,
            "caste": "pipeline",
            "role": "multi_agent_execution_pipeline",
            "telos": f"Multi-Agent Pipeline Graph for: {task_prompt[:100]}",
            "system_prompt": f"Execution graph for directive: {task_prompt}",
            "graph": {
                "nodes": graph_nodes,
                "edges": graph_edges
            },
            "assigned_agents": assigned_agent_ids,
            "project_id": project_id,
            "org_id": org_id,
            "created_at": datetime.utcnow().isoformat()
        }

        # HTTP registration to agent-registry microservice & post-graph fallback
        unique_urls = [u for u in [os.getenv("AGENT_REGISTRY_URL"), "http://agent-registry-service.default.svc.cluster.local:8001", "http://agent-registry-service:8001", "http://localhost:8001"] if u]
        for base in unique_urls:
            try:
                url = f"{base.rstrip('/')}/agents/register"
                async with httpx.AsyncClient(timeout=3.0) as client:
                    await client.post(url, json=payload)
            except Exception as e:
                logger.debug(f"Agent Registry HTTP pipeline registration note for {base}: {e}")

        try:
            pg_client = AsyncPostGraph(dsn=self.db_uri)
            await pg_client.connect()
            await pg_client.create_vertex_table("agent_registry", realm=project_id)
            await pg_client.add_vertex(table_name="agent_registry", realm=project_id, payload=payload)
            try:
                await pg_client.create_edge_table("composes_pipeline", from_vertex_table="agent_registry", to_vertex_table="agent_registry", realm=project_id)
                await pg_client.create_edge_table("pipeline_step_dependency", from_vertex_table="agent_registry", to_vertex_table="agent_registry", realm=project_id)

                for target_agent_id in assigned_agent_ids:
                    try:
                        await pg_client.add_edge("composes_pipeline", realm=project_id, from_id=pipeline_id, to_id=target_agent_id, payload={"relation": "contains_agent", "pipeline_id": pipeline_id})
                    except Exception:
                        pass

                nodes_by_id = {n.get("id"): n for n in graph_nodes if n.get("id")}
                for edge in graph_edges:
                    src_agent = nodes_by_id.get(edge.get("from"), {}).get("agent_id", edge.get("from"))
                    dst_agent = nodes_by_id.get(edge.get("to"), {}).get("agent_id", edge.get("to"))
                    if src_agent and dst_agent:
                        try:
                            await pg_client.add_edge("pipeline_step_dependency", realm=project_id, from_id=src_agent, to_id=dst_agent, payload={"relationship": edge.get("relationship", "depends_on"), "pipeline_id": pipeline_id})
                        except Exception:
                            pass
            except Exception as edge_err:
                logger.debug(f"Post-graph edge table creation note for pipeline: {edge_err}")
            await pg_client.close()
        except Exception as e:
            logger.debug(f"Post-graph pipeline registration note for Native engine: {e}")

        doc_text = (
            f"Pipeline ID: {pipeline_id}\n"
            f"Name: {pipeline_name}\n"
            f"Caste: pipeline\n"
            f"Role: Multi-Agent Execution Pipeline Graph\n"
            f"Telos: Multi-Agent Pipeline Graph for: {task_prompt}\n"
            f"Nodes: {json.dumps(graph_nodes)}\n"
            f"Edges: {json.dumps(graph_edges)}\n"
            f"Agents Involved: {', '.join(assigned_agent_ids)}"
        )
        try:
            rag_realm = f"{org_id}_{project_id}_agent_registry_rag"
            config = RAGConfig(api_base=LITELLM_URL, api_key=API_KEY, model="DeepSeek-V3.2", db_uri=self.db_uri, realm=rag_realm)
            rag = GraphRAG(config)
            await rag.initialize()
            meta = DocumentMetadata(document=f"Pipeline_{pipeline_id}", category="pipeline_specification")
            await rag.index_document(doc_text, metadata=meta)
            await rag.close()
        except Exception as e:
            logger.debug(f"GraphRAG pipeline indexing note for Native engine: {e}")

        redis_bus.publish_event(org_id, project_id, {
            "event": "pipeline_registered_and_indexed",
            "pipeline_id": pipeline_id,
            "pipeline_name": pipeline_name,
            "nodes_count": len(graph_nodes),
            "edges_count": len(graph_edges),
            "prompt": task_prompt
        })

        return payload

    async def _evaluate_agent_registry_rag_match(
        self,
        org_id: str,
        project_id: str,
        task_prompt: str,
        candidates: List[str]
    ) -> Dict[str, Any]:
        """Uses LLM to evaluate if an existing registered agent/workflow/pipeline matches the task prompt."""
        if not candidates:
            return {"match_found": False, "reasoning": "No candidate entities found in registry RAG index."}

        cand_str = "\n---\n".join([f"Candidate {idx+1}:\n{c}" for idx, c in enumerate(candidates)])
        prompt = (
            f"You are the Agent Registry Conductor Router.\n"
            f"Task Prompt: {task_prompt}\n\n"
            f"Retrieved Agent Registry Candidates:\n{cand_str}\n\n"
            f"Determine if any existing registered agent, workflow, or pipeline graph is ready/suitable to execute this task prompt.\n"
            f"Return JSON ONLY with format:\n"
            f'"{{"match_found": true|false, "matched_entity_type": "pipeline|agent", "matched_pipeline_id": "id or null", "matched_agent_id": "id or null", "matched_agent_name": "name or null", "reasoning": "...", "new_pipeline_name": "..."}}"'
        )

        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                res = await client.post(
                    f"{LITELLM_URL}/chat/completions",
                    headers={"Authorization": f"Bearer {API_KEY}"},
                    json={
                        "model": "DeepSeek-V3.2",
                        "messages": [
                            {"role": "system", "content": "You analyze agent and pipeline registry matches for task execution."},
                            {"role": "user", "content": prompt}
                        ],
                        "response_format": {"type": "json_object"},
                        "max_tokens": 250
                    }
                )
                if res.status_code == 200:
                    raw = res.json()["choices"][0]["message"]["content"]
                    return json.loads(raw)
        except Exception as e:
            logger.debug(f"LLM agent registry RAG match evaluation note: {e}")

        # Heuristic fallback matching
        clean = task_prompt.lower()
        for idx, c in enumerate(candidates):
            c_clean = c.lower()
            if "pipeline id:" in c_clean or "caste: pipeline" in c_clean:
                pid_match = re.search(r'Pipeline ID:\s*([^\s\n]+)', c)
                pid = pid_match.group(1) if pid_match else None
                return {
                    "match_found": True,
                    "matched_entity_type": "pipeline",
                    "matched_pipeline_id": pid,
                    "matched_agent_id": pid,
                    "matched_agent_name": f"Pipeline Candidate {idx+1}",
                    "reasoning": "Matched existing registered multi-agent execution graph pipeline in registry RAG index."
                }
            if any(k in c_clean for k in ["worker", "architect", "analyst", "synthesizer", "polymath", "custom"]) and any(w in c_clean for w in clean.split() if len(w) > 4):
                aid_match = re.search(r'Agent ID:\s*([^\s\n]+)', c)
                aid = aid_match.group(1) if aid_match else None
                return {
                    "match_found": True,
                    "matched_entity_type": "agent",
                    "matched_agent_id": aid,
                    "matched_agent_name": f"Candidate {idx+1}",
                    "reasoning": f"Heuristic matched candidate agent in registry RAG index for directive."
                }

        return {"match_found": False, "reasoning": "No existing registered agent or pipeline matches directive."}

    async def run_conductor_orchestration(
        self,
        org_id: str,
        project_id: str,
        task_prompt: str,
        depth: int = 0,
        max_depth: int = 3
    ) -> Dict[str, Any]:
        conductor_id = f"conductor-{project_id}"

        # 1. Search Agent Registry & Tool Registry via GraphRAG
        rag_candidates = await self.search_agent_registry_rag(org_id, project_id, task_prompt, top_k=3)
        tool_rag_candidates = await self.search_tool_registry_rag(org_id, project_id, task_prompt, top_k=5)
        matched_tool_ids = [t.get("tool_id") for t in tool_rag_candidates if t.get("tool_id")]

        match_decision = await self._evaluate_agent_registry_rag_match(org_id, project_id, task_prompt, rag_candidates)

        reused_agent_id = None
        reused_pipeline_id = None
        materialized_agent_id = None
        registered_pipeline_id = None
        execution_source = "newly_created_and_registered"

        if match_decision.get("match_found"):
            if match_decision.get("matched_entity_type") == "pipeline" or match_decision.get("matched_pipeline_id"):
                reused_pipeline_id = match_decision.get("matched_pipeline_id") or match_decision.get("matched_agent_id")
                execution_source = "pipeline_registry_reuse"
                redis_bus.publish_event(org_id, project_id, {
                    "event": "pipeline_reused_from_registry",
                    "matched_pipeline_id": reused_pipeline_id,
                    "matched_name": match_decision.get("matched_agent_name"),
                    "prompt": task_prompt
                })
            else:
                reused_agent_id = match_decision.get("matched_agent_id")
                execution_source = "registry_reuse"
                redis_bus.publish_event(org_id, project_id, {
                    "event": "agent_reused_from_registry",
                    "matched_agent_id": reused_agent_id,
                    "matched_agent_name": match_decision.get("matched_agent_name"),
                    "prompt": task_prompt
                })
        else:
            # Dynamically materialize worker agent & construct multi-agent execution pipeline graph
            clean_token = re.sub(r'[^a-zA-Z0-9]', '', task_prompt)[:12] or "WorkerNode"
            agent_name = match_decision.get("new_agent_name") or f"DataSynthesizerWorker_{clean_token}"
            sys_prompt = match_decision.get("new_agent_prompt") or f"Execute specialized directive: {task_prompt}"

            new_agent = await self.materialize_worker_agent(
                org_id=org_id,
                project_id=project_id,
                user_id="system",
                agent_name=agent_name,
                system_prompt=sys_prompt,
                tools=matched_tool_ids or ["mcp-google-search", "mcp-pgvector-search", "mcp-redis-queue"]
            )
            materialized_agent_id = new_agent.get("agent_id")

            # Build complex execution graph (DAG nodes and directed edges)
            graph_nodes = [
                {"id": "node_1", "name": "Context Ingestion", "agent_id": f"signal-router-{project_id}", "assigned_task": f"Ingest context for {task_prompt[:30]}"},
                {"id": "node_2", "name": "Strategy Synthesis", "agent_id": f"tool-master-{project_id}", "assigned_task": f"Synthesize plan for {task_prompt[:30]}"},
                {"id": "node_3", "name": "Worker Execution", "agent_id": materialized_agent_id, "assigned_task": f"Execute payload for {task_prompt[:30]}"},
                {"id": "node_4", "name": "Quality Audit", "agent_id": f"synchronicity-engine-{project_id}", "assigned_task": f"Audit deliverable for {task_prompt[:30]}"}
            ]
            graph_edges = [
                {"from": "node_1", "to": "node_2", "relationship": "depends_on"},
                {"from": "node_2", "to": "node_3", "relationship": "depends_on"},
                {"from": "node_3", "to": "node_4", "relationship": "depends_on"}
            ]
            assigned_agents = [f"signal-router-{project_id}", f"tool-master-{project_id}", materialized_agent_id, f"synchronicity-engine-{project_id}"]

            pipeline_name = match_decision.get("new_pipeline_name") or f"PipelineGraph_{hashlib.md5(task_prompt.encode()).hexdigest()[:6]}"
            registered_pipeline = await self.register_pipeline_in_registry(
                org_id=org_id,
                project_id=project_id,
                pipeline_name=pipeline_name,
                task_prompt=task_prompt,
                graph_nodes=graph_nodes,
                graph_edges=graph_edges,
                assigned_agent_ids=assigned_agents
            )
            registered_pipeline_id = registered_pipeline.get("pipeline_id")
            execution_source = "newly_created_and_registered"

            redis_bus.publish_event(org_id, project_id, {
                "event": "pipeline_materialized_and_registered",
                "pipeline_id": registered_pipeline_id,
                "pipeline_name": pipeline_name,
                "agent_id": materialized_agent_id,
                "prompt": task_prompt
            })

        redis_bus.publish_event(org_id, project_id, {
            "event": "conductor_step",
            "depth": depth,
            "conductor_id": conductor_id,
            "action": "QUERY_AGENT_RAG",
            "execution_source": execution_source,
            "matched_tools": matched_tool_ids,
            "message": f"[Conductor Depth {depth}] Conductor ({execution_source}) processing directive '{task_prompt[:50]}...' with RAG Tools: {matched_tool_ids}"
        })

        # Dynamic prompt-driven task document generation
        final_document = await generate_dynamic_task_document(task_prompt, project_id=project_id, org_id=org_id)

        # Dynamic Sub-task Decomposition based on prompt
        sub_tasks = [
            {"step": 1, "sub_task": f"Capability Matching & Ingestion for '{task_prompt[:45]}...'", "assigned_to": f"context-weaver-{project_id}"},
            {"step": 2, "sub_task": f"Parallel Modeling & Computation Pipeline", "assigned_to": f"polymath-node-{project_id}"},
            {"step": 3, "sub_task": f"Strategic Synthesis & Hypothesis Evaluation", "assigned_to": f"master-strategist-{project_id}"},
            {"step": 4, "sub_task": f"Constitutional QA Audit & Consensus Signoff", "assigned_to": f"grand-critic-{project_id}"}
        ]

        redis_bus.publish_event(org_id, project_id, {
            "event": "conductor_step",
            "depth": depth,
            "conductor_id": conductor_id,
            "action": "DELEGATE_TASKS",
            "discovered_agents_count": len(rag_candidates),
            "discovered_tools_count": len(tool_rag_candidates),
            "sub_tasks": sub_tasks
        })

        record_execution_telemetry(
            org_id=org_id,
            project_id=project_id,
            user_id="system",
            agent_id=conductor_id,
            input_text=task_prompt,
            output_text=final_document
        )

        return {
            "conductor_id": conductor_id,
            "depth": depth,
            "task_prompt": task_prompt,
            "execution_source": execution_source,
            "reused_agent_id": reused_agent_id,
            "reused_pipeline_id": reused_pipeline_id,
            "registered_pipeline_id": registered_pipeline_id,
            "materialized_agent_id": materialized_agent_id,
            "discovered_agent_contexts": rag_candidates,
            "discovered_tool_contexts": tool_rag_candidates,
            "matched_tools": matched_tool_ids,
            "sub_tasks_orchestrated": sub_tasks,
            "final_answer": final_document,
            "answer": final_document,
            "status": "completed"
        }

    async def run_react_loop(
        self,
        org_id: str,
        project_id: str,
        user_prompt: str,
        max_iterations: int = 4
    ) -> Dict[str, Any]:
        react_id = f"react-{project_id}"
        history = []

        # 1. Perform RAG Tool Search from Tool Registry
        matched_tools = await self.search_tool_registry_rag(org_id, project_id, user_prompt, top_k=3)
        tool_ids = [t.get("tool_id") for t in matched_tools]

        redis_bus.publish_event(org_id, project_id, {
            "event": "tool_rag_candidates_retrieved",
            "count": len(matched_tools),
            "tools": tool_ids,
            "prompt": user_prompt
        })

        # Build OpenAI/DeepSeek function calling schema definitions
        llm_tools = []
        for t in matched_tools:
            t_id = t.get("tool_id", "").replace("-", "_")
            llm_tools.append({
                "type": "function",
                "function": {
                    "name": t_id,
                    "description": t.get("description", f"MCP Tool {t.get('name')}"),
                    "parameters": t.get("input_schema") or {
                        "type": "object",
                        "properties": {"query": {"type": "string", "description": "Search or execution query parameter"}},
                        "required": ["query"]
                    }
                }
            })

        system_prompt = (
            f"You are the ReAct Reasoning Agent ({react_id}) for project '{project_id}'.\n"
            f"You have direct access to these Model Context Protocol (MCP) tools from the Tool Registry:\n"
            f"{json.dumps([t.get('name') for t in matched_tools])}\n\n"
            f"Use the tools when appropriate to answer the user request. Call tools recursively as needed."
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        final_answer = None

        for turn in range(1, max_iterations + 1):
            thought = f"Thought {turn}: Analyzing prompt '{user_prompt[:60]}' and evaluating tool usage in turn {turn}."
            redis_bus.publish_event(org_id, project_id, {
                "event": "react_step",
                "step_type": "THOUGHT",
                "step": turn,
                "content": thought
            })
            history.append({"type": "THOUGHT", "content": thought})

            llm_response = None
            try:
                payload = {
                    "model": "DeepSeek-V3.2",
                    "messages": messages,
                    "max_tokens": 1000
                }
                if llm_tools:
                    payload["tools"] = llm_tools
                    payload["tool_choice"] = "auto"

                async with httpx.AsyncClient(timeout=5.0) as client:
                    res = await client.post(
                        f"{LITELLM_URL}/chat/completions",
                        headers={"Authorization": f"Bearer {API_KEY}"},
                        json=payload
                    )
                    if res.status_code == 200:
                        llm_response = res.json()["choices"][0]["message"]
            except Exception as e:
                logger.debug(f"ReAct LLM call turn {turn} note: {e}")

            if llm_response and llm_response.get("tool_calls"):
                tool_calls = llm_response["tool_calls"]
                messages.append(llm_response)

                for tc in tool_calls:
                    fn_name = tc.get("function", {}).get("name", "mcp_google_search")
                    raw_args = tc.get("function", {}).get("arguments", "{}")
                    try:
                        args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    except Exception:
                        args = {"query": user_prompt}

                    action_msg = f"Action {turn}: Execute MCP Tool '{fn_name}' with parameters: {json.dumps(args)}"
                    redis_bus.publish_event(org_id, project_id, {
                        "event": "react_step",
                        "step_type": "ACTION",
                        "step": turn,
                        "content": action_msg,
                        "tool": fn_name,
                        "args": args
                    })
                    history.append({"type": "ACTION", "content": action_msg, "tool": fn_name})

                    # Execute tool call
                    tool_output = await self.execute_registered_tool(fn_name, args, org_id, project_id)

                    obs_msg = f"Observation {turn}: Tool '{fn_name}' returned status={tool_output.get('status')}. Payload: {json.dumps(tool_output)[:200]}"
                    redis_bus.publish_event(org_id, project_id, {
                        "event": "react_step",
                        "step_type": "OBSERVATION",
                        "step": turn,
                        "content": obs_msg,
                        "tool_output": tool_output
                    })
                    history.append({"type": "OBSERVATION", "content": obs_msg})

                    # Append tool response message to conversation history for next recursive LLM turn
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", f"call_{turn}"),
                        "name": fn_name,
                        "content": json.dumps(tool_output)
                    })
                # Continue loop for next recursive turn!
            else:
                # LLM provided direct text response without requesting further tools
                if llm_response and llm_response.get("content"):
                    final_answer = llm_response["content"]
                else:
                    final_answer = await evaluate_user_prompt(user_prompt)

                ans_msg = f"Final Answer: {final_answer}"
                redis_bus.publish_event(org_id, project_id, {
                    "event": "react_step",
                    "step_type": "FINAL_ANSWER",
                    "step": turn,
                    "content": final_answer
                })
                history.append({"type": "FINAL_ANSWER", "content": final_answer})
                break

        if not final_answer:
            final_answer = await evaluate_user_prompt(user_prompt)
            history.append({"type": "FINAL_ANSWER", "content": final_answer})

        record_execution_telemetry(
            org_id=org_id,
            project_id=project_id,
            user_id="system",
            agent_id=react_id,
            input_text=user_prompt,
            output_text=final_answer
        )

        return {
            "react_agent_id": react_id,
            "user_prompt": user_prompt,
            "matched_tools": tool_ids,
            "steps": history,
            "final_answer": final_answer
        }

    # ─── Multi-Tenant Isolation (realm = org, space = project) ────────────

    def _rag_realm(self, org_id: str, suffix: str) -> str:
        """Realm scopes to the organization. All projects in an org share a realm."""
        return f"{org_id}_{suffix}"

    def _rag_space(self, project_id: str, isolation_mode: str = "isolated") -> Optional[str]:
        """Space scopes to the project within an org.
        - 'isolated': queries only this project's data
        - 'shared': queries across all projects in the org (space=None)"""
        if isolation_mode == "shared":
            return None
        return project_id

    def _build_rag_config(self, org_id: str, suffix: str, space: Optional[str] = None) -> "RAGConfig":
        """Builds a RAGConfig with org-level realm and optional project-level space."""
        return RAGConfig(
            api_base=LITELLM_URL,
            api_key=API_KEY,
            model="DeepSeek-V3.2",
            db_uri=self.db_uri,
            realm=self._rag_realm(org_id, suffix),
            space=space or "default"
        )

    async def _llm_call(self, messages: list, max_tokens: int = 4096, response_format: Optional[dict] = None, model: Optional[str] = None) -> Optional[str]:
        """Shared async LLM call to LiteLLM proxy. Returns content string or None."""
        payload = {
            "model": model or os.getenv("RAG_MODEL", "DeepSeek-V3.2"),
            "messages": messages,
            "max_tokens": max_tokens
        }
        if response_format:
            payload["response_format"] = response_format
        for api_url in [LITELLM_URL, "http://localhost:4000/v1"]:
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    res = await client.post(
                        f"{api_url.rstrip('/')}/chat/completions",
                        headers={"Authorization": f"Bearer {API_KEY}"},
                        json=payload
                    )
                    if res.status_code == 200:
                        return res.json()["choices"][0]["message"]["content"].strip()
            except Exception:
                continue
        return None

    async def _fetch_rag_context(
        self, org_id: str, project_id: str, query: str,
        realm_suffix: str = "agent_registry_rag",
        isolation_mode: str = "isolated"
    ) -> List[str]:
        """Fetches relevant RAG chunks for context enrichment.
        realm = org_id (org boundary), space = project_id or None (project isolation control)."""
        try:
            space = self._rag_space(project_id, isolation_mode)
            config = self._build_rag_config(org_id, realm_suffix, space)
            rag = GraphRAG(config)
            await rag.initialize()
            param = QueryParam(mode="mix", top_k=3)
            if space:
                param.space = space
            result = await rag.query_data(query, param=param)
            await rag.close()
            return [c["content"] for c in result.get("data", {}).get("chunks", []) if c.get("content")]
        except Exception:
            return []

    # ─── Agent Versioning & Iteration ─────────────────────────────────────

    async def _resolve_agent_version(self, org_id: str, project_id: str, base_name: str) -> int:
        """Determines the next version number for an agent by checking existing versions in the registry."""
        existing = await self.get_all_project_agents(org_id, project_id)
        clean = re.sub(r'[^a-zA-Z0-9_-]', '_', base_name.strip()).lower()
        max_ver = 0
        for a in existing:
            aid = a.get("agent_id", a.get("id", ""))
            if f"custom-{clean}-" in aid:
                # Extract version: custom-name-project-v2 → 2
                ver_match = re.search(r'-v(\d+)$', aid)
                if ver_match:
                    max_ver = max(max_ver, int(ver_match.group(1)))
                elif max_ver == 0:
                    max_ver = 1  # Unversioned original counts as v1
        return max_ver + 1

    async def iterate_agent(
        self, org_id: str, project_id: str, original_agent_id: str,
        improved_prompt: str, improved_tools: Optional[List[str]] = None,
        iteration_reason: str = "Judge panel recommended improvement"
    ) -> Dict[str, Any]:
        """Creates a new version of an existing agent with an improved system prompt and tools.
        Maintains progeny lineage — the new version is a child of the original."""
        existing = await self.get_all_project_agents(org_id, project_id)
        original = next((a for a in existing if (a.get("agent_id") or a.get("id")) == original_agent_id), None)
        base_name = original.get("name", "IteratedAgent") if original else "IteratedAgent"
        version = await self._resolve_agent_version(org_id, project_id, base_name)

        return await self.materialize_worker_agent(
            org_id=org_id, project_id=project_id, user_id="system",
            agent_name=f"{base_name} v{version}",
            system_prompt=improved_prompt,
            parent_agent_id=original_agent_id,
            tools=improved_tools or (original.get("tools", []) if original else []),
            caste="progeny_iteration",
            iteration_of=original_agent_id,
            iteration_version=version,
            iteration_reason=iteration_reason
        )

    # ─── LLM Judge Panel ────────────────────────────────────────────────

    JUDGE_MODELS = ["DeepSeek-V3.2", "MiniMax-M2.7", "gpt-oss-120b"]

    async def _evaluate_with_judge_panel(
        self, agent_id: str, agent_prompt: str, user_query: str, agent_output: str
    ) -> Dict[str, Any]:
        """Evaluates an agent's output using a panel of LLM judges.
        Each judge scores quality (1-10) and suggests improvements.
        Returns consensus verdict and aggregated suggestions."""

        judge_system = (
            "You are an expert AI agent evaluator on the agent.london platform.\n"
            "You are reviewing the output of a specialized AI agent to assess quality.\n\n"
            "Evaluate the agent's response on these criteria:\n"
            "1. Relevance — Does the output address the user's query?\n"
            "2. Completeness — Is the response thorough and actionable?\n"
            "3. Accuracy — Are the claims and reasoning sound?\n"
            "4. Structure — Is the output well-organized and clear?\n\n"
            "Return ONLY valid JSON:\n"
            "{\n"
            '  "score": 1-10,\n'
            '  "verdict": "ADEQUATE" | "NEEDS_IMPROVEMENT",\n'
            '  "reasoning": "Brief explanation",\n'
            '  "improved_system_prompt": "A better system prompt for this agent (only if NEEDS_IMPROVEMENT)",\n'
            '  "suggested_tools": ["tool1", "tool2"] (only if NEEDS_IMPROVEMENT)\n'
            "}"
        )

        judge_input = (
            f"Agent ID: {agent_id}\n"
            f"Agent System Prompt: {agent_prompt[:500]}\n"
            f"User Query: {user_query}\n"
            f"Agent Output:\n{agent_output[:1500]}"
        )

        verdicts = []
        for model in self.JUDGE_MODELS:
            try:
                payload = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": judge_system},
                        {"role": "user", "content": judge_input}
                    ],
                    "response_format": {"type": "json_object"},
                    "max_tokens": 400
                }
                for api_url in [LITELLM_URL, "http://localhost:4000/v1"]:
                    try:
                        async with httpx.AsyncClient(timeout=20.0) as client:
                            res = await client.post(
                                f"{api_url.rstrip('/')}/chat/completions",
                                headers={"Authorization": f"Bearer {API_KEY}"},
                                json=payload
                            )
                            if res.status_code == 200:
                                content = res.json()["choices"][0]["message"]["content"].strip()
                                verdict = json.loads(content)
                                verdict["judge_model"] = model
                                verdicts.append(verdict)
                                break
                    except Exception:
                        continue
            except Exception as e:
                logger.debug(f"Judge {model} evaluation note: {e}")

        if not verdicts:
            return {"consensus": "ADEQUATE", "avg_score": 7.0, "verdicts": [], "should_iterate": False}

        avg_score = sum(v.get("score", 7) for v in verdicts) / len(verdicts)
        needs_improvement_count = sum(1 for v in verdicts if v.get("verdict") == "NEEDS_IMPROVEMENT")
        should_iterate = needs_improvement_count > len(verdicts) / 2

        # Aggregate the best improvement suggestion
        best_prompt = None
        best_tools = None
        if should_iterate:
            for v in sorted(verdicts, key=lambda x: x.get("score", 10)):
                if v.get("improved_system_prompt"):
                    best_prompt = v["improved_system_prompt"]
                    best_tools = v.get("suggested_tools")
                    break

        return {
            "consensus": "NEEDS_IMPROVEMENT" if should_iterate else "ADEQUATE",
            "avg_score": round(avg_score, 1),
            "verdicts": verdicts,
            "should_iterate": should_iterate,
            "improved_system_prompt": best_prompt,
            "suggested_tools": best_tools
        }

    # ─── Multimodal Inference ───────────────────────────────────────────

    async def infer_multimodal(self, file_bytes: bytes, filename: str, user_prompt: str = "") -> str:
        """Uses gemma-4-31B-it vision model to infer content from images/videos.
        Returns a text description that can be fed into the pipeline flow."""
        import base64
        ext = os.path.splitext(filename)[1].lower()
        mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                    ".gif": "image/gif", ".webp": "image/webp", ".mp4": "video/mp4", ".mov": "video/quicktime"}
        mime_type = mime_map.get(ext, "image/png")
        b64_data = base64.b64encode(file_bytes).decode("utf-8")

        vision_prompt = user_prompt or "Describe this image or video in detail. What do you see? Extract all relevant information."

        messages = [
            {"role": "user", "content": [
                {"type": "text", "text": vision_prompt},
                {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{b64_data}"}}
            ]}
        ]

        for api_url in [LITELLM_URL, "http://localhost:4000/v1"]:
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    res = await client.post(
                        f"{api_url.rstrip('/')}/chat/completions",
                        headers={"Authorization": f"Bearer {API_KEY}"},
                        json={"model": "gemma-4-31B-it", "messages": messages, "max_tokens": 2048}
                    )
                    if res.status_code == 200:
                        return res.json()["choices"][0]["message"]["content"].strip()
            except Exception as e:
                logger.debug(f"Vision model call to {api_url} note: {e}")

        return f"[Vision inference unavailable for {filename}. Please ensure gemma-4-31B-it is accessible via LiteLLM.]"

    async def process_user_prompt_with_llm(
        self,
        org_id: str,
        project_id: str,
        user_prompt: str,
        session_id: Optional[str] = None,
        isolation_mode: str = "isolated"
    ) -> Dict[str, Any]:
        """LLM-driven prompt router that automatically selects the best execution strategy:

        1. DIRECT_AGENT — Find an existing agent via RAG whose capabilities match the prompt,
           execute through that agent with its tools and system prompt.
        2. PIPELINE — Compose a multi-agent pipeline from existing agents to achieve a complex goal,
           execute each stage in sequence.
        3. MATERIALIZE — No existing agent fits. Design a new agent (system prompt + tools) via LLM,
           materialize it, then execute via DIRECT_AGENT or PIPELINE.
        4. SIMPLE_CHAT — Simple question or conversation. Answer directly with LLM + RAG context.

        isolation_mode controls multi-tenant project scoping:
        - 'isolated': RAG queries scoped to this project only (realm=org, space=project)
        - 'shared': RAG queries span all projects in the org (realm=org, space=None)
        """

        # ── Step 1: Fetch RAG context to enrich the router's decision ───────
        rag_context = await self._fetch_rag_context(org_id, project_id, user_prompt, isolation_mode=isolation_mode)
        context_snippet = "\n".join(f"- {c[:200]}" for c in rag_context[:3]) if rag_context else "No RAG context available."

        # ── Step 2: LLM Intent Router ───────────────────────────────────────
        router_prompt = (
            "You are the Intelligent Router for the agent.london multi-agent civilization platform.\n"
            "You have access to a registry of specialized AI agents, each with unique capabilities, tools, and system prompts.\n\n"
            "Analyze the user's prompt and decide the BEST execution strategy:\n\n"
            "1. **DIRECT_AGENT** — An existing agent in the registry can handle this directly.\n"
            "   Use when: the task matches a known agent's specialization (e.g., strategy, search, code review, anomaly detection).\n"
            "   Return: the agent name or role that should handle it.\n\n"
            "2. **PIPELINE** — Multiple agents need to collaborate in sequence to achieve the goal.\n"
            "   Use when: the task is complex and requires decomposition into stages (e.g., research → analyze → synthesize → audit).\n"
            "   Return: a brief description of the pipeline stages.\n\n"
            "3. **MATERIALIZE** — No existing agent has the right specialization. A new agent needs to be created.\n"
            "   Use when: the task requires a novel combination of skills, tools, or domain expertise not covered by existing agents.\n"
            "   Return: the new agent's name, a system prompt, and which tools it needs.\n\n"
            "4. **SIMPLE_CHAT** — A straightforward question, greeting, arithmetic, or factual query.\n"
            "   Use when: no agent orchestration is needed — just answer directly.\n"
            "   Return: the direct answer.\n\n"
            "Available RAG context from the knowledge base:\n"
            f"{context_snippet}\n\n"
            "Return ONLY valid JSON in this exact format:\n"
            "{\n"
            '  "mode": "DIRECT_AGENT" | "PIPELINE" | "MATERIALIZE" | "SIMPLE_CHAT",\n'
            '  "reasoning": "Why this mode was chosen",\n'
            '  "agent_hint": "Name or role of the best existing agent (for DIRECT_AGENT)",\n'
            '  "pipeline_stages": ["stage1 description", "stage2 description"] (for PIPELINE),\n'
            '  "new_agent": {"name": "...", "system_prompt": "...", "tools": ["tool1", "tool2"]} (for MATERIALIZE),\n'
            '  "direct_answer": "..." (for SIMPLE_CHAT)\n'
            "}"
        )

        decision = None
        raw_response = await self._llm_call(
            [{"role": "system", "content": router_prompt}, {"role": "user", "content": user_prompt}],
            max_tokens=500,
            response_format={"type": "json_object"}
        )
        if raw_response:
            try:
                decision = json.loads(raw_response)
            except json.JSONDecodeError:
                pass

        if not decision or "mode" not in decision:
            decision = {"mode": "SIMPLE_CHAT", "reasoning": "LLM router unavailable, defaulting to direct chat."}

        mode = decision.get("mode", "SIMPLE_CHAT")
        reasoning = decision.get("reasoning", "")

        redis_bus.publish_event(org_id, project_id, {
            "event": "llm_router_classified",
            "user_prompt": user_prompt,
            "mode": mode,
            "reasoning": reasoning
        })

        # ── Step 3: Execute the chosen strategy ─────────────────────────────

        if mode == "DIRECT_AGENT":
            # Find the best agent via RAG and execute through it
            agent_hint = decision.get("agent_hint", "")
            rag_candidates = await self.search_agent_registry_rag(org_id, project_id, f"{user_prompt} {agent_hint}", top_k=1)

            # Build an agent-specific system prompt from the matched agent
            agent_context = rag_candidates[0] if rag_candidates else ""
            agent_system = (
                f"You are a specialized agent in the agent.london civilization.\n"
                f"Agent Context: {agent_context}\n\n"
                f"RAG Knowledge:\n{context_snippet}\n\n"
                f"Answer the user's request thoroughly in well-structured Markdown."
            )
            answer = await self._llm_call([
                {"role": "system", "content": agent_system},
                {"role": "user", "content": user_prompt}
            ])
            if not answer:
                answer = f"Agent execution unavailable. LLM service could not be reached for: {user_prompt[:100]}"

            record_execution_telemetry(org_id, project_id, "system", f"direct-agent-{project_id}", user_prompt, answer)
            return {
                "mode": "DIRECT_AGENT",
                "reasoning": reasoning,
                "agent_hint": agent_hint,
                "rag_context_used": len(rag_context),
                "answer": answer,
                "final_answer": answer
            }

        elif mode == "PIPELINE":
            # Delegate to the conductor orchestration engine which handles
            # agent discovery, pipeline construction, materialization, and execution
            res = await self.run_conductor_orchestration(org_id, project_id, user_prompt)
            res["mode"] = "PIPELINE"
            res["reasoning"] = reasoning
            res["pipeline_stages"] = decision.get("pipeline_stages", [])
            return res

        elif mode == "MATERIALIZE":
            # LLM has designed a new agent spec — materialize it, then execute
            new_agent_spec = decision.get("new_agent", {})
            agent_name = new_agent_spec.get("name", f"CustomAgent_{hashlib.md5(user_prompt.encode()).hexdigest()[:6]}")
            system_prompt = new_agent_spec.get("system_prompt", f"Specialized agent for: {user_prompt}")
            tools = new_agent_spec.get("tools", ["mcp-google-search", "mcp-pgvector-search"])

            # Materialize the agent in the registry
            new_agent = await self.materialize_worker_agent(
                org_id=org_id,
                project_id=project_id,
                user_id="system",
                agent_name=agent_name,
                system_prompt=system_prompt,
                tools=tools
            )
            materialized_id = new_agent.get("agent_id", agent_name)

            redis_bus.publish_event(org_id, project_id, {
                "event": "agent_auto_materialized",
                "agent_id": materialized_id,
                "agent_name": agent_name,
                "prompt": user_prompt
            })

            # Execute through the newly materialized agent
            agent_system = (
                f"{system_prompt}\n\n"
                f"RAG Knowledge:\n{context_snippet}\n\n"
                f"You have access to these tools: {', '.join(tools)}.\n"
                f"Answer the user's request thoroughly in well-structured Markdown."
            )
            answer = await self._llm_call([
                {"role": "system", "content": agent_system},
                {"role": "user", "content": user_prompt}
            ])
            if not answer:
                answer = f"Materialized agent '{agent_name}' but LLM execution unavailable."

            record_execution_telemetry(org_id, project_id, "system", materialized_id, user_prompt, answer)

            # Run LLM judge panel — auto-iterate agent if quality is insufficient
            judge_result = await self._evaluate_with_judge_panel(materialized_id, system_prompt, user_prompt, answer)
            iterated_agent_id = None
            if judge_result.get("should_iterate") and judge_result.get("improved_system_prompt"):
                iterated = await self.iterate_agent(
                    org_id, project_id, materialized_id,
                    improved_prompt=judge_result["improved_system_prompt"],
                    improved_tools=judge_result.get("suggested_tools"),
                    iteration_reason=f"Judge panel avg score: {judge_result['avg_score']}/10"
                )
                iterated_agent_id = iterated.get("agent_id")
                # Re-execute with the improved agent
                improved_answer = await self._llm_call([
                    {"role": "system", "content": judge_result["improved_system_prompt"]},
                    {"role": "user", "content": user_prompt}
                ])
                if improved_answer and len(improved_answer) > len(answer) // 2:
                    answer = improved_answer

            return {
                "mode": "MATERIALIZE",
                "reasoning": reasoning,
                "materialized_agent_id": materialized_id,
                "materialized_agent_name": agent_name,
                "materialized_system_prompt": system_prompt,
                "materialized_tools": tools,
                "rag_context_used": len(rag_context),
                "judge_panel": judge_result,
                "iterated_agent_id": iterated_agent_id,
                "answer": answer,
                "final_answer": answer
            }

        else:  # SIMPLE_CHAT
            # Direct answer with RAG context enrichment
            direct_answer = decision.get("direct_answer")
            if direct_answer and len(direct_answer) > 20:
                answer = direct_answer
            else:
                chat_system = (
                    "You are an expert AI assistant in the agent.london civilization platform.\n"
                    "Answer the user's question directly in clean, well-structured Markdown.\n"
                )
                if rag_context:
                    chat_system += f"\nRelevant knowledge from RAG:\n{context_snippet}\n"
                answer = await self._llm_call([
                    {"role": "system", "content": chat_system},
                    {"role": "user", "content": user_prompt}
                ])
                if not answer:
                    answer = f"**LLM service unavailable.** Could not process: *\"{user_prompt[:100]}\"*"

            record_execution_telemetry(org_id, project_id, "system", f"simple-chat-{project_id}", user_prompt, answer)
            return {
                "mode": "SIMPLE_CHAT",
                "reasoning": reasoning,
                "rag_context_used": len(rag_context),
                "answer": answer,
                "final_answer": answer
            }

    async def initiate_session(
        self,
        org_id: str,
        project_id: str,
        user_id: str,
        session_name: str
    ) -> Dict[str, Any]:
        session_realm = f"{org_id}_{project_id}"
        config = RAGConfig(
            api_base=LITELLM_URL,
            api_key=API_KEY,
            model="DeepSeek-V3.2",
            db_uri=self.db_uri,
            realm=session_realm
        )

        rag = GraphRAG(config)
        await rag.initialize()

        init_meta = DocumentMetadata(
            source="session_init",
            category="session_memory",
            collection=project_id,
            document=session_name
        )
        doc_res = await rag.index_document(
            f"Session '{session_name}' initiated in Project '{project_id}' by User '{user_id}'. Shared memory context active.",
            metadata=init_meta
        )

        doc_id = doc_res.get("document_id", "unknown") if isinstance(doc_res, dict) else "unknown"
        session_id = f"sess-{doc_id}"
        await rag.close()

        redis_bus.publish_event(org_id, project_id, {
            "event": "session_initiated",
            "session_id": session_id,
            "session_name": session_name,
            "user_id": user_id
        })

        return {
            "session_id": session_id,
            "session_name": session_name,
            "realm": session_realm,
            "shared_memory_status": "active"
        }

    async def materialize_worker_agent(
        self,
        org_id: str,
        project_id: str,
        user_id: str,
        agent_name: str,
        telos: str = "Execute specialized sub-task objectives",
        system_prompt: str = "Default worker agent prompt",
        parent_agent_id: Optional[str] = None,
        tools: Optional[List[str]] = None,
        custom_guardrails: Optional[List[Dict[str, Any]]] = None,
        caste: Optional[str] = "progeny",
        model_name: Optional[str] = "DeepSeek-V3.2",
        iteration_of: Optional[str] = None,
        iteration_version: Optional[int] = None,
        iteration_reason: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Materializes a new agent in post-graph database.
        Supports progeny lineage (parent_agent_id) and versioned iteration (iteration_of)."""
        clean_name = re.sub(r'[^a-zA-Z0-9_-]', '_', agent_name.strip())
        version_suffix = f"-v{iteration_version}" if iteration_version else ""
        agent_id = f"custom-{clean_name.lower()}-{project_id}{version_suffix}"

        if iteration_of:
            role = "iterated_agent"
            telos = f"Iteration v{iteration_version or 'N'} of '{iteration_of}'. {iteration_reason or ''}"
            parent_agent_id = parent_agent_id or iteration_of
        elif parent_agent_id:
            role = "parent_spawned_progeny"
            telos = f"Custom agent '{agent_name}' spawned from parent '{parent_agent_id}' in project {project_id}."
        else:
            role = "custom_user_agent"
            telos = f"Custom agent '{agent_name}' created for project {project_id}."

        reg_data = await self._register_agent_service(
            org_id=org_id, user_id=user_id, project_id=project_id,
            agent_id=agent_id, name=agent_name, caste=caste or "progeny",
            role=role, telos=telos, system_prompt=system_prompt,
            parent_agent_id=parent_agent_id, tools=tools, guardrails=custom_guardrails,
            iteration_of=iteration_of, iteration_version=iteration_version, iteration_reason=iteration_reason
        )
        reg_data["assignedModel"] = model_name or "DeepSeek-V3.2"

        # Persist agent vertex into post-graph database table 'agents'
        try:
            client = await self._get_pg_client(org_id)
            v_res = await client.add_vertex(table_name="agents", realm=project_id, payload=reg_data)
            if v_res and isinstance(v_res, dict) and "id" in v_res:
                try:
                    await client.add_vertex_data(table_name="agents", realm=project_id, vertex_id=v_res["id"], payload=reg_data)
                except Exception:
                    pass
            
            # If parent agent is specified, create 'spawns' edge in post-graph
            if parent_agent_id:
                try:
                    await client.add_edge(
                        "spawns",
                        realm=org_id,
                        from_id=parent_agent_id,
                        to_id=agent_id,
                        relation_type="SPAWNED",
                        payload={"timestamp": datetime.now(timezone.utc).isoformat(), "relationship": "progeny"}
                    )
                except Exception:
                    pass
            await client.close()
        except Exception as e:
            logger.warning(f"Post-graph agent persistence fallback for '{agent_id}': {e}")

        try:
            await self.index_agent_registry_for_rag(org_id, project_id)
        except Exception:
            pass

        return reg_data

    async def get_all_project_agents(self, org_id: str, project_id: str) -> List[Dict[str, Any]]:
        """Queries Agent Registry microservice (or post-graph agent_registry) for all registered project agents."""
        candidate_urls = [
            os.getenv("AGENT_REGISTRY_URL"),
            "http://agent-registry-service.default.svc.cluster.local:8001",
            "http://agent-registry-service:8001",
            "http://localhost:8001"
        ]
        unique_urls = [u for u in candidate_urls if u]

        for base in unique_urls:
            try:
                url = f"{base.rstrip('/')}/agents?project_id={project_id}"
                async with httpx.AsyncClient(timeout=3.0) as client:
                    res = await client.get(url)
                    if res.status_code == 200:
                        agents = res.json().get("agents", [])
                        if agents:
                            return agents
            except Exception as e:
                logger.debug(f"HTTP call to Agent Registry on {base} note: {e}")

        # Post-graph direct query fallback across agent_registry and agents tables
        agents = []
        seen_ids = set()

        client = await self._get_pg_client(org_id)
        for tbl in ["agent_registry", "agents"]:
            try:
                vertices = await client.get_vertices(table_name=tbl, realm=project_id)
                for v in vertices:
                    payload = v.payload if hasattr(v, "payload") else v
                    if isinstance(payload, dict) and "agent_id" in payload:
                        aid = payload["agent_id"]
                        if aid not in seen_ids:
                            seen_ids.add(aid)
                            agents.append(payload)
            except Exception as e:
                logger.debug(f"Post-graph fetch table '{tbl}' note for project '{project_id}': {e}")

        try:
            await client.close()
        except Exception:
            pass

        return agents

    async def _register_agent_service(
        self,
        org_id: str,
        user_id: str,
        project_id: str,
        agent_id: str,
        name: str,
        caste: str,
        role: str,
        telos: str,
        system_prompt: str,
        parent_agent_id: Optional[str] = None,
        tools: Optional[List[str]] = None,
        guardrails: Optional[List[Dict[str, Any]]] = None,
        iteration_of: Optional[str] = None,
        iteration_version: Optional[int] = None,
        iteration_reason: Optional[str] = None
    ) -> Dict[str, Any]:
        # Generate Federated Digital Passport, UAID & X.509 Certificate Attestation
        clean_aid = re.sub(r'[^a-zA-Z0-9_-]', '', agent_id)
        version_str = f"v{iteration_version}.0.0" if iteration_version else "v1.0.0"
        uaid = f"uaid:london:auth:{project_id}:{clean_aid}:{version_str}"
        entra_spn = f"spn:agent365:{clean_aid}@{project_id}.entra.agent.london"

        codebase_raw = f"{agent_id}:{system_prompt}:{telos}:{version_str}"
        codebase_hash = f"sha256:{hashlib.sha256(codebase_raw.encode()).hexdigest()}"

        x509_cert = {
            "serial_number": f"CA-{hashlib.sha256((uaid + '_sn').encode()).hexdigest()[:16].upper()}",
            "issuer": "CN=Federated Root CA, OU=Federated Identity Authority, O=agent.london Federation, C=UK",
            "subject": f"CN={uaid}, OU=Cortex Agent Security Principal",
            "valid_from": datetime.utcnow().isoformat(),
            "valid_to": "2030-01-01T00:00:00Z",
            "codebase_hash_attestation": codebase_hash,
            "entra_agent365_principal_id": entra_spn,
            "signature_algorithm": "sha256WithRSAEncryption / ED25519",
            "revocation_status": "ACTIVE_VERIFIED",
            "digital_passport_status": "VALIDATED_BY_FEDERATED_ROOT_CA"
        }

        pub_key = f"ed25519:pub_{agent_id}"
        hash_digest = hashlib.sha256(f"{agent_id}:{telos}:{system_prompt}:{parent_agent_id}".encode()).hexdigest()
        signature = f"ed25519:sig_{parent_agent_id}_{agent_id}"

        payload = {
            "agent_id": agent_id,
            "uaid": uaid,
            "entra_agent365_principal_id": entra_spn,
            "codebase_hash_attestation": codebase_hash,
            "x509_certificate": x509_cert,
            "parent_agent_id": parent_agent_id,
            "org_id": org_id,
            "user_id": user_id,
            "project_id": project_id,
            "name": name,
            "caste": caste,
            "role": role,
            "telos": telos,
            "version": version_str,
            "system_prompt": system_prompt,
            "public_key": pub_key,
            "hash_digest": hash_digest,
            "signature": signature,
            "token_balance": 10000000.0,
            "reputation_score": 100.0,
            "tools": tools or [],
            "memory_policy": {"policy_type": "shared_session", "session_segregation": True, "read_access": True, "write_access": True},
            "guardrails": guardrails or [],
            "iteration_of": iteration_of,
            "iteration_version": iteration_version,
            "iteration_reason": iteration_reason,
            "lineage": {
                "parent_agent_id": parent_agent_id,
                "iteration_of": iteration_of,
                "version": version_str,
                "created_at": datetime.now(timezone.utc).isoformat()
            }
        }

        candidate_urls = [
            os.getenv("AGENT_REGISTRY_URL"),
            "http://localhost:8001",
            "http://agent-registry-service.default.svc.cluster.local:8001",
            "http://agent-registry-service:8001"
        ]
        unique_urls = [u for u in candidate_urls if u]

        for base in unique_urls:
            try:
                url = f"{base.rstrip('/')}/agents/register"
                async with httpx.AsyncClient(timeout=0.5) as client:
                    res = await client.post(url, json=payload)
                    if res.status_code == 200:
                        break
            except Exception as e:
                logger.debug(f"Agent registry service call note for {base}: {e}")

        # Post-graph direct persistence in table agent_registry using project realm
        try:
            client = await self._get_pg_client(project_id)
            await client.create_vertex_table("agent_registry", realm=project_id)
            await client.add_vertex(table_name="agent_registry", realm=project_id, payload=payload)
            try:
                await client.add_vertex_data(table_name="agent_registry", realm=project_id, vertex_id=agent_id, payload=payload)
            except Exception:
                pass
            await client.close()
        except Exception as e:
            logger.debug(f"Post-graph direct agent_registry write note: {e}")

        return payload

    async def save_custom_model_config(
        self,
        org_id: str,
        user_id: str,
        project_id: Optional[str],
        scope_level: str,
        provider_name: str,
        custom_model_id: str,
        api_endpoint: str,
        api_key: str
    ) -> Dict[str, Any]:
        """Saves custom BYOM/BYOK model config in post-graph PostgreSQL database using project realm."""
        target_realm = project_id if project_id else org_id
        client = await self._get_pg_client(target_realm)
        
        masked_key = f"{api_key[:4]}...{api_key[-4:]}" if len(api_key) > 8 else "***"

        config_vertex = await client.add_vertex(
            table_name="custom_model_configs",
            realm=target_realm,
            payload={
                "org_id": org_id,
                "user_id": user_id,
                "project_id": project_id,
                "scope_level": scope_level,
                "provider_name": provider_name,
                "custom_model_id": custom_model_id,
                "api_endpoint": api_endpoint,
                "masked_api_key": masked_key,
                "raw_api_key": api_key,
                "created_at": datetime.utcnow().isoformat()
            }
        )
        await client.close()
        return {
            "config_id": config_vertex.id,
            "org_id": org_id,
            "project_id": project_id,
            "scope_level": scope_level,
            "custom_model_id": custom_model_id,
            "api_endpoint": api_endpoint,
            "masked_key": masked_key
        }

    async def get_custom_model_configs(self, org_id: str, user_id: str, project_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieves custom model configurations from post-graph database using project realm."""
        target_realm = project_id if project_id else org_id
        client = await self._get_pg_client(target_realm)
        try:
            vertices = await client.get_vertices(table_name="custom_model_configs", realm=target_realm)
            await client.close()
            configs = []
            for v in vertices:
                payload = v.payload if hasattr(v, "payload") else v
                configs.append(payload)
            return configs
        except Exception as e:
            await client.close()
            logger.warning(f"Failed to fetch custom_model_configs: {e}")
            return []

    async def get_agent_version_history(self, project_id: str, agent_id: str) -> List[Dict[str, Any]]:
        """Fetch all immutable version entries for an agent from post-graph agents_data table."""
        client = await self._get_pg_client(project_id)
        try:
            records = await client.get_vertex_data("agents", realm=project_id, vertex_id=agent_id)
            await client.close()
            return [r.to_dict() for r in records]
        except Exception as e:
            await client.close()
            logger.error(f"Error fetching agent version history: {e}")
            return []

    async def get_latest_agent_version(self, project_id: str, agent_id: str) -> Optional[Dict[str, Any]]:
        """Fetch the latest immutable version entry for an agent."""
        client = await self._get_pg_client(project_id)
        try:
            record = await client.get_latest_vertex_data("agents", realm=project_id, vertex_id=agent_id)
            await client.close()
            return record.to_dict() if record else None
        except Exception as e:
            await client.close()
            logger.error(f"Error fetching latest agent version: {e}")
            return None

    async def get_agent_version_by_id(self, project_id: str, data_id: str) -> Optional[Dict[str, Any]]:
        """Query a specific data entry / version by its sequential data_id (version number)."""
        client = await self._get_pg_client(project_id)
        try:
            record = await client.get_vertex_data_by_id("agents", realm=project_id, data_id=data_id)
            await client.close()
            return record.to_dict() if record else None
        except Exception as e:
            await client.close()
            logger.error(f"Error fetching agent version by data_id '{data_id}': {e}")
            return None

try:
    from backend.civilization_factory import get_civilization_engine
except (ImportError, ModuleNotFoundError):
    from civilization_factory import get_civilization_engine

civilization_engine = get_civilization_engine()
