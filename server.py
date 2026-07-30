#!/usr/bin/env python3
import os
import sys

# Ensure local directory is in python search path
SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import json
import time
import urllib.parse
from http.server import HTTPServer, SimpleHTTPRequestHandler

from registry import AgentRegistry, AgentTier, AgentStatus
from kagent_materializer import KagentMaterializer

# Global Civilization Registry Instance
registry = AgentRegistry()
materializer = KagentMaterializer()

class CivilizationRequestHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=SCRIPT_DIR, **kwargs)

    def _set_cors_headers(self, status=200, content_type="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, PUT, DELETE")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With")
        self.end_headers()

    def do_OPTIONS(self):
        self._set_cors_headers(200, "text/plain")

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/api/agents":
            self._set_cors_headers(200)
            agents = registry.list_agents()
            self.wfile.write(json.dumps({"success": True, "agents": agents}).encode('utf-8'))
            return

        elif path == "/api/summary":
            self._set_cors_headers(200)
            summary = registry.get_civilization_summary()
            self.wfile.write(json.dumps({"success": True, "summary": summary}).encode('utf-8'))
            return

        elif path == "/api/kagent/manifest":
            self._set_cors_headers(200, "text/plain")
            yaml_bundles = []
            for agent_dict in registry.list_agents():
                agent_obj = registry.get_agent(agent_dict["id"])
                if agent_obj:
                    yaml_bundles.append(materializer.materialize_bundle(agent_obj))
            manifest_output = "\n---\n".join(yaml_bundles)
            self.wfile.write(manifest_output.encode('utf-8'))
            return

        elif path in ["/ws/civilization", "/api/playground/execute"]:
            self._set_cors_headers(200)
            self.wfile.write(json.dumps({"status": "connected", "protocol": "civilization-telemetry-v1"}).encode('utf-8'))
            return

        # Serve static files for standard GET requests
        super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        
        content_length = int(self.headers.get('Content-Length', 0))
        body_bytes = self.rfile.read(content_length) if content_length > 0 else b'{}'
        
        try:
            payload = json.loads(body_bytes.decode('utf-8'))
        except Exception:
            payload = {}

        if path == "/api/procreate":
            self._set_cors_headers(200)
            name = payload.get("name", "Operative Citizen")
            tier_str = payload.get("tier", "Operative")
            domain = payload.get("domain", "engineering")
            sector = payload.get("sector", "fabrication")
            guild = payload.get("guild", "workers")
            parent_id = payload.get("parentId")
            capabilities = payload.get("capabilities", ["data_processing"])
            system_prompt = payload.get("systemPrompt", "Execute specialized domain tasks.")

            tier_enum = AgentTier.OPERATIVE
            for t in AgentTier:
                if t.value.lower() == tier_str.lower():
                    tier_enum = t
                    break

            if not parent_id:
                spawners = registry.list_agents(tier=AgentTier.PROCREATOR) or registry.list_agents(tier=AgentTier.SOVEREIGN)
                if spawners:
                    parent_id = spawners[0]["id"]
                else:
                    self.wfile.write(json.dumps({"error": "No valid parent spawner found."}).encode('utf-8'))
                    return

            try:
                child = registry.spawn_child_agent(
                    parent_id=parent_id,
                    name=name,
                    tier=tier_enum,
                    domain=domain,
                    sector=sector,
                    guild=guild,
                    capabilities=capabilities,
                    system_prompt=system_prompt
                )
                crd_bundle = materializer.materialize_bundle(child)
                self.wfile.write(json.dumps({
                    "success": True,
                    "agent": child.to_dict(),
                    "kagent_crd": crd_bundle
                }).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
            return

        elif path == "/api/audit":
            self._set_cors_headers(200)
            audit_results = []
            for agent_dict in registry.list_agents():
                agent_id = agent_dict["id"]
                divergence = agent_dict["telemetry"]["divergence_score"]
                status = registry.audit_agent(agent_id, divergence)
                audit_results.append({
                    "id": agent_id,
                    "name": agent_dict["name"],
                    "divergence_score": divergence,
                    "status": status.value
                })
            self.wfile.write(json.dumps({"success": True, "audit_results": audit_results}).encode('utf-8'))
            return

        elif path in ["/api/playground/chat", "/api/playground/execute"]:
            self._set_cors_headers(200)
            message = payload.get("message", payload.get("prompt", "Status check"))
            agent_id = payload.get("agentId", "agent-senate-prime")
            agent = registry.get_agent(agent_id)
            
            agent_name = agent.name if agent else "Civilization Sovereign"
            response_text = f"[{agent_name}] Acknowledged request: '{message}'. Enforcing Kagent policies across 1B agent namespace."
            
            self.wfile.write(json.dumps({
                "success": True,
                "response": response_text,
                "agentId": agent_id,
                "tokenUsage": 42,
                "sentinelApproved": True
            }).encode('utf-8'))
            return

        self._set_cors_headers(404)
        self.wfile.write(json.dumps({"error": "Endpoint not found"}).encode('utf-8'))

def run_server(port=8000):
    server_address = ('', port)
    httpd = HTTPServer(server_address, CivilizationRequestHandler)
    print(f"Kagent Civilization Server running on http://localhost:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server.")
        httpd.server_close()

if __name__ == "__main__":
    port = 8000
    if len(sys.argv) > 1:
        port = int(sys.argv[1])
    run_server(port)
