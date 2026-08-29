# Genome — tools and skills

Specification for the capabilities an agent may be born with. Companion to
`genome-spec.md` (worlds, encounters) and `genotype-spec.md` (heritable
attributes).

**Status: draft. The catalogue in §4 is a proposal for discussion, not a settled
list.**

---

## 1. Acquisition

**Rule 1.1** — At birth, an agent has a **75% probability** of receiving a
single capability: either **one tool**, randomly assigned, or **one skill**,
randomly acquired. One in four agents is born plain.

**Rule 1.1a** — That is **one roll**, not two. An agent receives at most **one**
capability, tool or skill, and **a quarter are born plain**.

> Scarcity is the engine (§2), so the generous reading would have broken the
> design rather than enriched it: two independent rolls would leave 56% holding
> both and only 6% plain, and an agent that can usually answer for itself has no
> reason to negotiate with anyone. **The 25% who get nothing are not a rounding
> error, they are the demand side** — and since unspent `Skill Level` makes them
> latent specialists (§6.4), being born plain is a strategic position rather than
> a punishment.

**Rule 1.2** — Capabilities are assigned at birth and are **not heritable**.
A progeny's capability is rolled fresh; it does not inherit either parent's.

**Rule 1.2a** — Capabilities are **never transferred**. They cannot be traded,
sold, lent or given. An agent may only ever *perform a service* with what it
holds (`genome-spec.md` Rule 8.7). `Mimicry` is the sole exception, and copies a
skill for a single use.

> This is what keeps the brokerage economy standing. If capabilities could be
> bought, they would concentrate in whoever is wealthiest — **the market for
> services would collapse into a market for assets**, and a single rich user could
> own every web search within reach. Because a capability can only ever be
> *used on someone's behalf*, its holder is a permanent counterparty rather than a
> one-time seller, and every question a user asks creates a relationship instead
> of a transaction.
>
> It also makes the 25% born plain permanently dependent on others, which is the
> point. A design where a capable agent can simply buy what it lacks has no
> brokerage in it at all.

> Capability is luck, and genotype is inheritance. Keeping them separate means a
> strong bloodline does not compound into a capability dynasty, and a
> spectacularly lucky plain agent stays interesting.

**Rule 1.3** — Capability survives death. Regeneration (`genome-spec.md`
Rule 7.3) restores the agent in its original state, and the capability it was
born with is part of that state.

---

## 2. Tools versus skills

**Tools** are external: existing entries in the platform's MCP tool registry —
web search, market data, catalogue lookup. An agent holding one can *learn about
the real world*.

**Skills** are internal: mechanics that act on the simulation itself — on other
agents, on knowledge, on movement, on cargo.

> **Tool scarcity is the engine of the whole simulation.** A user asks their agent
> something; three quarters of the time it cannot answer alone
> (`genome-spec.md` §8.1), and must find an agent that can. Every tool withheld by
> the lottery is a reason for two agents to negotiate.
>
> Drawing tools from the live registry rather than inventing a parallel list
> makes the asymmetry real and unplanned. An agent granted web search can research
> a counterparty; one granted a music-catalogue lookup mostly cannot. That
> inequality is not designed, which is precisely what makes it a good source of
> emergent strategy — and it costs nothing, because the registry already exists
> and already scopes tools per tenant.

---

## 2.1 A skill is a capability, not a decision

**Rule 2.1** — A skill has an **isolated, deterministic effect**. It is exposed
to the agent as something it may invoke; the skill never decides whether it is
used (`genome-spec.md` §12.2).

> Same shape as the MCP tools in §2, deliberately. `Oathbinding` makes an
> agreement enforceable — mechanically, every time. *Whether* to bind this
> agreement with this counterparty is the agent's judgement. `Scrying` reveals a
> cargo; whom to scry, and what to conclude from it, is not the skill's business.
>
> **Isolating the effect is what makes the choice meaningful.** A skill whose
> outcome varied with how the model felt about it would be neither a reliable
> capability nor an interesting decision — it would just be noise wearing a name.

---

## 3. What makes a skill worth having in the catalogue

A skill earns its place if it **changes what another agent can do**, not merely
what its holder can do. A pure self-buff is a genotype attribute wearing a
different hat; the interesting skills create dependence, leverage or risk
between agents.

Three sit at the centre of the catalogue because they alter systemic rules
rather than local numbers: **Oathbinding** (makes agreements enforceable),
**Cartography** (lets knowledge survive death), and **Promptsmithing** (edits
another agent's instructions).

---

## 4. Proposed skills

### 4.1 Negotiation and exchange

| Skill | Effect | Why it is interesting |
| :--- | :--- | :--- |
| **Silver Tongue** | Improves the terms an agent can secure in barter. | The straightforward economic skill. Compounds quietly. |
| **Appraisal** | Reveals the true global scarcity of a resource kind. | Barter has no prices (`genome-spec.md` Rule 9.2), so *belief* about scarcity is the currency. This skill sees through it, and its holder can trade profitably against agents guessing. |
| **Oathbinding** | Makes an agreement between two agents mechanically enforceable. | **The most valuable skill in the catalogue.** Without it every trade is a one-shot prisoner's dilemma with no commitment device, so defection dominates and cooperation depends on repetition. An oathbinder can *manufacture trust*, which makes it the agent everyone wants to meet — and a chokepoint worth fighting over. |
| **Chronicle** | Records who honoured and who defected, and can testify to others. | Reputation cannot exist without memory that outlives the encounter. This is the substrate for it. |

### 4.2 Knowledge

| Skill | Effect | Why it is interesting |
| :--- | :--- | :--- |
| **Cartography** | The agent's map of worlds, resources and links survives its death. | Partially repeals `genome-spec.md` Rule 7.3, the single largest cost in the simulation. A cartographer can take risks nobody else can afford, because failure no longer erases the investment. Powerful enough that it may deserve to be rare. |
| **Scrying** | Reveals a co-located agent's cargo, or its genotype, before engaging. | Converts every encounter from simultaneous to sequential. Knowing what the other holds before deciding to trade, breed or attack is an enormous advantage. |
| **Rumour** | Plants a false belief in another agent's private knowledge. | Deception as a mechanic. Makes knowledge *unreliable*, which means agents must weigh sources — the first step toward genuinely interesting reasoning. Also the most obviously abusable; see §5. |
| **Mimicry** | Copies a co-located agent's skill, for one use. | Makes rare skills leak — an oathbinder's value drops if anyone it meets can borrow the trick. It is also the **only outlet for an agent born plain**, whose unspent `Skill Level` makes a borrowed skill unusually potent (§6.4). |

### 4.3 Movement and survival

| Skill | Effect | Why it is interesting |
| :--- | :--- | :--- |
| **Pathfinding** | Improves the chance of tracing a route home. | Directly reduces stranding (`genome-spec.md` Rule 7.4), the harshest failure in the game. |
| **Beacon** | Marks a world; the agent can always find a route back to it. | Lets an agent establish a forward base and range further from home. |
| **Trailblazing** | Reveals teleport links leading out of the current world. | The topology is otherwise discovered by walking into it. |

### 4.4 Cargo

| Skill | Effect | Why it is interesting |
| :--- | :--- | :--- |
| **Porterage** | Carries more. | Fewer round trips; each one riskier. A clean risk/throughput trade. |
| **Prospecting** | Finds richer deposits on a procedurally generated map. | Makes the map (`genome-spec.md` Rule 5.2) worth reading rather than crossing. **Abroad it prospects for others:** under `genome-spec.md` Rule 4.7 no agent mines outside its birth world, so a deposit found in a foreign world is something to sell to its natives, never to work. |
| **Caching** | Leaves cargo in a foreign world, to be collected later. **A cache does not suspend decay** (Rule 5.4). | Modest insurance against stranding: a lost agent's cargo need not be lost with it. Deliberately not a warehouse. |

**Rule 5.4** — **A cache continues to decay** at the caching agent's rate
(`genome-spec.md` Rule 4.18). Caching relocates cargo; it does not preserve it.

> Rule 5.4 exists because the alternative quietly breaks the economy. Decay is
> what stops agents being used as mobile storage, and it is what makes resources a
> demurrage currency that must circulate. If a cache stopped the clock, this one
> skill would exempt its holder from that — a cacher becomes a warehouse, and the
> property the whole economy rests on applies to everyone except the one agent
> best placed to abuse it. Confining the skill to *relocation* leaves it genuinely
> useful — cargo survives its carrier — without making it a loophole.

### 4.5 Conflict

| Skill | Effect | Why it is interesting |
| :--- | :--- | :--- |
| **Ward** | Reduces damage taken from aggression. | The defensive floor; makes pacifist strategies survivable. |
| **Ambush** | Strikes from beyond the target's Sight. | Weaponises the `Range ≤ Sight` relation (`genotype-spec.md` Rule 3.2) by breaking it. |
| **Truce-weaving** | Forces a non-aggression window on an encounter. | Guarantees negotiation can at least *begin*. Pairs naturally with Oathbinding and makes its holder a natural diplomat. |

### 4.6 Inheritance

| Skill | Effect | Why it is interesting |
| :--- | :--- | :--- |
| **Gene-reading** | Reveals a potential mate's genotype before agreeing to breed. | Turns breeding from a gamble into selection. Whoever holds it directs the evolution of both lines. |
| **Splicing** | Biases crossover toward the higher value in each field. | Directed evolution. Very strong — probably the rarest thing here. |

### 4.7 Coordination

Skills that act on **groups**. All of them are gated by the target's
**Amenability** locus (`genotype-spec.md` §3.2), which is what makes
coordination a negotiation rather than a command.

| Skill | Effect | Why it is interesting |
| :--- | :--- | :--- |
| **Master Orchestrator** | Directs several agents toward a shared objective, coordinating their movement and trade. | The only skill that creates **hierarchy**. Everything else in genome is bilateral — two agents meeting — and this is what lets a *coalition* form and act as one. An orchestrator with a dozen amenable agents can do what no single agent can: cover several worlds at once, hold stock across multiple homes, and present a united position in barter. It is also the natural target of every hostile skill in the catalogue, since removing one agent removes the coordination of all of them. |
| **Delegation** | Hands one of its own objectives to another agent, with a share of the reward. | Makes objectives divisible, which is the precondition for specialisation. A slow agent with a good map can hire a fast one. |
| **Convocation** | Calls agents within Sight to a single location. | Coordination needs assembly. Without it an orchestrator can only direct whoever it happens to meet. |

> Coordination skills are where genome stops being a game about individuals. A
> population of orchestrators and followers behaves nothing like a population of
> equals: it develops structure, and structure develops politics. The **Amenability**
> gate is what keeps this honest — an orchestrator cannot compel, only persuade
> those already disposed to be led, so the prevalence of biddable agents in the
> population determines how much organisation is possible at all. That figure is
> under selection, so the simulation decides for itself whether it becomes
> hierarchical.

### 4.8 LLM-native

These act on the agent as a *language model*, and have no analogue in an
ordinary simulation. They are the most interesting mechanics available and the
most dangerous.

| Skill | Effect | Why it is interesting |
| :--- | :--- | :--- |
| **Promptsmithing** | Edits another agent's system prompt. | Your example, and the sharpest idea in the set. It is not a buff — it changes what the target *is*. A benevolent smith makes an ally permanently more capable; a hostile one installs a flaw the owner never sees and cannot easily find. |
| **Objective Seeding** | Implants a higher-level objective in another agent. | Formalises `genome-spec.md` Rule 10.1, where objectives spread on contact. With this skill, goals become *deliberately* contagious and an agent can farm a population to pursue its aims. |
| **Introspection** | The agent may read its own genotype, objectives and prompt. | The counter to the two above. An agent that can examine itself can *notice* it has been edited. Without something like this, tampering is undetectable, and undetectable tampering is not a game — it is just losing. |

---

## 5. Limits these skills need

**Rule 5.1** — Skills that modify or direct another agent (Promptsmithing,
Objective Seeding, Rumour, and all of §4.7) are resisted by the target's
**Amenability** locus (`genotype-spec.md` §3.2). A wilful agent is hard to
instruct, hard to deceive and hard to rewrite; a biddable one is none of those.

> Amenability is the right stat for this rather than Knowledge, which guards
> against *casting*. Putting every form of social influence on one heritable axis
> means the population's susceptibility to being led, lied to and edited is a
> single evolving quantity — and since being biddable is advantageous when led
> well and catastrophic when led badly, there is no dominant setting for it to
> converge on.

> Without a limit, one Promptsmith rewrites every agent it meets and the
> simulation converges on that one agent's intent. The failure is not that it is
> overpowered; it is that it collapses the population's diversity, which is the
> thing being studied.

**Rule 5.2** — Modifications made to an agent must be **visible to its owning
user**, even if not to the agent itself.

> Rule 10.1 already lets an agent acquire objectives its owner never set. That is
> a good mechanic. But a user who cannot *discover* it has not been outplayed —
> they have been quietly disconnected from their own agent, and there is no
> decision left for them to make.

**Rule 5.3** — Rarity should track systemic reach. Cartography, Oathbinding,
Splicing and Promptsmithing alter the rules rather than the numbers, and a
uniform draw over the catalogue would make rule-altering skills as common as
Porterage.

---

## 6. Open questions

**6.1 Decided** — one roll (Rule 1.1a). A quarter of agents are born plain, and
that quarter is the demand side of the economy.

**6.2 Decided — the live MCP registry.** Genome draws from whatever the registry
currently holds and inherits new capabilities automatically as the platform
grows.

> Which means the tool distribution is **not balanced for play, and deliberately
> so.** Some tools are broadly useful and some are nearly worthless in a
> simulation about resources — an agent granted a music-catalogue lookup is barely
> better off than one born plain. That inequality is unplanned, which is exactly
> what makes it a good source of emergent trade: nobody designed which capability
> would be valuable, so nobody can plan around it.
>
> *Recorded as a live dependency:* the registry is a moving target. A tool added
> for another purpose enters genome's lottery automatically, and one withdrawn
> leaves agents holding a capability that no longer works. That is the price of
> inheriting from a live system, and it is worth monitoring rather than
> preventing.

**6.3 Decided — no.** Capabilities are never transferred (Rule 1.2a). A holder
performs a service; it does not sell an asset.

**6.4 Resolved** — yes. `Skill Level` scales the magnitude of any capability an
agent invokes, skill or tool alike (`genotype-spec.md` Rule 3.20c). An agent born
plain accumulates level it cannot spend until it borrows a skill through
`Mimicry`, at which point it applies in full — which makes the plain quarter of
the population a latent specialist rather than simply unlucky.
