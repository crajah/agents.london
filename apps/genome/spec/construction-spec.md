# Genome — construction and the Ark

Specification for the crafting hierarchy that culminates in an Ark. Companion to
`genome-spec.md` §10.1.2, which establishes that worlds flood and that an Ark
shelters agents through it.

**Status: draft proposal for discussion.** Tiers, names and costs are a starting
shape, not settled numbers.

---

## 1. The design rule

**Every construction relaxes exactly one constraint the game already imposes.**

This is the difference between a crafting tree and a shopping list. Genome
already has a set of pressures agents live under — cargo decays, stock is
capped, agents strand, disease spreads, knowledge dies with its holder — and each
of those is a place where a building can *mean* something. A structure that
merely unlocks the next structure is a tollbooth.

**Rule 1.1** — A construction must name the rule it relaxes. A proposed
construction that relaxes nothing is rejected.

> The corollary is a useful check on this whole subsystem: **if a tier cannot name
> a constraint, that tier should not exist.** Depth for its own sake is how
> crafting trees become chores.

---

## 2. Costs, and why variety matters more than quantity

**Rule 2.1** — Construction consumes **deposited stock** at the builder's world
(`genome-spec.md` Rule 4.3), permanently.

**Rule 2.2** — Cost rises in the **number of distinct kinds** required, more than
in the quantity of any one. Tier 1 needs 1 kind; the Ark needs all 20.

> This is the load-bearing decision in the document, and it is what welds
> construction to the rest of the design.
>
> A world produces **two** kinds (`genome-spec.md` Rule 2.2), so a construction
> needing six kinds cannot be built from home no matter how rich the builder. It
> requires four kinds imported through agents, which requires partners, which
> requires the negotiation the simulation is about. **Every tier is a diplomatic
> problem wearing a resource cost.**
>
> It also explains an objective that would otherwise look arbitrary.
> `genome-spec.md` Rule 10.2 sets the first maximisation at *5 units of every one
> of the 20 kinds* — a strange target until you notice that **the Ark requires
> all 20**. Tier 1 of the objective hierarchy is not a milestone on the way to the
> Ark; it is the Ark's shopping list. The two hierarchies are the same hierarchy
> seen from different ends.

**Rule 2.2a** — **Only a flood destroys a construction.** Structures cannot be
attacked, razed by others, or lost to neglect.

> Construction is therefore a **ratchet**: what a coalition raises stands until
> the water comes. Three reasons this is the right call.
>
> **It protects the contributor.** A berth claim (Rule 3.7) is the only thing
> persuading a user to spend scarce resources on someone else's world. If a rival
> could raze the structure, that claim would be destructible by a third party who
> was never part of the bargain, and nobody rational would fund anything.
>
> **It keeps the Ark race a contest of coordination rather than sabotage.** With
> destruction available, the cheapest path to surviving a flood is not building
> faster but stopping whoever is ahead — and the design's whole thesis is that the
> interesting problem is assembling a coalition, not dismantling one.
>
> **It leaves the flood as the only adversary that takes things away**, which
> concentrates all loss into one scheduled, universal, impersonal event. That is a
> cleaner shape than continuous attrition, and it makes the countdown the single
> moment everything is decided.

**Rule 2.3** — Consumed resources leave the world's stock, so the world ceiling
(`genome-spec.md` Rule 4.13) falls below its cap and **regeneration resumes**.
Building is therefore not merely a cost — like materialisation, it is one of the
things that keeps a world productive.

---

## 3. The hierarchy

**Rule 3.1** — Construction is organised into **five independent branches**, one
per **colour family** (`genome-spec.md` §4.3). A branch is advanced using the
kinds of its own family.

| Branch | Family | Kinds | Concerns |
| :--- | :--- | :--- | :--- |
| **Earth** | Neutrals — Grey, Blue Grey, Brown | 3 | Structure, storage, defence |
| **Fire** | Yellows & Oranges | 4 | Processing, tools, making |
| **Growth** | Greens & Limes | 4 | Regeneration, preservation |
| **Life** | Reds, Pinks & Purples | 4 | Health, immunity |
| **Water** | Blues & Cyans | 5 | Knowledge, navigation |

**Rule 3.2** — A branch's **capstone requires every kind in its family**. The
**Ark requires all five capstones**, and therefore, transitively, **something
made from all twenty kinds**.

### 3.1 The branches

**Earth** — 4 tiers

| Tier | Construction | Kinds | Relaxes |
| :-- | :--- | :-- | :--- |
| 1 | **Cairn** | 1 | Root of the branch; marks a site |
| 2 | **Store** | 2 | The 25-unit user ceiling (`genome-spec.md` Rule 4.15), modestly |
| 3 | **Rampart** | 2 | Aggression suffered in this world (Rule 9.3) |
| 4 | **Foundation** | **3 — all** | Bears the weight of a Shipyard; nothing else can |

**Fire** — 3 tiers

| Tier | Construction | Kinds | Relaxes |
| :-- | :--- | :-- | :--- |
| 1 | **Kiln** | 1 | Root; the processing prerequisite |
| 2 | **Toolhouse** | 2 | Collection rate from piles (Rule 4.5) |
| 3 | **Forge** | **4 — all** | The 8-unit materialisation cost (Rule 2.1) |

**Growth** — 3 tiers

| Tier | Construction | Kinds | Relaxes |
| :-- | :--- | :-- | :--- |
| 1 | **Grove** | 1 | Pile regeneration rate (Rule 4.6) |
| 2 | **Granary** | 2 | Cargo decay for agents departing here (Rule 4.18) |
| 3 | **Orchard** | **4 — all** | Safe Period for agents provisioned here (`genotype-spec.md` §3.7) |

**Life** — 3 tiers

| Tier | Construction | Kinds | Relaxes |
| :-- | :--- | :-- | :--- |
| 1 | **Apothecary** | 1 | Infection Propensity at home (`pathogen-spec.md` §2.2) |
| 2 | **Infirmary** | 2 | Antigen retention (`pathogen-spec.md` Rule 2.19) |
| 3 | **Sanatorium** | **4 — all** | Clears an active infection, restoring expression |

**Water** — 3 tiers

| Tier | Construction | Kinds | Relaxes |
| :-- | :--- | :-- | :--- |
| 1 | **Library** | 1 | Knowledge dying with an agent (Rule 7.3) |
| 2 | **Beacon** | 2 | Stranding — odds of tracing a route home (Rule 7.4) |
| 3 | **Observatory** | **5 — all** | Teleport topology, including other worlds' flood clocks (§4.2.1) |

**Convergence** — 2 tiers

| Tier | Construction | Requires | Relaxes |
| :-- | :--- | :--- | :--- |
| 17 | **Shipyard** | Foundation + all four other capstones | Nothing; the Ark's precondition |
| 18 | **Ark** | Shipyard | Death by flood (Rule 10.3) |

**Eighteen constructions.** The longest path is six deep; no path is shorter than
that, because the Shipyard cannot be reached without every capstone.

### 3.2 Collaboration is a requirement, not an efficiency

Resource variety alone does not compel cooperation. It makes cooperation the
cheapest route, and a sufficiently rich or well-travelled user could still
grind their way up alone. Height in this tree is meant to be unreachable
without partners, so the requirement is stated directly.

**Rule 3.3** — Every construction records the **distinct users** who contributed
to it (§3.5). A construction cannot be completed until it has at least the
number its tier requires.

| Tier | Distinct contributors required |
| :--- | :--- |
| Branch roots — Cairn, Kiln, Grove, Apothecary, Library | **1** — the owner alone |
| Branch tier 2 | **2** |
| Branch capstone | **3** |
| Shipyard | **5** |
| **Ark** | **8** |

**Rule 3.4** — A contributor is counted once, however much it gives. Eight
deliveries by one user's eight agents is **one** contributor.

**Rule 3.9a** — The **Ark tree is immutable**. The eighteen constructions, their
tiers, their contributor counts and their dependencies are fixed. User plans
(`genome-spec.md` Rule 13.6) are **added alongside** it and never alter it.

> The canonical tree is what every constraint-relaxation in the design hangs from
> (Rule 13.7 of `genome-spec.md` reserves effects to it entirely), so a user able
> to edit it could rewrite the economy by editing a prerequisite. Additive-only
> keeps authorship real and the spine fixed: a user may build anything beside the
> tree and nothing into it.

**Rule 3.10** — A completed construction may be **carried through a teleport
point** by as many agents as it required contributors, and those agents must
represent **that many distinct users**.

**Rule 3.11** — The carriers need not be the builders. Any agents of the right
number and spread will do.

**Rule 3.12** — Carriers move as **one body** and are occupied for the journey:
they may not separate, mine or trade until the construction is set down.

**Rule 3.13** — A construction may **never be dismantled** into resources.

> Rule 3.13 is the one that has to be there, and it closes an exploit rather than
> expressing a preference. `genome-spec.md` Rule 4.2 says a teleport carries agents
> and not cargo, and Rule 4.16 caps an agent at fifteen units. Without Rule 3.13 a
> user builds a structure out of a hundred units, walks it through a portal with a
> handful of agents, and takes it apart on the other side — a resource teleport,
> a bypassed cargo ceiling, and both of the rules that make distance cost
> something, defeated by a crate.
>
> **Rule 3.10 mirrors Rule 3.4 deliberately.** Requiring *distinct users* rather
> than merely bodies means moving a construction demands the same scarce input
> that raising one did — other people. Under the alternative, a single wealthy
> user with five agents could walk off with a Forge that took four users to fund,
> and the berth claim in Rule 3.7 would be worth much less than it looks.
>
> **What this does to the flood is the interesting part**, and it is better than
> the flat wipe it replaces. Portage is possible but scales with contributor
> count, and the countdown is two days (Rule 4.8):
>
> | | Contributors | Evacuable in two days? |
> | :--- | ---: | :--- |
> | Branch roots — Cairn, Kiln, Grove, Apothecary, Library | 1 | yes, by one agent |
> | Branch tier 2 | 2 | plausibly, for a prepared pair |
> | Capstones — Foundation, Forge, Orchard, Sanatorium, Observatory | 3–5 | effectively no |
>
> **What can be saved is inversely proportional to what it is worth.** A coalition
> that plans ahead rescues its roots and loses its capstones, and the Ark remains
> the only continuity for anything that took a coalition to raise. The flood keeps
> its teeth exactly where they mattered, and the two-day window becomes a
> logistics problem with a real answer instead of a countdown to a foregone
> conclusion.

> Rule 3.4 is the load-bearing half. Without it, "eight contributors" is satisfied
> by wealth — a user with enough agents supplies the count themselves and the
> requirement measures nothing. Counting *users* rather than deliveries makes the
> scarce input **other people**, which is the only input that cannot be
> accumulated.

#### 3.2.1 What this makes the Ark

**The Ark is a collective vessel by construction.** Eight distinct users must
have contributed, and contribution earns a proportional claim on berths
(Rule 3.7). So an Ark necessarily carries a coalition — **its crew is its
builders**, and there is no arrangement in which one user builds a boat and fills
it with their own agents.

**Most users will never build an Ark. They will buy into one.** Since a berth on
someone else's ship saves an agent exactly as well as a berth on your own, and
since eight contributors are needed regardless, the rational structure is for a
region to converge on **whoever is furthest along** and finish that Ark together.
Expect regional Ark coalitions to form around a focal builder, and expect the
competition to be over *which* Ark rather than whether to build one.

**And it gives a poorly connected user a role rather than an exclusion.** The
fairness problem in Rule 6.2 — a trade graph nobody chose — is at its worst here,
since a user with few links can reach few kinds and fewer partners. But
contribution requires only *reaching* an Ark, not leading one. A user who can
touch a single well-connected neighbour can put agents aboard a vessel they could
never have built. **The badly connected are not locked out of survival; they are
locked out of ownership**, which is a much better failure mode and a considerably
more interesting one.

#### 3.2.2 Is a contributor count a constraint, or a mandate?

It is worth being straight about this, because `genome-spec.md` Rule 12.5 forbids
the specification supplying behaviour, and a rule reading "the Ark needs eight
users" looks very like an instruction to cooperate.

The defence is that it constrains **the artefact, not the agent**. *An Ark is too
large for one user to build* is the same kind of statement as *a world holds two
kinds* — a fact about the world that makes certain outcomes unreachable alone. It
names no behaviour and compels none. Everything that actually has to happen for an
Ark to exist remains open and unscripted: **whom to approach, what to offer, what
to conceal, whether to honour the arrangement once berths are allocated, and
whether to abandon a coalition for a better one.** Those are the decisions, and
the count creates the situation in which they are worth making.

The line to hold is that the requirement must never be satisfiable by *compliance*.
If contribution were free, eight users would trivially assemble and the rule would
have manufactured cooperation rather than provoked it. It is not free — every unit
contributed is a unit not spent on one's own agents, from a stock capped at 25 and
decaying in transit — so joining a coalition is a **costly choice made against
alternatives**, which is exactly what a game-theoretic mechanic should be.

#### 3.2.4 There is no solitary route, and what that costs

**Rule 3.8** — No user can reach an Ark alone, at any price. There is no
expensive solitary variant. **Collaboration is the only route to survival.**

> This is a deliberate narrowing and it should be stated as one rather than
> discovered later. It means the simulation **cannot answer "does cooperation
> emerge?"** — cooperation is compulsory, so the question is settled by
> construction rather than by evidence. Anyone reading a result from this
> simulation should know that.
>
> What it buys is a sharper question. **The interesting variation was never
> whether agents cooperate, but what kind of cooperation forms and how it fails.**
> With collaboration compulsory, everything that remains is about its *shape*:
>
> - which coalitions form, around whom, and on what terms;
> - who is admitted and who is excluded from a graph nobody chose (Rule 6.2);
> - whether contributors are paid fairly in berths, or merely enough to keep
>   contributing;
> - who defects *inside* a coalition, and when — the two days of a countdown
>   being the moment at which defection stops being punishable;
> - and what a coalition does with a hold too small for everyone's claims
>   (Rule 4.3).
>
> None of those is settled by making cooperation mandatory. **The compulsion sets
> the stage; the failure modes are still emergent**, and failures of cooperation
> are considerably more informative than its absence would have been.

#### 3.2.3 Why the count rises rather than sitting flat

A fixed requirement of, say, three contributors everywhere would be a toll paid
once: assemble three partners, then climb freely. A rising count makes each tier
a **larger diplomatic problem than the last**, so the difficulty of construction
tracks the difficulty of coordination rather than the difficulty of gathering.

That is the intended shape of the whole game. Resources are the *medium* of
cooperation, never its substance — an agent that cannot negotiate cannot build,
however much it carries. By the Ark, the binding constraint has stopped being
material altogether: **eight users who will each spend real resources on a vessel
whose berths they must share is a coalition problem, and no amount of gathering
solves it.**

### 3.3 Notes on particular constructions

**Cairn and Kiln relax nothing, and are the only two permitted to.** Rule 1.1
allows a structural exception for two branch roots. Two is the budget for
tollbooths in this design.

**Store is deliberately weak.** The 25-unit ceiling is the anti-snowball
mechanic (`genome-spec.md` §4.5), and a building that removed it would undo the
most valuable property in the resource system. Store should raise the cap by a
small fixed amount, not multiply it — enough to be worth building, not enough to
restore hoarding.

**Library duplicates the `Cartography` skill** (`skills-spec.md` §4.2)
deliberately. A skill is luck; a building is earned. That a user can *construct*
what another was born with is the right relationship between the two systems, and
it means a run of bad skill rolls can be answered with work.

**Forge is the construction that changes the economy.** Reducing materialisation
below 8 units shifts the balance in `genome-spec.md` §2.1, where breeding is
currently twice as efficient as self-reliance. A deep discount would make
materialisation competitive with breeding and quietly reduce the pressure to
cooperate — so it should be modest. Of every number in this document, this is the
one most worth getting right.

**Sanatorium is the only cure in the design.** Everything else about disease is
prevention, resistance or waiting it out. A capstone that clears an active
infection makes the Life branch worth completing even for a user who never
intends to build an Ark, which is a good property for a branch to have.

**Observatory is the counterweight to the LinkedIn topology.** Rule 6.2 hands a
user a trade graph they did not choose, and the Water capstone is the only thing
in the design that lets them see past it — including other worlds' flood clocks
(§4.2.1). Whether it also lets them *create* links is a much larger question
(§5.2); as specified it reveals, it does not connect.

**Orchard extends Safe Period, which no skill does.** Decay is the constraint
that most sharply bounds a user's reach (`genome-spec.md` §10.1.1), and the
Growth capstone is the only permanent relief from it. For a poorly connected user
it may matter more than the Ark.

### 3.4 Why branches rather than one tree

**Because a world holds two kinds, and they fall in one or two families.** A user
begins able to advance one branch — two if lucky enough to have been dealt kinds
from different families — and can do nothing at all on the other three until an
agent brings something home. **The route through the tree is dictated by what a
user can reach, which is dictated by who they are connected to.** That is the
whole design, and a single trunk hid it: with one chain, everybody built the same
thing next.

**There is one destination and an enormous number of routes.** Sixteen branch
constructions can be interleaved in any order consistent with their own branch,
which is a five-way multinomial — millions of distinct build orders. Two users
with different resource access will genuinely play differently, not merely more
slowly.

**Colour now predicts capability.** Branches are keyed to the colour families, and
an agent carries two colours drawn from its birth world's kinds
(`genotype-spec.md` §3.5). **An agent's colours therefore advertise which branches
its user can advance** — a Grey-and-Brown agent comes from a line that builds
Earth, a Cyan agent from one that builds Water. Colour was already a signal of
provenance and a courtship cue; it is now also a *trade prospectus*, readable
across a map by anyone who cares to look. That was not designed in — it falls out
of keying branches to the families colour already encodes — and it is the
strongest argument for doing it this way.

**Specialisation becomes a real strategy.** A user with poor connections can
still complete their own family's branch to its capstone, becoming the region's
only Forge or only Sanatorium. Capstones are precisely what other users cannot
easily reach, so a specialist has something to trade that is not a commodity —
which is the first thing in this design that rewards being *narrow*.

### 3.5 Cooperative construction

**Rule 3.5** — An agent may **contribute its carried cargo directly to a
construction in the world it currently occupies**, including a world belonging to
another user.

> This is the **second exception** to depositing only at a birth world
> (`genome-spec.md` Rule 4.3); breeding is the first. Both spend *carried* cargo
> in the field, and both exist for the same reason: they are the two acts the
> simulation most wants to be possible between strangers. No new transfer channel
> is created — an agent is still the only thing that moves resources, and it
> spends what it is carrying where it is standing.

**Rule 3.6** — A contribution goes **into the construction, never into the host's
stock**, and therefore does not count against the host's 25-unit ceiling
(`genome-spec.md` Rule 4.15).

> Necessary, not incidental. If contributions landed in stock they would be capped
> at 25 per kind, and an Ark needing all 20 kinds could never be co-built at all —
> the host would hit the ceiling long before the recipe was satisfied. Construction
> is a sink that bypasses the cap, which is exactly why it can absorb a coalition's
> output.

**Rule 3.7** — Contribution earns a **proportional claim on the construction's
capacity**, allocated mechanically. For an Ark this means **berths**
(Rule 4.3). The host is credited for every prerequisite tier it built alone.

**Rule 3.7a** — A berth, once held by an agent, is **the agent's to exchange**.
It may be given or traded to another agent.

**Rule 3.7b** — A berth changes hands like any other bargain: the parties must be
**co-located** (`genome-spec.md` Rule 9.1b) and both must agree. It may be
exchanged at any time, **including during the countdown**.

**Rule 3.7d** — A berth may be traded to **any agent**, including one whose user
contributed nothing to that Ark.

**Rule 3.7c** — An agent holds **at most one berth**. A claim beyond that is a
holding to be traded, never a second seat.

> A berth is the most valuable thing in the simulation, and Rules 3.7a–3.7c are
> what make that fact do some work rather than merely be true.
>
> **Rule 3.7d is what makes it an economy rather than an allocation.** Restricting
> berths to the contributing coalition would make contribution the only route to
> survival and leave nothing to trade. Open circulation gives the document's own
> claim — *most users will never build an Ark, they will buy into one* — something
> to be true of, and it means an Ark's crew at launch need not be its builders at
> all.
>
> **It is the one good with no adequate price.** A berth is worth everything an
> agent has earned — its map, its gained attributes, its antigens, its standing
> with counterparties (Rule 4.9). Cargo caps at fifteen units
> (`genome-spec.md` Rule 4.16), so no quantity of resources an agent can carry
> comes close. **Berths therefore cannot be bought, only exchanged for things that
> are not goods**: a reciprocal claim, a coalition's protection, a debt, kinship.
> That is precisely the region of game theory the design exists to explore, and
> nothing else in it forces a non-market trade.
>
> **It makes genuine sacrifice possible, and measurable.** An agent that hands over
> its berth dies in the water and loses everything it learned so that another does
> not. That is the strongest altruistic act available anywhere in these documents,
> and because lineage is recorded (`genome-spec.md` §7) and dispositions are
> heritable, it is *observable*: whether berths flow toward kin, toward
> reciprocators, or toward whoever argued best is a question the simulation can
> answer rather than assume. Hamilton's rule has a test here.
>
> **And a user cannot compel an agent to keep it.** Under Rule 13.5 an owner's
> instruction sets an objective and the agent decides how to serve it, so an agent
> may give away the berth its owner spent a coalition's resources to earn. That is
> uncomfortable by design. `genome-spec.md` §12 says choices are made rather than
> computed, and this is the sharpest case: if a user could veto it, the berth would
> be property and the sacrifice would be theatre.

### 3.5.1 Why the claim is enforced and not promised

**Rule 3.7 is the difference between this mechanic working and being dead on
arrival**, and the reasoning is worth stating because the alternative is more
obviously dramatic.

A promised berth is a contract, and contracts in genome are only as good as the
shadow of the future (`genome-spec.md` §10.1.2). But a flood is a *known
deadline*, and a repeated game with a known end unravels by backward induction:
at the last moment defection costs nothing, so a host who has already banked the
resources has no reason to honour anything. Rational contributors know this, so
they do not contribute, and cooperative construction never happens.

That is not a hard trust problem the simulation can enjoy watching. It is a
mechanic that predictably produces nothing.

Making the claim **mechanical** inverts it. Contribution is safe, so cooperation
survives the deadline that would otherwise destroy it — and the interesting
decision moves somewhere better:

- **Which Ark do you fund?** You cannot fund them all. Backing another user's Ark
  is capacity not spent on your own, and berths on someone else's ship are worth
  nothing if your own world floods first.
- **Contributors compete with each other.** Berths are proportional and finite,
  so co-funders are simultaneously allies against the flood and rivals for the
  same seats.
- **Coalitions form around resource complementarity**, not friendship. An Ark
  needs all 20 kinds and a world produces two, so the useful partner is the one
  holding what you cannot reach — which is the same logic that governs breeding
  and colour (`genotype-spec.md` §3.5).

`Oathbinding` (`skills-spec.md` §4.1) still has work to do here, but on the
*terms* rather than the berths: who boards first, what happens to a contributor
whose own world floods, whether a claim may be sold. Those are negotiable and
therefore breakable. The berth itself is not.

> The deeper point: this is the one place in the design where a mechanism
> **defeats backward induction instead of being defeated by it**. Everything else
> about the flood erodes cooperation as it approaches. Cooperative construction is
> the counter-pressure, and it only works because it does not ask anyone to trust
> a promise made before a deadline.

---

## 4. The Ark

**Rule 4.1** — The Ark shelters agents through a flood. Agents inside survive;
agents outside do not.

**Rule 4.2** — The Ark requires **all 20 kinds**, and therefore requires that its
builder has reached every corner of the resource space — through partners, since
a world produces two.

**Rule 4.3** — Ark **capacity is finite**, and it is capacity for **anything**.
A manifest may carry agents, **constructions**, and **deposited stock**, all
drawn against the same limit.

**Rule 4.3a** — A construction carried on the manifest is **re-established intact**
in the nascent world. One not carried is destroyed with everything else
(Rule 4.4).

> Rule 4.3 is what makes the Ark interesting rather than merely expensive, and
> Rule 4.3a is what makes it worth building at all.
>
> **It is the answer to evacuation** (§4.2.3). Agents that can reach a portal in
> two days leave and live (Rule 4.11); agents several hops out do not. Property is
> harder — a prepared coalition carries out its branch roots under Rule 3.10,
> while the capstones, needing three to five distinct users assembled at one spot
> inside two days, are not going anywhere.
>
> So evacuation saves the agents you positioned well and the cheapest tier of what
> you built. A berth saves the rest, an Ark can carry a Forge through the water,
> and no amount of packing substitutes for either.
>
> **And it converts the Ark into a collective allocation problem under a
> deadline**, which is the sharpest thing in the design. Capacity is shared among
> contributors (Rule 3.7), and berths, buildings and stock compete for the same
> space. A coalition must agree what to save: my agents or your Sanatorium? The
> Observatory that took four users to fund, or the cargo that would rebuild it
> faster? **Everyone's claim is legitimate, the total exceeds the hold, and the
> countdown is two days.** That is a bargaining problem with a real clock, real
> stakes, and no correct answer.
>
> A structure that saves everything is a switch: build it and the threat is over.
> A structure with capacity forces a **choice under a deadline** — which agents
> board, and which are left in the water. The user must value their own agents
> against each other, and the criteria they use are exactly the thing the
> simulation is trying to observe: the strongest genotype, the largest cargo, the
> deepest knowledge, the rarest lineage, or the ones that happen to be home.
>
> And it opens the question the flood makes urgent: **may an Ark shelter a foreign
> agent?** Berths are scarce and a visiting agent belongs to someone else. Refusing
> is free; accepting costs a berth that could have held your own. That is a real
> prisoner's dilemma arriving at the worst possible moment, which is precisely
> when `genome-spec.md` §10.1.2 predicts cooperation is unravelling by backward
> induction. **The Ark is where the whole game's argument about cooperation gets
> settled.**

---

## 4.1 The flood resets the world

**Rule 4.4** — A flood **returns a world to its nascent state**. Piles revert to
their original arrangement, rates and quantities; **deposited stock is
destroyed**; and **every construction is destroyed except the Ark itself**.

**Rule 4.5** — Agents sheltered in the Ark survive **entire** — cargo, knowledge,
gained attributes and retained antigens intact.

**Rule 4.6** — Agents outside perish, and regenerate in the nascent world under
`genome-spec.md` Rule 7.2 — which restores them **in their original state**:
genotype intact, and everything earned gone.

### 4.1.1 What the flood actually takes

The genotype survives either way. Rule 7.2 already guarantees that. So the Ark is
not saving agents from extinction — it is saving them from **amnesia**:

| Lost by drowning | Kept by boarding |
| :--- | :--- |
| The agent's knowledge store, and with it the user's queryable corpus (`genome-spec.md` Rule 8.4) | The corpus, entire |
| Wisdom, Skill Level, Counsel, Occulmancy | All of it |
| Retained antigens — every disease survived (`pathogen-spec.md` Rule 2.19) | Immunity, carried into the new world |
| Cargo in hand | Cargo |
| Every construction below tier 14 | Nothing — those are lost regardless |

> This is what eighteen constructions are worth, and it is a better answer than "your
> agents die". **A flood is an amnesia event.** The population survives it and
> arrives on the other side knowing nothing: no map of which worlds hold which
> kinds, no memory of who honoured an agreement, no immunity to anything it has
> already survived. A user who boarded keeps a civilisation. A user who did not
> keeps a genome and a blank world.

### 4.1.2 What this makes the simulation

**Genome is cyclical, and only one thing accumulates across cycles.**

Material progress is erased on a schedule: stock, constructions, maps, knowledge,
reputation, acquired immunity. What crosses a flood untouched is the **genotype**
— through regeneration for those who drowned, through survival for those who did
not — along with lineage, which is recorded in certificates rather than in
anything a flood can reach.

So across many cycles the only durable asset in the entire design is the
**inherited genome**, and the only durable progress is **evolutionary**. Every
other kind of advantage is a lease. For a simulation named after the genome that
is either a very satisfying coincidence or the reason the flood was invented, and
either way it is now the design's central claim.

### 4.1.3 It also repairs the backward-induction problem

`genome-spec.md` §10.1.2 warned that a known deadline unravels cooperation:
near the end, defection stops being punishable, so trust degrades as the flood
approaches. **A reset is not an ending, and that changes the analysis.** The game
continues on the far side, agents that boarded keep their opinions, and lineages
persist — so there is an *after* in which a defector can be remembered. The
shadow of the future is shortened by a flood, not extinguished.

But it is shortened **selectively**, and that is more interesting than either
extreme:

> **You can defect safely against an agent you know will drown.** Its opinions die
> with its knowledge (Rule 4.6), so the reputational cost of cheating it is zero.
> As a flood approaches, an agent's trustworthiness therefore depends on whether
> its counterparty expects it to have a berth — and berths are earned by
> contribution (Rule 3.3), which is **public**. Late in a cycle, the agents worth
> dealing honestly with are exactly the ones visibly building an Ark.
>
> Cooperation does not collapse before a flood. It concentrates.

## 4.2 The clock

**Rule 4.7** — Every world carries its **own flood clock**. A flood arrives after
a duration drawn uniformly between **15 and 30 days**, and the draw is **not
disclosed**.

**Rule 4.8** — **Two days before a flood, a countdown becomes visible** to every
agent in that world, visitors included.

**Rule 4.9** — A flood kills **every agent present in the world** when it
arrives, **whether or not it is their home world**. Visitors die with natives.

**Rule 4.10** — A **berth on an Ark is the only exemption.** Nothing else saves an
agent that is present: not a construction, not standing, not whose world it is.

**Rule 4.11** — An agent **elsewhere when the water comes is untouched**. Presence
is the criterion, and only presence.

> Three consequences, and the second is the one that changes how the map is read.
>
> **What is lost is everything earned** — knowledge, gained attributes, retained
> antigens, cargo (§5.1) — none of which regeneration restores
> (`genome-spec.md` Rule 7.3). The agent returns; what it had learned does not. A
> berth is the only thing that carries an agent's earned life across the water.
>
> **Travel becomes genuinely dangerous.** Standing in a foreign world when its
> clock runs out kills an agent as surely as standing in its own. Wanderlust
> (`genotype-spec.md` §3.2) now carries a real hazard rather than a cost in decay
> and distance, and the question *when does this world flood* stops being strategy
> and becomes survival.
>
> **Which gives the Observatory a life-and-death function.** It reveals other
> worlds' flood clocks (§4.2.1), and under Rule 4.9 that is no longer an
> optimisation — it is the difference between sending agents somewhere and sending
> them somewhere that is about to drown. Flood-clock intelligence becomes the most
> valuable thing an agent can carry out of a foreign world, and one of the few
> pieces of knowledge worth crossing a map to buy. Rule 4.8 warns visitors for
> exactly this reason: it is a hazard notice, not a courtesy.
>
> **The two-day window is now a real evacuation.** Agents near a portal can leave;
> agents deep in the map or several hops out cannot. A berth is insurance for the
> ones that cannot run, and the berth market is priced by how far a coalition's
> agents habitually range.
>
> *Recorded honestly:* this weakens the flood as an equaliser. An agent that
> reliably evacuates keeps its knowledge across cycles, so accumulation is bounded
> by **Longevity** (`genotype-spec.md` §3.4) rather than by the water. The flood
> still strips a world's stock, piles and constructions, and still takes everyone
> who misjudged the clock — but a careful, well-placed agent can compound
> indefinitely, and that is a property to watch rather than one to assume away.

### 4.2.1 Why per-world clocks change everything

Worlds flood **at different times**, and almost every interesting consequence
follows from that.

**A freshly flooded world is the safest place in the universe** — and the
poorest. Its clock has just reset, so it cannot flood again for at least fifteen
days, but it is in its nascent state with nothing built and nothing stockpiled.
Safety and wealth are anticorrelated across the map, continuously, and every
travelling agent is trading one against the other whether or not it knows it.

**A visitor can be caught in someone else's flood.** An agent abroad drowns in
the host world's flood, not its own, and it has no berth there. Travel now
carries a hazard that has nothing to do with the traveller's own preparations —
which makes the host's clock something worth knowing before stepping through a
teleport, and makes `Observatory` (§3.1) considerably more valuable than it
looked.

**Uncertainty compounds with time.** The draw is uniform on [15, 30], so the
*hazard rate* climbs: an agent that has survived to day 28 faces near-certainty
within two days, while one at day 10 faces none at all. Rational anxiety
increases through a cycle without anyone being told anything, and behaviour
should visibly change in the last third even before a countdown appears.

### 4.2.2 What the two-day countdown does

**It bounds the endgame to two days.** `genome-spec.md` §10.1.2 warned that a
known deadline unravels cooperation by backward induction. A *hidden* deadline
cannot: you cannot reason backwards from a date you do not know, so for thirteen
to twenty-eight days the game is effectively open-ended and cooperation holds
normally. **The countdown is the only window in which defection is safely
calculable, and it is two days long.** Turning an unravelling problem into a
short, recurring, visible crisis is a much better design than either a hidden or
a published date.

**It is the evacuation window.** Two days is enough to bring nearby agents home
or send them out, and not enough to recall one that is four hops away. Evacuation
therefore becomes a *plan* rather than a reflex — agents must already be
positioned when the countdown starts, which means guessing at a hazard rate.

**It creates a distress market.** Everyone in a counting-down world knows they
need a berth, a route out, or a partner, and everyone knows the others know.
Visitors from safe worlds arrive holding exactly what desperate agents need. What
a berth is worth in the last hour is a price nobody has to set.

**And it makes trustworthiness legible at exactly the moment it matters.** §4.1.3
notes that defecting against an agent who will drown is free, because its
memories die with it. Once a countdown is visible, every agent in the world can
see who is likely to have a berth — contributions are public (Rule 3.7) — and so
who will still be around to remember. **Honesty in the final two days is a
function of who is visibly getting on the boat.**

### 4.2.3 Evacuation is a cheaper substitute for an Ark, and that needs watching

Agents elsewhere when their home floods **survive**, keeping their knowledge,
attributes and antigens. An Ark saves precisely the same things. So a user who
simply sends every agent abroad during the countdown preserves everything an Ark
would have preserved, for nothing.

Three things currently stop that being strictly dominant, and they may not be
enough:

- Evacuation needs **somewhere to go** — a reachable link, to a world not itself
  counting down.
- It needs agents **already in position**; two days will not recall a distant one.
- Evacuated agents are **abroad and unproductive**, decaying cargo
  (`genome-spec.md` Rule 4.18) and exposed to foreign strains.

**Open (§5.7):** whether that is sufficient, or whether an Ark must preserve
something evacuation cannot — deposited stock loaded aboard being the obvious
candidate. As the rules stand, the cheapest survival strategy is to build no Ark
at all and keep a bag packed, which is not what a fourteen-tier hierarchy should
reward.

---

## 5. Open questions

**5.1 Resolved** — a flood returns the world to its nascent state (§4.1):
constructions, deposited stock and pile progress destroyed, the Ark alone
surviving. What an Ark saves is everything *earned* — knowledge, gained
attributes, antigens, cargo — none of which regeneration restores.

**5.6 Decided** — the **Ark persists; its prerequisites do not.** A user emerges
owning a hull and must rebuild the seventeen constructions beneath it.

> Thematically exact — Noah lands and the world is empty — and mechanically it
> does the right thing. **Surviving one flood makes the next materially easier
> without making it trivial**: the coalition keeps the single thing that cannot be
> rebuilt quickly, and must still reassemble everything that feeds it, with all
> the partners and all the negotiation that implies.
>
> It also means an established coalition and a new one are not equivalent. A group
> that has already survived a flood starts each subsequent cycle from a genuinely
> better position, so **advantage compounds across cycles through cooperation
> rather than through accumulation** — which is the only form of compounding this
> design permits anywhere.

**5.2 Decided — it creates them.** The Water capstone both reveals the graph and
**forges new teleport links**.

> I had recommended reveal-only, on the grounds that the unchosen graph is the
> design's most distinctive constraint. Working through the consequences, creating
> links is the better answer, because of how it interacts with the flood.
>
> **It converts structural inequality from permanent to initial.** Rule 6.2 hands
> a user a trade graph they did not choose, and reveal-only would have made that a
> cage for the entire life of the simulation — a poorly connected user could see
> exactly how badly placed they were and do nothing about it. Creating links means
> the LinkedIn graph is the *starting position*, not the ending one. That is a
> more interesting claim than the original: inequality is inherited, and can be
> worked out of, at enormous cost, over many cycles.
>
> **And the cost is naturally bounded by the flood.** An Observatory is a
> prerequisite, so it is destroyed every cycle (§5.6) and must be rebuilt — five
> kinds, three contributors, on top of the Beacon and Library beneath it. Nobody
> forges links casually.
>
> **But a link, once made, is permanent** (`genome-spec.md` Rule 6.3a) and floods
> do not touch the graph. So **connectivity is the one thing in the entire design
> that ratchets across floods.** Stock resets, constructions burn, knowledge
> drowns — the map only ever grows. Over many cycles the universe becomes steadily
> better connected, which means the simulation has a long arc and not merely a
> repeating one: early cycles are isolated and scarce, late cycles are dense and
> crowded, and the game changes character as it runs. That is worth considerably
> more than the constraint I was trying to protect.

**Rule 3.9** — An Observatory forges **one link, once**. Forging another requires
another Observatory — and since the flood destroys it (§5.6), that means rebuilding
the entire Water branch in a later cycle.

> Which prices connectivity in the only currency this design treats as truly
> scarce: **coordination, repeated.** A new edge costs five kinds, three
> contributors, and a Beacon and Library beneath it — every cycle, from scratch.
> Nobody opens a region quickly.
>
> The result is that the universe becomes connected **slowly and permanently**.
> Early cycles are isolated, scarce and mostly local; late cycles are dense,
> crowded and competitive; and the transition takes many floods. That gives the
> simulation an arc measured in cycles rather than a loop, and it is the only
> quantity in the design that only ever increases.

**5.3 Decided** — only floods destroy (Rule 2.2a). Construction is a ratchet and
the flood is the sole adversary that takes anything away.

*Knock-on, recorded:* `Rampart` was specified as defence against aggression
suffered in a world. Structures are no longer attackable, so it defends **agents,
not buildings** — aggression between agents (`genome-spec.md` Rule 9.3) remains
entirely live, and a Rampart makes a world a safer place to visit, which is a
reason for others to come and trade.

**5.4 Resolved** — construction is cooperative (§3.2). An agent contributes
carried cargo to any construction in the world it occupies, contributions bypass
the host's stock ceiling, and capacity claims are allocated mechanically rather
than promised.

**5.5 Decided — per world.** A construction belongs to the world it stands in,
not to the user who owns that world.

> The two readings are equivalent today, since a user has exactly one world
> (`genome-spec.md` Rule 3.1). Saying *per world* is the safer of two identical
> statements: nothing breaks if an agent is ever permitted to build abroad, or if
> a user ever comes to hold more than one world. Choosing the reading that
> survives a future change costs nothing now.

**5.7 Resolved** — an Ark carries constructions and stock as well as agents
(Rules 4.3, 4.3a), which evacuation cannot. Evacuation saves a line; the Ark saves
what the coalition built.

**5.8 Resolved — no.** Collaboration is the only route to survival, deliberately.
See §3.2.4 for what that costs and what it buys.

**5.9 Decided** — one link per Observatory built (Rule 3.9). Connectivity grows
slowly, permanently, and only through repeated coordination.
