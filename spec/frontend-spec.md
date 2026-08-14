# The frontend

Specification for the agent.london web client (`frontend/`). React 18 with
Material UI, built by Vite, served as static assets and proxied to the backend
at `/api` and `/ws`.

Companion to the three service specifications, which own the data this client
displays:

- `agent-graph-spec.md` — agents, pipelines, runs, discovery
- `tool-registry-spec.md` — the MCP tools an agent may call
- `document-registry-spec.md` — the corpus agents retrieve over

Rule references of the form "AG Rule 7.4" point at those documents. Rules here
are numbered `F.x` so they can be cited from a commit message or an issue
without ambiguity.

Status: partially implemented. §14 records what is true today, including the
behaviours that contradict the rules below.

---

## 1. What the frontend is, and is not

It is a **window onto the registries**. Every agent, tool, document, pipeline
and run it shows exists in the graph, was put there through the backend, and
can be inspected there. The client renders, navigates and composes; it does not
own state that nothing else knows about.

That framing decides most of what follows. Three consequences:

1. **The frontend has no private truth.** Anything it displays should be
   answerable by an API call a person could make with `curl`. A panel that can
   only be explained by reading the client's source is a panel showing
   something the system does not actually believe.
2. **It must never manufacture a result.** The registries are careful never to
   invent a tool result, a run outcome or a retrieval (AG Rule 7.2,
   document-registry Rule 5.3). A client that fabricates on their behalf undoes
   that work at the last possible moment, in the one place a user will believe
   it.
3. **It is multi-tenant.** Every request carries an organisation and a project,
   because the services keep organisations in separate PostgreSQL schemas
   (AG §2). A call that omits them does not fail — it reads someone else's
   realm, or an empty one, and looks like a system with no data in it.

### 1.1 Non-goals

Not specified here: visual design beyond the tokens in §12, marketing pages,
the Kubernetes deployment, or the backend's own API contract (that belongs to
the service specifications). This document covers what the client must *do*.

---

## 2. The shell

One page. No router — the view is a value in component state, and the browser
URL does not change.

```
┌──────────────────────────────────────────────────────────────┐
│ Header      org · user · project · BYOM · theme · logout     │
├──────────────────────────────────────────────────────────────┤
│ ProjectTabsBar   project universes · API key                 │
├──────────┬───────────────────────────────────────────────────┤
│ Sidebar  │ Active view                                       │
│ 9 views  │                                                   │
└──────────┴───────────────────────────────────────────────────┘
```

**Rule F.1** — The shell renders only after authentication. Before it, the
whole application is replaced by the lock screen (§3), not merely overlaid: a
dashboard rendered behind a modal has already fetched a tenant's data.

**Rule F.2** — The current view is one of nine ids, and the set is closed:
`chatbot`, `playground`, `discovery`, `civilization`, `agents`, `tools`,
`documents`, `sessions`, `guardrails`. Adding a view means adding it to the
sidebar, the switch, and §5 of this document — three places on purpose, so a
view cannot exist without a stated purpose.

**Rule F.3** — The view survives a project switch. Changing project reloads the
data in the current panel; it does not navigate the user somewhere else. Losing
someone's place because they changed context is the fastest way to make context
switching feel expensive.

### 2.1 Deep links

**Rule F.4** — The active view and the project belong in the URL. They are not
there today, and the cost is concrete: a user cannot send a colleague a link to
a document space, a run, or an agent, and a refresh always lands back on the
chatbot. This is stated as a rule rather than a wish because every panel below
already has a natural address (`/projects/{project}/agents/{agent_id}`), and
retrofitting one later means revisiting all nine.

---

## 3. Identity and tenancy

Three ways in, all resolving to the same session shape:

| Route | How |
| :--- | :--- |
| Google | Google Identity Services, verified server-side |
| Microsoft | OAuth2 authorisation code + PKCE, exchanged server-side |
| Email | An address typed into the lock screen |

```jsonc
{
  "email": "alice@example.com",
  "orgId": "org_example_com",   // derived, §3.1
  "userId": "user_alice",
  "isGeneric": false            // a consumer mailbox, §3.1
}
```

### 3.1 How an organisation is derived

The email domain decides the tenant:

- a **corporate** domain becomes one shared organisation, `org_{domain}`, so
  everyone at a company lands in the same realm;
- a **generic** domain — gmail, outlook, icloud and the rest — becomes a
  personal organisation, `org_user_{user}_{domain}`, because two strangers with
  gmail addresses are not colleagues and must not share a graph.

Both are lowercased and non-alphanumerics become underscores, since the value
becomes a PostgreSQL schema name.

**Rule F.5** — The derivation lives in exactly one module. It is currently
written twice — once in the lock screen and once in the app shell — and two
copies of a tenancy rule that can disagree is a way for a user to land in a
different organisation depending on which door they came through.

**Rule F.6** — The generic-domain list is data, not a condition. It is a set of
domains; adding one must not require touching the branch that uses it.

### 3.2 What the lock screen actually proves

**Rule F.7** — **Email sign-in establishes no identity and must not be
described as if it does.** Typing an address and pressing the button calls the
authentication callback directly: there is no password, no verification mail,
no server round trip. Anyone can enter any address and receive that address's
organisation.

This is currently true, and it is written down here rather than left to be
discovered because everything else in this system takes tenancy seriously — the
services put each organisation in its own schema precisely so that a boundary
means something. A front door that hands out any tenant on request makes that
boundary decorative.

Until it is fixed, the email route must be labelled as unverified in the
interface. When it is fixed, it should be by the same means the OIDC routes
already use: the server verifies, the server issues the session, and the client
receives one it cannot mint itself.

**Rule F.8** — The session is not persisted. A reload signs the user out. That
is the correct default while F.7 stands — a forged session should not also be
durable — and should be revisited only together with it.

---

## 4. Project context

A project is the second tenancy tier (AG §2: the post-graph *space*). The tab
bar switches between a user's projects, creates them, and shows the project's
API key.

**Rule F.9** — Creating a project is a server operation. The tab bar may not
add a project to its own list on failure; a project that exists only in the
browser accepts documents and agents that go nowhere.

**Rule F.10** — **An API key is never generated in the browser.** When the
regeneration endpoint fails, the client shows the failure. It currently invents
a locally random key in the correct `XXXX-XXXX-XXXX-XXXX` shape, which cannot
authenticate anything — so the user copies it, uses it, and receives a 401 from
a service that never heard of it. A key that looks right and is not is worse
than a visible error.

**Rule F.11** — The key is shown on request, copied on request, and never
logged.

---

## 5. The views

Each view states what it is for, what it reads, and what it must not do. This
is the section to extend when a view is added.

### 5.1 Chatbot

Conversational access to the project's agents. Sessions are held client-side; a
turn is sent to the backend and the answer rendered.

**Rule F.12** — A failed turn renders as a failed turn. The existing behaviour
is right: an HTTP failure produces a visible system error in the transcript,
not silence and not a plausible answer.

### 5.2 Playground

The same conversation with the machinery exposed: which agent answered, which
mode the router chose, the steps taken.

**Rule F.13** — **Every step shown must have happened.** The panel currently
appends fabricated steps after each turn — a `KAGENT_EXECUTION` at "64ms" and a
`VERIFICATION_AUDIT` at "28ms", both marked `success`, both invented client-side
regardless of what the backend did, one of them claiming to have verified an
ED25519 signature that was never checked. A pipeline that failed therefore
displays two green successes.

The backend has the real answer: a run records `executed_steps` with per-step
status and timings (AG §3.5), and `/api/mcp/v1/tools/call` returns the run's
status. The panel should render those and show nothing where there is nothing.

**Rule F.14** — Latency is measured or absent. An invented figure is worse than
a blank, because it will be quoted.

**Rule F.15** — When the backend cannot be reached, the panel says so. It must
not fall back to "Executed multi-agent pipeline for directive …", which is a
sentence describing work that did not occur.

### 5.3 Discovery

Natural-language search for agents: the user describes a need, the system finds
agents that can meet it (AG §10).

**Rule F.16** — Results are the registry's, and are labelled with their source.
`/api/agents/discover` answers from one of three tiers — the agent registry's
vector index over registered agents, the archetype index, or keyword matching —
and only the first returns agents with a version and a content hash that can be
pinned and called. A user choosing between them deserves to know which they are
looking at.

**Rule F.17** — A discovered agent is invocable from where it was found. The
discovery response carries an `mcp_tool` name (`agent:{slug}@{version}`); the
panel should be able to run it without the user copying anything.

**Rule F.18** — Sample agents are marked as samples. The panel seeds itself
with illustrative entries; anything not returned by the server must be visibly
distinguishable from something that was.

### 5.4 Agent graph (civilization)

The population as a graph: agents as nodes, provenance as edges.

**Rule F.19** — The edges are the `spawns` edges from the registry (AG §5), not
a layout invented from a list. Provenance is the reason the graph is a graph;
drawing plausible lines between unrelated agents makes the panel decorative.

**Rule F.20** — The graph is bounded. It is drawn from a traversal with an
explicit depth (AG Rule 6.4) — a provenance graph is not guaranteed acyclic
once agents fork copies of each other.

### 5.5 Agent registry

The list, with detail: telos, caste, role, version, content hash, tools,
guardrails, reputation, token balance.

**Rule F.21** — The version and the content hash are shown. They are what make
an agent reproducible (AG §4.2), and they are the difference between "the
summariser" and "the summariser as it was when this run cited it".

**Rule F.22** — Assigning a model offers only models the router serves (§7),
and an agent already assigned one the router no longer serves renders it
marked, not silently replaced.

**Rule F.23** — Dormant agents are hidden by default and reachable on request.
Deletion is dormancy (AG Rule 3.2); an agent that has disappeared entirely from
the interface looks deleted, and users then ask why its provenance still
appears elsewhere.

### 5.6 Tools

The MCP tools available to this organisation and project.

**Rule F.24** — Each tool shows its `side_effects` and its version.
`read`, `write` and `external` are not decoration: they decide whether a tool
may be retried or invoked speculatively (tool-registry Rule 6.2), and a user
authorising one should see which it is.

**Rule F.25** — Tool listings name the realm. `GET /tools` requires `org_id`
(tool-registry Rule 2.1); a listing without one is not "all tools".

**Rule F.26** — Registering a tool states its input and output schemas. They
are required (tool-registry Rule 3.2), and the form should say why: the input
schema is what a model is shown when the tool is offered to it.

### 5.7 Documents

The corpus, and retrieval over it. The one view where the namespace has three
tiers.

**Rule F.27** — The interface uses the words the specification uses:
**organisation → project → document space**. `document_space` is not a
post-graph space and not a project (document-registry §2). The client currently
says "space", which is the single most reliable source of confusion in this
system.

**Rule F.28** — **Every document call names the organisation.** The panel
receives `orgId` and does not send it on any document request, so uploads,
listings and queries all land in the backend's default realm rather than the
signed-in user's. A user's documents are being written to, and read from, an
organisation that is not theirs.

**Rule F.29** — Ingestion reports what really happened. The registry
distinguishes indexed from catalogued-but-not-indexed (document-registry
Rule 6.2) and returns `status: "partial"` for the second. A document that
uploaded but is not retrievable must not be presented as filed.

**Rule F.30** — A rejected file says why. A `415` means no parser could read it
and **nothing was stored** (document-registry Rule 5.3) — the message should
carry that, because the user's next question is whether to re-upload.

**Rule F.31** — A batch shows per-file outcomes. The registry returns succeeded
and failed counts separately (Rule 5.5); collapsing them into "processed N
files" is how a partial batch reads as a complete one.

**Rule F.32** — Retrieval names its engine. A degraded read is labelled
degraded (document-registry Rule 8.2), because a user citing a passage is
making a claim about where it came from.

### 5.8 Sessions (shared memory)

Per-run context: what each step wrote, and in what order.

**Rule F.33** — Revisions are shown in order, not collapsed to a final value.
The registry keeps every revision precisely so a cyclic run can be read back
(AG Rule 8.5); showing only the last value discards the reason it is kept.

### 5.9 Guardrails

The inviolable rules attached to agents.

**Rule F.34** — A guardrail displays its level, its source and its action on
violation. "Blocked and audited" and "logged" are different promises.

---

## 6. Talking to the backend

Everything goes through `/api`, proxied to the backend. The client never calls a
registry directly — the backend is where realm defaults, key checks and
aggregation live, and a browser that bypasses it bypasses those.

### 6.1 The surface consumed today

| Endpoint | Used by |
| :--- | :--- |
| `GET /api/models` | shell, playground, agent detail |
| `POST /api/models/custom` | BYOM modal |
| `GET /api/orgs/{org}/users/{user}/projects` | project tabs |
| `POST /api/orgs/{org}/users/{user}/projects` | project tabs |
| `GET  /api/projects/{p}/key`, `POST …/key/regenerate` | project tabs |
| `GET /api/projects/{p}/agents` | registry, playground |
| `POST /api/agents/materialize` | materialize modal |
| `POST /api/agents/discover` | discovery |
| `POST /api/agents/synthesize-description` | agent detail |
| `POST /api/generate-system-prompt` | materialize modal |
| `POST /api/conductor/compose`, `…/orchestrate` | discovery, playground |
| `POST /api/agent/interact`, `/api/playground/chat` | chatbot, playground |
| `GET/POST /api/projects/{p}/spaces`, `…/documents…` | documents |
| `POST /api/projects/{p}/rag/query`, `GET …/rag/graph` | documents, explorer |
| `GET /api/metrics/global`, `…/project/{p}`, `…/agent/{a}` | header, agent detail |
| `GET /api/sessions` | sessions |

**Rule F.35** — Every request carries `org_id`, and every project-scoped
request carries `project_id`. Not as a convention — as the thing that decides
which PostgreSQL schema answers.

**Rule F.36** — One module owns the calling convention: base path, headers,
error shape, timeouts. Twenty-eight `fetch` calls with twenty-eight
hand-written error handlers is twenty-eight chances to handle one wrong, and
the models module (§7) is the pattern to follow.

### 6.2 Failure

**Rule F.37** — **Never fabricate.** A failed call produces a visible failure.
No invented answer, no invented step, no invented key, no invented search
result. This is the client's half of AG Rule 7.2, and it is the single most
important rule in this document: the registries take considerable trouble never
to hand an agent evidence it cannot distinguish from real evidence, and the
same is owed to a person.

**Rule F.38** — Distinguish *empty* from *unavailable*. "This project has no
documents" and "the document registry could not be reached" look identical as
an empty list and mean opposite things. The backend now returns `502` for the
second (document-registry §11); the client must render them differently.

**Rule F.39** — A failure names what failed and what to do. "Backend API
request failed (HTTP 502)" is a good message. "Something went wrong" is not.

**Rule F.40** — Long operations show progress and cannot be double-submitted.
Ingesting a document costs several model calls; a button that stays live
invites a second upload of the same file.

---

## 7. Models

**Rule F.41** — The model list comes from the router, through
`GET /api/models`, and is cached for the session. Three views used to carry
their own copy, and all three drifted: they offered DeepSeek V3.1 and V3.2 long
after that provider stopped answering, so a user could select a model no agent
could call and only discover it when a run failed.

**Rule F.42** — The deployment's configured default is preselected. The
response carries `default_model` and `embedding_model`; the client does not
have an opinion of its own about which model is best.

**Rule F.43** — Embedding models are never offered as an agent's model. They
are filtered out by role. Assigning one produces an agent that cannot hold a
conversation.

**Rule F.44** — When the catalogue cannot be fetched, the fallback is the one
configured default, marked unverified — not a remembered list. A remembered
list is exactly how the drift in F.41 happened.

**Rule F.45** — A custom model added through BYOM is scoped to an org, project
or user, and is labelled as custom wherever it appears.

---

## 8. Real time

A WebSocket to `/ws/civilization` carries civilization events.

**Rule F.46** — Reconnection is bounded and backs off exponentially, and stops
after a fixed number of attempts. A client that retries forever against a dead
backend is a client that heats a laptop in a closed tab.

**Rule F.47** — Connection state is visible. The user should be able to tell
that the live view is live.

**Rule F.48** — Events update what is on screen. They are currently received
and logged to the console, which is a connection that costs something and
returns nothing.

**Rule F.49** — The socket closes on unmount, and unmounting cancels pending
reconnects.

---

## 9. Composition from a prompt

The system can turn one sentence into a published, runnable pipeline: the model
decomposes the goal, RAG finds an agent for each stage, the stages are composed
and published, and the pipeline runs. `tests/composer.py` does this over the
public API, and the end-to-end suite proves it.

**Rule F.50** — The interface should expose that path, and show its stages: the
decomposition, the agent chosen for each stage and why, the published pipeline,
and the run. It is the most capable thing the system does and it is currently
reachable only from a test.

**Rule F.51** — A composed pipeline is shown with its resolved pins. `@latest`
is never a stored value (AG Rule 4.3); the panel shows the versions actually
pinned, because that is what will run.

---

## 10. State

State lives in `App.jsx` and is passed down as a `state` object plus setters.

**Rule F.52** — Session, tenancy and project are shell state. Everything else
belongs to the view that uses it. The shell currently also holds a tools array
and a models array, which is why both went stale.

**Rule F.53** — Server data is not duplicated into shell state. A view that
adds a tool refetches; it does not prepend to an array the server does not know
about, which is how the interface comes to show a tool that does not exist.

**Rule F.54** — Theme preference persists; nothing else does, while F.7 stands.

---

## 11. Modals

`SSOModal`, `MaterializeAgentModal`, `BYOMModal`, `RegisterToolModal`,
`AgentDetailModal`.

**Rule F.55** — A modal that submits shows the outcome before it closes. A
dialog that dismisses itself on failure has told the user it worked.

**Rule F.56** — A modal owns its own draft state and discards it on cancel.

---

## 12. Presentation

**Rule F.57** — Light and dark are both first-class, following the system
preference unless the user has chosen. The choice persists.

**Rule F.58** — The layout works from 360px up. The sidebar becomes a drawer;
tables scroll horizontally inside their own container rather than making the
page scroll.

**Rule F.59** — Colour is never the only carrier of meaning. A failed step and
a successful one differ by more than hue.

**Rule F.60** — Every control is reachable by keyboard, and dialogs trap focus
and restore it on close.

**Rule F.61** — Long values — ids, hashes, prompts — are truncated with the
full value available on demand, never silently cut.

---

## 13. Build and configuration

Vite. `npm run dev` serves on 3000 and proxies `/api` and `/ws` to the backend
on 8000. `npm run build` emits `dist/`.

**Rule F.62** — The client reads no secrets. `VITE_GOOGLE_CLIENT_ID` and
`VITE_MS_CLIENT_ID` are public client identifiers; everything else — model
router keys, database credentials — belongs to the backend. A `VITE_` variable
is compiled into the bundle and served to everyone.

**Rule F.63** — No backend URL is hardcoded. The proxy in development and the
same-origin path in production are the only two arrangements.

---

## 14. Implementation status

What is true today, against the rules above. Last checked 14 August 2026, with
`npm run build`, `npm test` (15 assertions), `pytest services backend`
(235 passing) and `pytest tests` (108 passing against a live stack).

### 14.1 Holds

**Structure.** One API module carries the tenancy on every request and turns
every non-2xx into a thrown `ApiError` (F.36, F.37, F.38); server state is
fetched rather than mirrored in the shell, and a mutation bumps a reload token
(F.53); view and project live in the URL as `#/{view}/{project}` and survive a
refresh (F.4); WebSocket events refetch the panels they concern (F.48).

**Honesty.** The playground renders only the steps the backend measured, with
latency shown only where `duration_ms` was returned, and a failed turn reads as
a failure (F.12–F.15). Ingestion reports partial as partial, a 415 says nothing
was stored, and retrieval names its engine including when degraded (F.29–F.32).
A composed pipeline is labelled published rather than executed, and shows its
resolved pins instead of invented latencies and signatures (F.51).

**Tenancy and identity.** `org_id` accompanies every call, documents included
(F.28, F.35); the backend is the only authority on which realm an identity
belongs to (F.5); the email route is labelled unverified in the lock screen,
the session and a header chip, and grants no verified standing (F.7); no API
key is minted in the browser (F.10).

**Registry and discovery.** Agent cards show version and content hash, and say
"unpublished" when there is none (F.21); tool cards state their side effects in
words (F.24); discovery names the tier it matched from and says when a result
cannot be pinned (F.16); a discovered agent can be run in place through its MCP
tool name (F.17); a goal composes to a published pipeline with resolved pins,
and unmatched stages are named rather than dropped silently (F.50, F.51);
session memory lists every context revision in order, with conflicts shown
(F.33).

**Earlier.** Theme with system preference and persistence (F.57); bounded
WebSocket reconnection with cleanup (F.46, F.49); the authentication wall
replacing the shell (F.1); the nine-view sidebar with a mobile drawer (F.2,
F.58); the model catalogue fetched from the router, cached, defaulted from
configuration and filtered of embedding models (F.41–F.44); no secrets in the
bundle (F.62); no hardcoded backend URL (F.63).

### 14.2 Still to do

| Rule | What is missing |
| :--- | :--- |
| **F.34** | Guardrails render their level and source but not their action on violation. |
| **F.59–F.61** | Focus return on modal close and truncation-with-full-value are inconsistent across views. |
| **F.64** | View smoke tests — the four utility modules are covered, the nine panels are not. |

### 14.3 Order taken

1. **F.28 and F.10** — the tenancy leak and the credential that could not work.
2. **F.13–F.15** — success that did not occur.
3. **F.7** — the email route is now labelled, not verified.
4. **F.36 and F.53** — the structural fixes the rest depend on.
5. **F.27, F.5, F.41, F.48, F.4** — the remaining contradictions.
6. **F.17, F.21, F.24, F.33, F.50–F.51** — the features that were not built.

---

## 15. Testing

`npm test` runs `node --test tests/*.test.js` — the Node test runner against the
four utility modules, with `fetch` and `window` stubbed. No test dependency to
install, and no browser to start.

Fifteen assertions hold today:

1. **The API module** (F.36) — that every call carries `org_id`, in the query
   string and in JSON bodies; that an unscoped call keeps the organisation but
   drops the project; that an explicit organisation is not overwritten; that an
   upload puts the tenancy where FastAPI reads it and does not set its own
   `Content-Type`; that a non-2xx throws rather than returning something a view
   could render; and that unreachable is distinguishable from empty (F.38).
2. **Sessions** (F.5, F.7) — that the email route yields `verified: false`, that
   a verified route is not downgraded, that the realm comes from the backend
   rather than being re-derived, and that an address is checked before it is
   sent.
3. **The model catalogue** (F.41–F.44) — that embedding models never appear as
   assignable, and that an unreachable router yields the configured default
   without pinning the session to it.
4. **The route** (F.4) — that the URL names view and project, that unknown views
   fall back, and that switching panels replaces history rather than stacking
   it.

Still worth adding: **view smoke tests** — that each of the nine panels renders
against a recorded response without throwing. That needs a DOM, so it needs a
dependency; it is the reason it has not been done yet rather than a judgement
that it does not matter.

**Rule F.64** — A test that asserts an interface fabricates something is a test
protecting a bug. The rules in §6.2 are the ones worth holding shut first.
