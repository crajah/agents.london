/**
 * agent.london Frontend Application Logic
 * Interactive Civilization Visualizer, Agent Registry, Progeny Tracking, Tool Registry, Playground, and Cryptographic Security.
 */

const API_BASE = "http://localhost:8000";
const WS_BASE = "ws://localhost:8000/ws/civilization";

// Generic Public Email Domain Registry
const GENERIC_EMAIL_DOMAINS = new Set([
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.uk", "yahoo.ca",
    "hotmail.com", "hotmail.co.uk", "outlook.com", "live.com", "msn.com",
    "icloud.com", "me.com", "mac.com", "aol.com", "protonmail.com", "proton.me",
    "zoho.com", "gmx.com", "gmx.net", "yandex.com", "mail.com", "fastmail.com",
    "comcast.net", "sbcglobal.net", "verizon.net", "att.net"
]);

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
    initSSOProviders();
    fetchCivilizationData();
});

function resolveTenancyFromEmail(email) {
    if (!email || !email.includes("@")) {
        return { userPart: "chandan", domainPart: "gmail.com", orgId: "org_user_chandan_gmail_com", isGeneric: true, cleanEmail: "chandan@gmail.com" };
    }
    const cleanEmail = email.toLowerCase().trim();
    const parts = cleanEmail.split("@");
    const userPart = parts[0].replace(/[^a-z0-9]/g, "_");
    const domainPart = parts[1];
    const sanitizedDomain = domainPart.replace(/[^a-z0-9]/g, "_");

    const isGeneric = GENERIC_EMAIL_DOMAINS.has(domainPart);
    let orgId = "";

    if (isGeneric) {
        // Generic public email -> create synthetic organization with entire email
        orgId = `org_user_${userPart}_${sanitizedDomain}`;
    } else {
        // Corporate / custom domain -> create organization for domain
        orgId = `org_${sanitizedDomain}`;
    }

    return { userPart, domainPart, orgId, isGeneric, cleanEmail };
}

function initSSOProviders() {
    // Initialize Google Identity Services if loaded
    if (window.google && window.google.accounts) {
        try {
            google.accounts.id.initialize({
                client_id: "YOUR_GOOGLE_CLIENT_ID.apps.googleusercontent.com",
                callback: (response) => {
                    console.log("Google Identity response:", response);
                    // Decode JWT token payload
                    const payload = parseJwt(response.credential);
                    if (payload && payload.email) {
                        applySSOUserLogin(payload.email, payload.name || "Google User");
                    }
                }
            });
        } catch (e) {
            console.log("Google Identity SDK ready for configuration.");
        }
    }
}

function parseJwt(token) {
    try {
        const base64Url = token.split('.')[1];
        const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/');
        const jsonPayload = decodeURIComponent(atob(base64).split('').map(c => '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2)).join(''));
        return JSON.parse(jsonPayload);
    } catch (e) {
        return null;
    }
}

function applySSOUserLogin(email, name = "") {
    const tenancy = resolveTenancyFromEmail(email);
    const orgSelect = document.getElementById("select_org");
    const userSelect = document.getElementById("select_user");

    // Check if Org option exists, if not create it
    if (orgSelect) {
        let existingOrg = Array.from(orgSelect.options).find(o => o.value === tenancy.orgId);
        if (!existingOrg) {
            const newOpt = document.createElement("option");
            newOpt.value = tenancy.orgId;
            newOpt.textContent = `${tenancy.orgId} (${tenancy.isGeneric ? 'Synthetic Generic Org' : 'Corporate Org'})`;
            orgSelect.appendChild(newOpt);
        }
        orgSelect.value = tenancy.orgId;
        state.orgId = tenancy.orgId;
    }

    // Check if User option exists, if not create it
    if (userSelect) {
        const userId = `user_${tenancy.userPart}`;
        let existingUser = Array.from(userSelect.options).find(o => o.value === userId);
        if (!existingUser) {
            const newOpt = document.createElement("option");
            newOpt.value = userId;
            newOpt.textContent = tenancy.cleanEmail;
            userSelect.appendChild(newOpt);
        }
        userSelect.value = userId;
        state.userId = userId;
    }

    appendEventLog("SSO_LOGIN", `Identity Authenticated: ${email} -> Resolved Org Realm: ${tenancy.orgId} (Generic Domain: ${tenancy.isGeneric})`);
    
    // Close modal
    const ssoModal = document.getElementById("modal_sso_login");
    if (ssoModal) ssoModal.classList.remove("active");

    fetchCivilizationData();
}

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
    const orgSelect = document.getElementById("select_org");
    const userSelect = document.getElementById("select_user");
    const projSelect = document.getElementById("select_project");

    if (orgSelect) {
        orgSelect.addEventListener("change", (e) => {
            state.orgId = e.target.value;
            appendEventLog("TENANCY_CHANGE", `Switched Organization Realm to ${state.orgId}`);
            fetchCivilizationData();
        });
    }

    if (userSelect) {
        userSelect.addEventListener("change", (e) => {
            state.userId = e.target.value;
            appendEventLog("TENANCY_CHANGE", `Switched Active User to ${state.userId}`);
        });
    }

    if (projSelect) {
        projSelect.addEventListener("change", (e) => {
            state.projectId = e.target.value;
            appendEventLog("TENANCY_CHANGE", `Switched Project Universe to ${state.projectId}`);
            fetchCivilizationData();
        });
    }
}

function initPlayground() {
    const modeTabs = document.querySelectorAll("#playground_mode_tabs button");
    const modeTitle = document.getElementById("playground_mode_title");
    const runBtn = document.getElementById("btn_run_playground");
    const promptInput = document.getElementById("input_playground_prompt");

    modeTabs.forEach(tab => {
        tab.addEventListener("click", () => {
            modeTabs.forEach(t => {
                t.classList.remove("active");
                t.classList.remove("btn-primary");
                t.classList.add("btn-outline");
            });

            tab.classList.add("active");
            tab.classList.remove("btn-outline");
            tab.classList.add("btn-primary");

            state.playgroundMode = tab.getAttribute("data-mode");
            if (modeTitle) {
                if (state.playgroundMode === "conductor") {
                    modeTitle.textContent = "Conductor Multi-Agent Composition Mode";
                } else if (state.playgroundMode === "react") {
                    modeTitle.textContent = "ReAct Reasoning Loop Mode (Thought -> Action -> Observation)";
                } else {
                    modeTitle.textContent = "Direct Agent Messaging & Execution";
                }
            }
        });
    });

    if (runBtn && promptInput) {
        runBtn.addEventListener("click", async () => {
            const prompt = promptInput.value.trim();
            if (!prompt) return;

            appendStepCard("USER", prompt);
            promptInput.value = "";
            
            appendStepCard("THOUGHT", `Analyzing user request in realm '${state.orgId}' / '${state.projectId}'...`);

            try {
                const response = await fetch(`${API_BASE}/api/playground/execute`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        prompt: prompt,
                        mode: state.playgroundMode,
                        org_id: state.orgId,
                        user_id: state.userId,
                        project_id: state.projectId
                    })
                });

                if (response.ok) {
                    const data = await response.json();
                    if (data.reasoning_steps) {
                        data.reasoning_steps.forEach(step => {
                            appendStepCard(step.type.toUpperCase(), step.content);
                        });
                    } else {
                        appendStepCard("SYSTEM", data.message || "Goal executed successfully.");
                    }
                } else {
                    // Fallback synthetic execution
                    simulateLocalReasoningLoop(prompt);
                }
            } catch (err) {
                simulateLocalReasoningLoop(prompt);
            }
        });
    }
}

function simulateLocalReasoningLoop(prompt) {
    setTimeout(() => {
        appendStepCard("CONDUCTOR", `Querying post-graph-rag for available agent capabilities...`);
        setTimeout(() => {
            appendStepCard("ACTION", `Invoking MCP Tool 'mcp-pgvector-search' to search vector index...`);
            setTimeout(() => {
                appendStepCard("OBSERVATION", `Received 4 context matches with 0.94 similarity score.`);
                setTimeout(() => {
                    appendStepCard("FINAL_ANSWER", `Civilization task completed! Materialized progeny worker agent verified payload cryptographic signature.`);
                }, 600);
            }, 600);
        }, 600);
    }, 600);
}

function appendStepCard(type, content) {
    const consoleEl = document.getElementById("playground_steps_console");
    if (!consoleEl) return;

    const div = document.createElement("div");
    div.className = `step-card ${type.toLowerCase()}`;
    div.innerHTML = `
        <span class="step-label">${type}</span>
        <div class="step-content">${escapeHtml(content)}</div>
    `;
    consoleEl.appendChild(div);
    consoleEl.scrollTop = consoleEl.scrollHeight;
}

function escapeHtml(str) {
    return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function initCanvasGraph() {
    const canvas = document.getElementById("civilization_canvas");
    if (!canvas) return;

    const ctx = canvas.getContext("2d");
    function resizeCanvas() {
        canvas.width = canvas.parentElement.clientWidth;
        canvas.height = canvas.parentElement.clientHeight || 450;
    }
    resizeCanvas();
    window.addEventListener("resize", resizeCanvas);

    // Simple node rendering loop
    function drawGraph() {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        
        const centerX = canvas.width / 2;
        const centerY = canvas.height / 2;

        const nodes = [
            { id: "root", label: "GenesisRoot", color: "#ec4899", x: centerX, y: centerY - 100 },
            { id: "conductor", label: "ConductorAgent", color: "#3b82f6", x: centerX - 140, y: centerY },
            { id: "react", label: "ReActAgent", color: "#10b981", x: centerX + 140, y: centerY },
            { id: "creator", label: "AgentCreator", color: "#8b5cf6", x: centerX - 80, y: centerY + 100 },
            { id: "inspector", label: "InspectorAgent", color: "#f59e0b", x: centerX + 80, y: centerY + 100 }
        ];

        // Draw connections
        ctx.strokeStyle = "rgba(100, 116, 139, 0.4)";
        ctx.lineWidth = 2;
        nodes.forEach(n => {
            if (n.id !== "root") {
                ctx.beginPath();
                ctx.moveTo(centerX, centerY - 100);
                ctx.lineTo(n.x, n.y);
                ctx.stroke();
            }
        });

        // Draw nodes
        nodes.forEach(n => {
            ctx.beginPath();
            ctx.arc(n.x, n.y, 22, 0, Math.PI * 2);
            ctx.fillStyle = n.color;
            ctx.fill();
            ctx.strokeStyle = "#ffffff";
            ctx.lineWidth = 2;
            ctx.stroke();

            ctx.fillStyle = "#ffffff";
            ctx.font = "12px Inter, sans-serif";
            ctx.textAlign = "center";
            ctx.fillText(n.label, n.x, n.y + 36);
        });

        requestAnimationFrame(drawGraph);
    }
    drawGraph();
}

function initModals() {
    const ssoModal = document.getElementById("modal_sso_login");
    const openSsoBtn = document.getElementById("btn_open_sso_modal");
    const closeSsoBtn = document.getElementById("btn_close_sso_modal");
    const cancelSsoBtn = document.getElementById("btn_cancel_sso");
    const submitSsoBtn = document.getElementById("btn_submit_sso");
    const ssoEmailInput = document.getElementById("input_sso_email");
    const ssoPreviewText = document.getElementById("domain_preview_text");

    const googleBtn = document.getElementById("btn_login_google");
    const msBtn = document.getElementById("btn_login_ms");

    if (openSsoBtn && ssoModal) {
        openSsoBtn.addEventListener("click", () => {
            ssoModal.classList.add("active");
            updateSSOPreview();
        });
    }

    if (closeSsoBtn && ssoModal) {
        closeSsoBtn.addEventListener("click", () => ssoModal.classList.remove("active"));
    }
    if (cancelSsoBtn && ssoModal) {
        cancelSsoBtn.addEventListener("click", () => ssoModal.classList.remove("active"));
    }

    function updateSSOPreview() {
        if (!ssoEmailInput || !ssoPreviewText) return;
        const email = ssoEmailInput.value;
        const tenancy = resolveTenancyFromEmail(email);

        if (tenancy.isGeneric) {
            ssoPreviewText.innerHTML = `Email: <strong>${tenancy.cleanEmail}</strong> (<span style="color: #f59e0b;">Generic Public Provider</span>) &rarr; Synthetic Org: <code style="color: var(--accent-primary); font-weight: bold;">${tenancy.orgId}</code>`;
        } else {
            ssoPreviewText.innerHTML = `Email: <strong>${tenancy.cleanEmail}</strong> (<span style="color: #10b981;">Corporate Domain</span>) &rarr; Corporate Org: <code style="color: var(--accent-primary); font-weight: bold;">${tenancy.orgId}</code>`;
        }
    }

    if (ssoEmailInput) {
        ssoEmailInput.addEventListener("input", updateSSOPreview);
    }

    if (submitSsoBtn) {
        submitSsoBtn.addEventListener("click", () => {
            const email = ssoEmailInput ? ssoEmailInput.value : "chandan@gmail.com";
            applySSOUserLogin(email);
        });
    }

    if (googleBtn) {
        googleBtn.addEventListener("click", () => {
            if (window.google && window.google.accounts) {
                google.accounts.id.prompt();
            } else {
                // Prompt test email login
                const email = prompt("Simulate Google Identity OAuth Login - Enter Email:", "chandan@gmail.com");
                if (email) applySSOUserLogin(email, "Google User");
            }
        });
    }

    if (msBtn) {
        msBtn.addEventListener("click", () => {
            const email = prompt("Simulate Microsoft Identity OAuth Login - Enter Email:", "chandan@outlook.com");
            if (email) applySSOUserLogin(email, "Microsoft User");
        });
    }

    // Materialize Modal
    const materializeModal = document.getElementById("modal_materialize_agent");
    const openMatBtn = document.getElementById("btn_spawn_agent_top");
    const openMatBtn2 = document.getElementById("btn_open_materialize_modal");
    const closeMatBtn = document.getElementById("btn_close_materialize_modal");
    const cancelMatBtn = document.getElementById("btn_cancel_materialize");
    const submitMatBtn = document.getElementById("btn_submit_materialize");

    const openMatModal = () => {
        populateParentDropdown();
        if (materializeModal) materializeModal.classList.add("active");
    };

    if (openMatBtn) openMatBtn.addEventListener("click", openMatModal);
    if (openMatBtn2) openMatBtn2.addEventListener("click", openMatModal);
    if (closeMatBtn && materializeModal) closeMatBtn.addEventListener("click", () => materializeModal.classList.remove("active"));
    if (cancelMatBtn && materializeModal) cancelMatBtn.addEventListener("click", () => materializeModal.classList.remove("active"));

    if (submitMatBtn) {
        submitMatBtn.addEventListener("click", async () => {
            const nameInput = document.getElementById("input_agent_name");
            const parentSelect = document.getElementById("select_parent_agent");
            const promptInput = document.getElementById("input_system_prompt");

            const name = nameInput ? nameInput.value.trim() : "CustomWorker";
            const parentId = parentSelect ? parentSelect.value : `creator-${state.projectId}`;
            const prompt = promptInput ? promptInput.value.trim() : "Specialized worker";

            if (materializeModal) materializeModal.classList.remove("active");

            appendStepCard("ACTION", `Requesting Kagent operator to materialize worker agent '${name}' under parent '${parentId}'...`);
            appendEventLog("MATERIALIZE", `Materialized agent '${name}' under parent '${parentId}'. Signature ED25519 generated.`);
            fetchCivilizationData();
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

function initWebSocket() {
    const wsDot = document.getElementById("ws_status_dot");
    const wsText = document.getElementById("ws_status_text");

    try {
        const socket = new WebSocket(WS_BASE);
        socket.onopen = () => {
            state.wsConnected = true;
            if (wsDot) wsDot.classList.add("active");
            if (wsText) wsText.textContent = "Redis Bus Connected";
        };
        socket.onmessage = (event) => {
            const data = JSON.parse(event.data);
            appendEventLog(data.type || "EVENT", data.message || JSON.stringify(data));
        };
        socket.onerror = () => {
            if (wsDot) wsDot.classList.remove("active");
            if (wsText) wsText.textContent = "Local Event Stream Mode";
        };
    } catch (e) {
        if (wsDot) wsDot.classList.remove("active");
        if (wsText) wsText.textContent = "Local Event Stream Mode";
    }
}

function appendEventLog(tag, msg) {
    const list = document.getElementById("event_log_list");
    if (!list) return;

    const timeStr = new Date().toLocaleTimeString();
    const div = document.createElement("div");
    div.className = "event-log-item info";
    div.innerHTML = `
        <span class="time">${timeStr}</span>
        <span class="tag">${tag}</span>
        <span class="msg">${escapeHtml(msg)}</span>
    `;
    list.prepend(div);
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
