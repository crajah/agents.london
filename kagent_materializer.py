#!/usr/bin/env python3
"""
Kagent Materializer Engine for 1-Billion Agent Civilization.
Compiles abstract civilizational Agent Records into Kubernetes Custom Resource Definitions
(CRDs) using the official `kagent.dev/v1alpha2` API specifications.
"""

import json
from typing import Dict, Any, List
try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

from registry import AgentRecord, AgentTier, AgentStatus

class KagentMaterializer:
    def __init__(self, namespace: str = "kagent-civilization"):
        self.namespace = namespace

    def generate_agent_crd(self, agent: AgentRecord) -> Dict[str, Any]:
        crd_name = agent.id.lower()
        tools = []
        for cap in agent.capabilities:
            tools.append({
                "name": cap.replace("_", "-"),
                "type": "RemoteMCPServer",
                "remoteMCPServer": {
                    "url": f"http://mcp-{cap.replace('_', '-')}.{self.namespace}.svc.cluster.local:8080"
                }
            })

        crd = {
            "apiVersion": "kagent.dev/v1alpha2",
            "kind": "Agent",
            "metadata": {
                "name": crd_name,
                "namespace": self.namespace,
                "labels": {
                    "civilization.kagent.dev/tier": agent.tier.value.lower(),
                    "civilization.kagent.dev/domain": agent.domain,
                    "civilization.kagent.dev/sector": agent.sector,
                    "civilization.kagent.dev/guild": agent.guild,
                    "civilization.kagent.dev/status": agent.status.value.lower(),
                },
                "annotations": {
                    "civilization.kagent.dev/address": agent.address,
                    "civilization.kagent.dev/parent-id": agent.parent_id or "none"
                }
            },
            "spec": {
                "type": "Declarative",
                "declarative": {
                    "model": {
                        "provider": "openai",
                        "name": agent.model_name
                    },
                    "systemMessage": agent.system_prompt,
                    "tools": tools
                }
            }
        }
        return crd

    def generate_agent_policy_crd(self, agent: AgentRecord) -> Dict[str, Any]:
        crd_name = f"policy-{agent.id.lower()}"
        max_tokens = 500000 if agent.tier in [AgentTier.SOVEREIGN, AgentTier.PROCREATOR] else 50000
        sentinel_inspection = True

        crd = {
            "apiVersion": "kagent.dev/v1alpha2",
            "kind": "AgentPolicy",
            "metadata": {
                "name": crd_name,
                "namespace": self.namespace,
                "labels": {
                    "civilization.kagent.dev/target-agent": agent.id
                }
            },
            "spec": {
                "targetRef": {
                    "apiVersion": "kagent.dev/v1alpha2",
                    "kind": "Agent",
                    "name": agent.id.lower()
                },
                "governance": {
                    "maxTokenQuotaPerTask": max_tokens,
                    "sentinelTelemetryEnabled": sentinel_inspection,
                    "allowedToolTypes": ["RemoteMCPServer"],
                    "quarantineOnDivergenceThreshold": 0.85
                }
            }
        }
        return crd

    def materialize_bundle(self, agent: AgentRecord) -> str:
        agent_crd = self.generate_agent_crd(agent)
        policy_crd = self.generate_agent_policy_crd(agent)
        
        if HAS_YAML:
            return yaml.dump_all([agent_crd, policy_crd], sort_keys=False)
        else:
            return json.dumps([agent_crd, policy_crd], indent=2)

if __name__ == "__main__":
    from registry import AgentRegistry
    reg = AgentRegistry()
    mat = KagentMaterializer()
    sample = reg.get_agent(reg.list_agents()[0]["id"])
    if sample:
        print(mat.materialize_bundle(sample))
