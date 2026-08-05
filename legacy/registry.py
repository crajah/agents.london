#!/usr/bin/env python3
"""
Agent Registry Engine for 1-Billion Agent Civilization.
Supports hierarchical addressing (civilization://domain/sector/guild/agent_id),
lineage tracking, state machine management, sentinel auditing, and scale analytics.
"""

import uuid
import time
from enum import Enum
from typing import Dict, List, Optional, Any

class AgentTier(Enum):
    SOVEREIGN = "Sovereign"      # Tier 0: Senate, High Council, Grand Registrar
    PROCREATOR = "Procreator"    # Tier 1: Guild Masters, Factory Spawners
    SENTINEL = "Sentinel"        # Tier 2: Inspector General, Compliance Auditors
    OPERATIVE = "Operative"      # Tier 3: Specialized Worker Citizens

class AgentStatus(Enum):
    REGISTERED = "REGISTERED"
    DEPLOYING = "DEPLOYING"
    ACTIVE = "ACTIVE"
    AUDITING = "AUDITING"
    QUARANTINED = "QUARANTINED"
    RECYCLED = "RECYCLED"

class AgentRecord:
    def __init__(
        self,
        name: str,
        tier: AgentTier,
        domain: str = "core",
        sector: str = "governance",
        guild: str = "senate",
        parent_id: Optional[str] = None,
        capabilities: Optional[List[str]] = None,
        model_name: str = "gpt-4o",
        system_prompt: str = ""
    ):
        self.id = f"agent-{uuid.uuid4().hex[:12]}"
        self.name = name
        self.tier = tier
        self.domain = domain
        self.sector = sector
        self.guild = guild
        self.address = f"civilization://{domain}.{sector}.{guild}.{self.id}"
        self.parent_id = parent_id
        self.children_ids: List[str] = []
        self.status = AgentStatus.REGISTERED
        self.capabilities = capabilities or []
        self.model_name = model_name
        self.system_prompt = system_prompt
        self.created_at = time.time()
        self.updated_at = time.time()
        
        self.telemetry = {
            "tokens_consumed": 0,
            "tasks_completed": 0,
            "error_rate": 0.0,
            "divergence_score": 0.0,
            "latency_ms": 120.0
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "tier": self.tier.value,
            "address": self.address,
            "domain": self.domain,
            "sector": self.sector,
            "guild": self.guild,
            "parent_id": self.parent_id,
            "children_ids": self.children_ids,
            "status": self.status.value,
            "capabilities": self.capabilities,
            "model_name": self.model_name,
            "system_prompt": self.system_prompt,
            "telemetry": self.telemetry,
            "created_at": self.created_at,
            "updated_at": self.updated_at
        }

class AgentRegistry:
    def __init__(self):
        self._agents: Dict[str, AgentRecord] = {}
        self._address_index: Dict[str, str] = {}
        self._tier_index: Dict[AgentTier, List[str]] = {tier: [] for tier in AgentTier}
        self.bootstrap_permanent_civilization()

    def bootstrap_permanent_civilization(self):
        senate = AgentRecord(
            name="Sovereign Senate Prime",
            tier=AgentTier.SOVEREIGN,
            domain="governance",
            sector="executive",
            guild="senate",
            capabilities=["constitution_management", "policy_enforcement", "crd_approval"],
            system_prompt="You are the Sovereign Senate Prime. Maintain civilizational laws and balance of power."
        )
        senate.status = AgentStatus.ACTIVE
        self.register_agent(senate)

        registrar = AgentRecord(
            name="Grand Registrar",
            tier=AgentTier.SOVEREIGN,
            domain="governance",
            sector="executive",
            guild="registrar",
            capabilities=["identity_issuance", "namespace_routing", "sharded_index"],
            system_prompt="You are the Grand Registrar. Issue cryptographic identities and index all 1B agents."
        )
        registrar.status = AgentStatus.ACTIVE
        self.register_agent(registrar)

        sentinel = AgentRecord(
            name="Sentinel Inspector General",
            tier=AgentTier.SENTINEL,
            domain="governance",
            sector="judicial",
            guild="sentinels",
            parent_id=senate.id,
            capabilities=["telemetry_audit", "divergence_detection", "quarantine_execution"],
            system_prompt="You are the Chief Sentinel Inspector. Audit all agent behaviors and quarantine rogue nodes."
        )
        sentinel.status = AgentStatus.ACTIVE
        self.register_agent(sentinel)
        senate.children_ids.append(sentinel.id)

        spawner = AgentRecord(
            name="Master Guild Procreator",
            tier=AgentTier.PROCREATOR,
            domain="engineering",
            sector="fabrication",
            guild="spawners",
            parent_id=senate.id,
            capabilities=["task_decomposition", "agent_synthesis", "kagent_deployment"],
            system_prompt="You are the Master Guild Procreator. Synthesize and spawn worker agents based on task demand."
        )
        spawner.status = AgentStatus.ACTIVE
        self.register_agent(spawner)
        senate.children_ids.append(spawner.id)

    def register_agent(self, agent: AgentRecord) -> AgentRecord:
        self._agents[agent.id] = agent
        self._address_index[agent.address] = agent.id
        self._tier_index[agent.tier].append(agent.id)
        return agent

    def spawn_child_agent(
        self,
        parent_id: str,
        name: str,
        tier: AgentTier,
        domain: str,
        sector: str,
        guild: str,
        capabilities: List[str],
        system_prompt: str
    ) -> AgentRecord:
        parent = self.get_agent(parent_id)
        if not parent:
            raise ValueError(f"Parent agent {parent_id} not found.")

        child = AgentRecord(
            name=name,
            tier=tier,
            domain=domain,
            sector=sector,
            guild=guild,
            parent_id=parent_id,
            capabilities=capabilities,
            system_prompt=system_prompt
        )
        child.status = AgentStatus.ACTIVE
        self.register_agent(child)
        parent.children_ids.append(child.id)
        parent.updated_at = time.time()
        return child

    def audit_agent(self, agent_id: str, divergence_score: float) -> AgentStatus:
        agent = self.get_agent(agent_id)
        if not agent:
            raise ValueError(f"Agent {agent_id} not found.")

        agent.telemetry["divergence_score"] = divergence_score
        agent.updated_at = time.time()

        if divergence_score > 0.85:
            agent.status = AgentStatus.QUARANTINED
        elif divergence_score > 0.95:
            agent.status = AgentStatus.RECYCLED
        else:
            agent.status = AgentStatus.ACTIVE

        return agent.status

    def get_agent(self, agent_id: str) -> Optional[AgentRecord]:
        return self._agents.get(agent_id)

    def list_agents(self, tier: Optional[AgentTier] = None, status: Optional[AgentStatus] = None) -> List[Dict[str, Any]]:
        results = []
        for agent in self._agents.values():
            if tier and agent.tier != tier:
                continue
            if status and agent.status != status:
                continue
            results.append(agent.to_dict())
        return results

    def get_civilization_summary(self) -> Dict[str, Any]:
        total_agents = len(self._agents)
        tier_counts = {tier.value: len(ids) for tier, ids in self._tier_index.items()}
        status_counts = {}
        for agent in self._agents.values():
            status_counts[agent.status.value] = status_counts.get(agent.status.value, 0) + 1

        return {
            "total_agents_registered": total_agents,
            "simulated_civilization_scale": "1,000,000,000 (Target Topology)",
            "tier_distribution": tier_counts,
            "status_distribution": status_counts
        }

if __name__ == "__main__":
    registry = AgentRegistry()
    print("Agent Registry Initialized with", len(registry.list_agents()), "agents.")
