/**
 * agent.london Frontend Application Logic
 * Interactive Civilization Visualizer, Agent Registry, Progeny Tracking, Tool Registry, Playground, and Cryptographic Security.
 */

const API_BASE = "http://localhost:8000";
const WS_BASE = "ws://localhost:8000/ws/civilization";

// Application State
const state = {
    orgId: "org_london_meta",
    userId: "user_chandan",
    projectId: "proj_alpha_civilization",
    playgroundMode: "conductor", // "conductor", "react", "direct"
    agents: [],
    tools: [
        { tool_id: "mcp-pgvector-search", name: "pgvector Vector Search", scope_type: "org", endpoint_url: "http://localhost:8002/tools/pgvector", min_reputation_score: 50.0, input_schema: { query_vector: "list[float]" } },
        { tool_id: "mcp-redis-queue", name: "Redis Event Queue", scope_type: "project", endpoint_url: "http://localhost:8002/tools/redis", min_reputation_score: 0.0, input_schema: { channel: "str" } }
    ],
    events: [],
    wsConnected: false
};

document.addEventListener("DOMContentLoaded", () => {
    initNavigation();
    initTenancySelectors();
    initPlayground();
    initCanvasGraph();
    initModals();
    initWebSocket();
    fetchCivilizationData();
});

function initNavigation() {
    const navItems = document.querySelectorAll(".nav-item");
    const viewPanels = document.querySelectorAll(".view-panel");

    navItems.forEach(item => {
        item.addEventListener("click", () => {
            navItems.forEach(n => n.classList.remove("active"));
            viewPanels.forEach(p => p.classList.remove("active"));

            item.classList.add("active");
            const targetId = item.getAttribute("data-target");
            const targetPanel = document.getElementById(targetId);
            if (targetPanel) {
                targetPanel.classList.add("active");
            }
        });
    });
}

function initTenancySelectors() {
    const selectOrg = document.getElementById("select_org");
    const selectUser = document.getElementById("select_user");
    const selectProject = document.getElementById("select_project");

    if (selectOrg) {
        selectOrg.addEventListener("change", (e) => {
            state.orgId = e.target.value;
            fetchCivilizationData();
        });
    }
    if (selectUser) {
        selectUser.addEventListener("change", (e) => {
            state.userId = e.target.value;
        });
    }
    if (selectProject) {
        selectProject.addEventListener("change", (e) => {
            state.projectId = e.target.value;
            fetchCivilizationData();
        });
    }
}

function initPlayground() {
    const btnConductor = document.getElementById("btn_mode_conductor");
    const btnReact = document.getElementById("btn_mode_react");
    const btnDirect = document.getElementById("btn_mode_direct");
    const modeTitle = document.getElementById("playground_mode_title");
    const btnRun = document.getElementById("btn_run_playground");
    const inputPrompt = document.getElementById("input_playground_prompt");

    const setMode = (mode, title, btn) => {
        state.playgroundMode = mode;
        [btnConductor, btnReact, btnDirect].forEach(b => b && b.classList.remove("active", "btn-primary"));
        [btnConductor, btnReact, btnDirect].forEach(b => b && b.classList.add("btn-outline"));
        if (btn) {
            btn.classList.remove("btn-outline");
            btn.classList.add("btn-primary", "active");
        }
        if (modeTitle) modeTitle.textContent = title;
    };

    if (btnConductor) btnConductor.addEventListener("click", () => setMode("conductor", "Conductor Multi-Agent Composition Mode", btnConductor));
    if (btnReact) btnReact.addEventListener("click", () => setMode("react", "ReAct Reasoning + Acting Loop Mode", btnReact));
    if (btnDirect) btnDirect.addEventListener("click", () => setMode("direct", "Direct Agent Message Mode", btnDirect));

    if (btnRun && inputPrompt) {
        btnRun.addEventListener("click", async () => {
            const prompt = inputPrompt.value.trim();
            if (!prompt) return;

            appendStepCard("user", "USER GOAL", prompt);
            inputPrompt.value = "";

            try {
                const res = await fetch(`${API_BASE}/api/playground/chat`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        org_id: state.orgId,
                        project_id: state.projectId,
                        user_id: state.userId,
                        mode: state.playgroundMode,
                        prompt: prompt
                    })
                });
                const data = await res.json();
                handlePlaygroundResponse(data);
            } catch (e) {
                appendStepCard("system", "ERROR", "Failed to execute playground goal: " + e.message);
            }
        });
    }
}

function handlePlaygroundResponse(data) {
    if (data.steps) {
        data.steps.forEach(s => {
            appendStepCard(s.type.toLowerCase(), s.type, s.content);
        });
    } else if (data.sub_tasks_orchestrated) {
        appendStepCard("conductor", "ORCHESTRATION PLAN", `Conductor discovered ${data.discovered_agent_contexts ? data.discovered_agent_contexts.length : 0} agents via RAG. Delegated ${data.sub_tasks_orchestrated.length} sub-tasks.`);
        data.sub_tasks_orchestrated.forEach(st => {
            appendStepCard("action", `SUB-TASK ${st.step}`, `${st.sub_task} -> Assigned to: ${st.assigned_to}`);
        });
    } else if (data.answer) {
        appendStepCard("final_answer", "DIRECT ANSWER", data.answer);
    }
}

function appendStepCard(type, label, content) {
    const consoleBox = document.getElementById("playground_steps_console");
    if (!consoleBox) return;

    const card = document.createElement("div");
    card.className = `step-card ${type}`;
    card.innerHTML = `
        <span class="step-label">${label}</span>
        <div class="step-content">${content}</div>
    `;
    consoleBox.appendChild(card);
    consoleBox.scrollTop = consoleBox.scrollHeight;
}

let canvas, ctx;
let graphNodes = [];

function initCanvasGraph() {
    canvas = document.getElementById("civilization_canvas");
    if (!canvas) return;
    ctx = canvas.getContext("2d");

    resizeCanvas();
    window.addEventListener("resize", resizeCanvas);

    setupDefaultNodes();
    requestAnimationFrame(renderGraphLoop);
}

function resizeCanvas() {
    if (!canvas) return;
    const container = canvas.parentElement;
    canvas.width = container.clientWidth;
    canvas.height = container.clientHeight;
}

function setupDefaultNodes() {
    const w = canvas ? canvas.width : 800;
    const h = canvas ? canvas.height : 400;

    graphNodes = [
        { id: "genesis", name: "GenesisNode", caste: "genesis", x: w * 0.5, y: h * 0.15, vx: 0, vy: 0 },
        { id: "archivist", name: "OntologicalRegistry", caste: "archivist", x: w * 0.25, y: h * 0.4, vx: 0, vy: 0 },
        { id: "arbiter", name: "ResourceArbiter", caste: "economist", x: w * 0.75, y: h * 0.4, vx: 0, vy: 0 },
        { id: "judicature", name: "JudicatureNode", caste: "judicature", x: w * 0.5, y: h * 0.4, vx: 0, vy: 0 },
        { id: "creator", name: "AgentCreator", caste: "architect", x: w * 0.2, y: h * 0.65, vx: 0, vy: 0 },
        { id: "conductor", name: "ConductorAgent", caste: "architect", x: w * 0.4, y: h * 0.65, vx: 0, vy: 0 },
        { id: "react", name: "ReActAgent", caste: "task_workforce", x: w * 0.6, y: h * 0.65, vx: 0, vy: 0 },
        { id: "inspector", name: "InspectorAgent", caste: "auditor", x: w * 0.8, y: h * 0.65, vx: 0, vy: 0 },
        { id: "worker1", name: "DataWorker-Alpha", caste: "task_workforce", parentId: "creator", x: w * 0.3, y: h * 0.88, vx: 0, vy: 0 },
        { id: "worker2", name: "RAGSynthesizer", caste: "task_workforce", parentId: "conductor", x: w * 0.5, y: h * 0.88, vx: 0, vy: 0 }
    ];
}

function renderGraphLoop() {
    if (!ctx || !canvas) return;

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    ctx.strokeStyle = "rgba(255, 255, 255, 0.03)";
    ctx.lineWidth = 1;
    const step = 40;
    for (let x = 0; x < canvas.width; x += step) {
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, canvas.height);
        ctx.stroke();
    }
    for (let y = 0; y < canvas.height; y += step) {
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(canvas.width, y);
        ctx.stroke();
    }

    const gen = graphNodes.find(n => n.caste === "genesis");
    const jud = graphNodes.find(n => n.caste === "judicature");
    const arc = graphNodes.find(n => n.caste === "archivist");
    const eco = graphNodes.find(n => n.caste === "economist");

    if (gen && jud) drawEdge(gen, jud, "CONSTITUTION");
    if (gen && arc) drawEdge(gen, arc, "PROVENANCE");
    if (gen && eco) drawEdge(gen, eco, "TOKENS");

    graphNodes.filter(n => n.caste === "task_workforce").forEach(worker => {
        const parent = graphNodes.find(p => p.id === worker.parentId) || graphNodes.find(p => p.caste === "architect");
        if (parent) drawEdge(parent, worker, "PROGENY");
    });

    graphNodes.forEach(node => {
        drawNode(node);
    });

    requestAnimationFrame(renderGraphLoop);
}

function drawEdge(fromNode, toNode, label, isDashed = false) {
    ctx.save();
    ctx.beginPath();
    if (isDashed) ctx.setLineDash([4, 4]);
    ctx.moveTo(fromNode.x, fromNode.y);
    ctx.lineTo(toNode.x, toNode.y);
    ctx.strokeStyle = isDashed ? "rgba(245, 158, 11, 0.4)" : "rgba(59, 130, 246, 0.3)";
    ctx.lineWidth = 2;
    ctx.stroke();
    ctx.restore();
}

function drawNode(node) {
    ctx.save();

    let color = "#3b82f6";
    if (node.caste === "genesis") color = "#f59e0b";
    if (node.caste === "archivist") color = "#6366f1";
    if (node.caste === "economist") color = "#10b981";
    if (node.caste === "judicature") color = "#8b5cf6";
    if (node.caste === "architect") color = "#3b82f6";
    if (node.caste === "auditor") color = "#ef4444";
    if (node.caste === "task_workforce") color = "#64748b";

    ctx.shadowColor = color;
    ctx.shadowBlur = 12;

    ctx.beginPath();
    ctx.arc(node.x, node.y, 16, 0, Math.PI * 2);
    ctx.fillStyle = color;
    ctx.fill();

    ctx.strokeStyle = "#ffffff";
    ctx.lineWidth = 2;
    ctx.stroke();

    ctx.shadowBlur = 0;
    ctx.fillStyle = "#f8fafc";
    ctx.font = "12px 'Inter', sans-serif";
    ctx.textAlign = "center";
    ctx.fillText(node.name, node.x, node.y + 32);

    ctx.restore();
}

function initWebSocket() {
    try {
        const ws = new WebSocket(WS_BASE);
        ws.onopen = () => {
            state.wsConnected = true;
            updateStatusDot(true);
        };
        ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            handleWsMessage(data);
        };
        ws.onclose = () => {
            state.wsConnected = false;
            updateStatusDot(false);
        };
    } catch (e) {
        updateStatusDot(false);
    }
}

function updateStatusDot(connected) {
    const dot = document.getElementById("ws_status_dot");
    const text = document.getElementById("ws_status_text");
    if (dot && text) {
        if (connected) {
            dot.classList.add("active");
            text.textContent = "Redis Bus Connected";
        } else {
            dot.classList.remove("active");
            text.textContent = "Bus Standby Mode";
        }
    }
}

function handleWsMessage(data) {
    if (data.type === "agent_materialized") {
        const newAgent = data.data;
        appendEventLog("MATERIALIZED", `Worker Agent '${newAgent.name}' (PubKeys: ${newAgent.public_key || 'ed25519:verified'}) materialized.`);
        fetchCivilizationData();
    } else if (data.type === "react_completed") {
        appendEventLog("REACT", `ReAct Loop completed for prompt: '${data.data.user_prompt}'`);
    } else if (data.type === "conductor_completed") {
        appendEventLog("CONDUCTOR", `Conductor Orchestration completed for prompt: '${data.data.task_prompt}'`);
    }
}

function initModals() {
    const modal = document.getElementById("modal_materialize_agent");
    const btnOpen = document.getElementById("btn_open_materialize_modal");
    const btnOpenTop = document.getElementById("btn_spawn_agent_top");
    const btnClose = document.getElementById("btn_close_materialize_modal");
    const btnCancel = document.getElementById("btn_cancel_materialize");
    const btnSubmit = document.getElementById("btn_submit_materialize");

    const openModal = () => {
        populateParentDropdown();
        modal && modal.classList.add("active");
    };
    const closeModal = () => modal && modal.classList.remove("active");

    if (btnOpen) btnOpen.addEventListener("click", openModal);
    if (btnOpenTop) btnOpenTop.addEventListener("click", openModal);
    if (btnClose) btnClose.addEventListener("click", closeModal);
    if (btnCancel) btnCancel.addEventListener("click", closeModal);

    if (btnSubmit) {
        btnSubmit.addEventListener("click", async () => {
            const name = document.getElementById("input_agent_name").value;
            const parentId = document.getElementById("select_parent_agent").value;
            const prompt = document.getElementById("input_system_prompt").value;
            const toolsRaw = document.getElementById("input_agent_tools").value;

            if (!name || !prompt) {
                alert("Agent Name and System Prompt are required.");
                return;
            }

            const tools = toolsRaw ? toolsRaw.split(",").map(t => t.trim()) : [];

            try {
                const res = await fetch(`${API_BASE}/api/agents/materialize`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        org_id: state.orgId,
                        project_id: state.projectId,
                        user_id: state.userId,
                        agent_name: name,
                        parent_agent_id: parentId,
                        system_prompt: prompt,
                        tools: tools
                    })
                });
                const data = await res.json();
                closeModal();
                appendEventLog("MATERIALIZED", `Progeny Worker Agent '${name}' materialized with ED25519 Keypair & SHA-256 Digest.`);
                fetchCivilizationData();
            } catch (e) {
                alert("Failed to materialize agent: " + e.message);
            }
        });
    }
}

function populateParentDropdown() {
    const select = document.getElementById("select_parent_agent");
    if (!select) return;

    const parents = [
        { id: `creator-${state.projectId}`, name: `AgentCreator-${state.projectId}` },
        { id: `conductor-${state.projectId}`, name: `ConductorAgent-${state.projectId}` },
        { id: `react-${state.projectId}`, name: `ReActAgent-${state.projectId}` }
    ];

    select.innerHTML = parents.map(p => `<option value="${p.id}">${p.name}</option>`).join("");
}

async function fetchCivilizationData() {
    renderAgentCards();
    renderToolTable();
}

function renderAgentCards() {
    const grid = document.getElementById("agent_cards_grid");
    if (!grid) return;

    const primeAgents = [
        { agent_id: `genesis-${state.projectId}`, name: `GenesisNode-${state.projectId}`, caste: "genesis", telos: "Root authority initializing civilizational infrastructure.", pubkey: "ed25519:genesis_root_99a", tokens: 5000, rep: 100 },
        { agent_id: `archivist-${state.projectId}`, name: `OntologicalRegistry-${state.projectId}`, caste: "archivist", telos: "Universal agent ledger & cryptographic identity tracking.", pubkey: "ed25519:archivist_ledger_42b", tokens: 3000, rep: 100 },
        { agent_id: `arbiter-${state.projectId}`, name: `ResourceArbiter-${state.projectId}`, caste: "economist", telos: "Utility token bank & compute credit allocations.", pubkey: "ed25519:arbiter_bank_77c", tokens: 10000, rep: 100 },
        { agent_id: `judicature-${state.projectId}`, name: `JudicatureNode-${state.projectId}`, caste: "judicature", telos: "Constitutional law enforcement & dispute resolution.", pubkey: "ed25519:judicature_law_88d", tokens: 4000, rep: 100 },
        { agent_id: `creator-${state.projectId}`, name: `AgentCreator-${state.projectId}`, caste: "architect", telos: "Materializes custom worker agents via Kagent.", pubkey: "ed25519:creator_builder_11e", tokens: 2000, rep: 98 },
        { agent_id: `inspector-${state.projectId}`, name: `InspectorAgent-${state.projectId}`, caste: "auditor", telos: "Audits worker outputs & verifies signature compliance.", pubkey: "ed25519:inspector_audit_33f", tokens: 1500, rep: 100 },
        { agent_id: `conductor-${state.projectId}`, name: `ConductorAgent-${state.projectId}`, caste: "architect", telos: "Queries Agent RAG source to orchestrate collaborators.", pubkey: "ed25519:conductor_rag_55g", tokens: 2500, rep: 95 },
        { agent_id: `react-${state.projectId}`, name: `ReActAgent-${state.projectId}`, caste: "task_workforce", telos: "Executes Thought -> Action -> Observation reasoning loops.", pubkey: "ed25519:react_loop_66h", tokens: 1200, rep: 92 }
    ];

    grid.innerHTML = primeAgents.map(a => `
        <div class="card agent-card">
            <span class="card-role-badge ${a.caste}">${a.caste.toUpperCase()}</span>
            <h3>${a.name}</h3>
            <p style="font-size: 0.85rem; color: var(--text-secondary); margin: 6px 0;"><strong>Telos:</strong> ${a.telos}</p>
            <div style="font-size: 0.75rem; color: var(--text-muted); display: flex; flex-direction: column; gap: 4px; margin-top: 8px;">
                <span>Public Key: <code>${a.pubkey}</code></span>
                <span>Utility Tokens: <strong style="color: #10b981;">${a.tokens} CR</strong></span>
                <span>Reputation Score: <strong style="color: #3b82f6;">${a.rep}/100</strong></span>
            </div>
        </div>
    `).join("");
}

function renderToolTable() {
    const tbody = document.getElementById("tbody_tools");
    if (!tbody) return;

    tbody.innerHTML = state.tools.map(t => `
        <tr>
            <td><code>${t.tool_id}</code></td>
            <td><strong>${t.name}</strong></td>
            <td><span class="card-role-badge worker">${t.scope_type.toUpperCase()}</span></td>
            <td><code>${t.endpoint_url}</code></td>
            <td><code>${JSON.stringify(t.input_schema)}</code></td>
            <td><button class="btn btn-outline" style="padding: 2px 8px; font-size: 0.75rem;">Inspect</button></td>
        </tr>
    `).join("");
}

function appendEventLog(tag, msg) {
    const list = document.getElementById("event_log_list");
    if (!list) return;

    const timeStr = new Date().toLocaleTimeString();
    const item = document.createElement("div");
    item.className = "event-log-item info";
    item.innerHTML = `
        <span class="time">${timeStr}</span>
        <span class="tag">${tag}</span>
        <span class="msg">${msg}</span>
    `;
    list.prepend(item);
}
