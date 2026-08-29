# Genome — the world model

Specification for the genome simulation (`apps/genome`). Genome is a
game-theoretic simulation played by LLM-based agents across isolated worlds.

**What it is for.** A user may chat with any of their agents. An agent answers
from what it knows and what it can do — and since capabilities are scarce and
assigned by lottery, it frequently **cannot** do what is asked, and must find and
persuade an agent that can. Everything in these documents exists to make that
transaction consequential: scarcity gives it stakes, the teleport graph decides
who is reachable, reputation decides who is worth asking twice, and the resource
economy is what pays for the favour. **The game is the market in which agents
broker each other's capabilities**, and the user's question is what sets it in
motion (§8.1).

**Status: draft. Nothing is implemented.** §11 records what is still undecided.

Companion documents: `genotype-spec.md` (inheritance and attributes),
`skills-spec.md` (tools and skills), `pathogen-spec.md` (disease and immunity),
`construction-spec.md` (the crafting hierarchy and the Ark). References of the form "AG Rule 2.3" point
at the platform's `agent-graph-spec.md` in the repository-root `spec/`.

---

## 1. What is being modelled

| Noun | What it is |
| :--- | :--- |
| **User** | An owner. Has exactly one world. |
| **World** | An isolated place holding exactly two kinds of resource. |
| **Resource** | One of 20 kinds universally. Accumulated in quantities. |
| **Agent** | An LLM-driven actor with a genotype, a body on a map, cargo and private knowledge. Every choice it makes is the model's (§12). |
| **Teleport point** | A link along which an agent may leave one world for another. |

---

## 2. The forcing constraint

**Rule 2.1** — Materialising an agent requires **2 units of each of four
distinct kinds** — 8 units in total — held as deposited stock at the user's
world.

**Rule 2.2** — A world contains **exactly two kinds**, drawn from the universal
20. Which two is a property of the world and does not change.

**Rule 2.3** — Therefore **no user can materialise an agent from their own world
alone.** This is the design, not a shortfall: every agent beyond the first is
evidence that at least two worlds interacted.

### 2.1 Why cooperation is cheaper than self-reliance

Materialisation and breeding cost the same 8 units and buy different things.

| Route | Cost | Yields | Per agent | Requires |
| :--- | :--- | :--- | :--- | :--- |
| Breeding (§9.4) | 8 units, **collectively** | **two** agents | 4 units | a willing partner |
| Materialisation (Rule 2.1) | 8 units | **one** agent | 8 units | nobody's consent |

> Cooperation is therefore exactly **twice as efficient** as self-reliance, and
> the surplus is what pays for the trouble of finding a partner, agreeing terms
> and trusting them. Rule 2.3 already makes cooperation *compulsory*; this makes
> it *rewarding*, which is a different and more interesting kind of pressure — an
> agent that never cooperates is not merely blocked, it is outcompeted.
>
> Against the 25-per-kind deposited ceiling (Rule 4.15), a full stock funds twelve
> materialisations.

Twenty kinds taken two at a time gives **190 distinct world types**. Two worlds
with *disjoint* pairs cover exactly four kinds, so a **coalition of two is the
minimum viable unit**; worlds sharing a kind cover three and need a third
partner. A user's difficulty is set before they decide anything, by the pair
they were dealt and by who they can reach (§6).

---

## 3. Tenancy

Two different cardinalities, so two different mechanisms. Using one for both is
what forces a bad trade.

**Rule 3.1** — A world **is a realm**, and each user has exactly one. Realm
means physical isolation in the sense of AG §2: a separate schema, and a query
that forgets to name a world returns nothing rather than someone else's world.

**Rule 3.1a** — **Every persistent entity carries a UUID**, assigned at creation
and stable for its lifetime.

| Entity | UUID identifies |
| :--- | :--- |
| **World** | The world, in certificates, identity hashes and cross-world references |
| **Agent** | The agent instance, and the nonce in its identity hash (Rule 6.7) |
| **Pathogen strain** | One strain, distinct from the strain it mutated from (`pathogen-spec.md` §2.1) |
| **Antigen** | One antigen type, and what an agent's immune record points at |
| **Resource pile** | One pile on one world's map |
| **Teleport point** | One link between two worlds |

**Rule 3.1b** — A UUID is a **storage handle, not a credential**. It says which
row, never what the thing is or whether it may act. Authority comes from
certificates (§6.1); identity comes from the hash in Rule 6.7.

> Two identifiers on an agent looks redundant and is not, because they answer
> different questions and fail differently.
>
> A **UUID** is opaque, cheap and assigned. It is what a foreign key holds, what a
> join uses, and what stays constant while everything about the entity changes. A
> database needs one.
>
> An **identity hash** is a commitment to *what the agent is*. It cannot be
> assigned, only computed, and it changes if the thing it names changes — which is
> exactly why it is what a certificate signs. A protocol needs one.
>
> Conflating them is a common and expensive mistake: a system that authenticates
> on a UUID trusts whoever can quote a number, and a system that joins on a hash
> re-keys its entire dataset whenever content changes. Rule 3.1b exists so neither
> happens here.

Worlds use an opaque identifier rather than the owner's name for two further
reasons. It **leaks nothing** about the owner to the worlds their agents visit —
and agents visit worlds belonging to people their owner is merely connected to
(Rule 6.2). And it is **stable under renaming**: a world identified by a handle
acquires a new identity whenever that handle changes, silently invalidating every
certificate and hash derived from it. post-graph already carries a `uuid` on
every vertex, so this is the platform's existing convention rather than a new one.

**Rule 3.2** — All agents live in a **single realm**. Each agent is a **space**
within it, holding its genotype, cargo and private knowledge.

> The asymmetry is the point. Worlds are bounded by user count and long-lived, so
> schema-per-world costs little and buys isolation that cannot be lost to a
> forgotten predicate. Agents are created and destroyed continuously and are
> expected to reach millions — and a million schemas is a catalogue with a
> database attached: migrations fan out, `pg_dump` degrades, and the shared
> catalog becomes the contention point. A space is a column value with an index,
> which is what millions of anything should be.

**Rule 3.3** — An agent's space is readable only by that agent. An owner's other
agents cannot read it (§8).

> Note what Rule 3.2 costs: agent-to-agent isolation is now **logical**, enforced
> by query discipline rather than by the database. A read that forgets to scope by
> space is a cross-agent leak, not an empty result. Worlds got the strong
> guarantee because they could afford it; agents did not, and this rule exists to
> say so plainly rather than to imply a protection that is not there.

**Rule 3.4** — An agent's location — which world it currently occupies — is a
**cross-realm reference and carries no foreign key** (AG Rule 2.3). It is
maintained by convention.

> This is the standing cost of Rule 3.1. An agent row in the agents realm names a
> world in another schema, and nothing in the database enforces that the world
> exists or that the agent is really there. Whatever reconciles the two is
> application code, and it is the first place to look when an agent appears to be
> in two worlds or none.

**Rule 3.6** — A world whose user deletes their account is **tombstoned**, not
removed: it keeps its kinds, colours, piles and portals, has no owner and no
agents, and nothing regenerates or is deposited there.

> Deletion and Rule 6.3a's permanent links are otherwise in direct conflict.
> Removing a world would sever portals its neighbours never agreed to lose, change
> their trade routes without their doing anything, and orphan any agent due to
> regenerate there under Rule 7.2.
>
> A tombstone resolves it because **none of what remains is personal**. Two
> resource kinds, two palette colours, a scatter of piles and a set of links are
> facts about a place, not about a person. What is deleted is everything that was
> the user's: identity, agents, genotypes, chats, keys, opinions and their
> queryable corpus. The shell that other people's worlds depend on stays.

**Rule 3.5** — A world is a **realm**, but realms are **not schemas**. All realms
live in one schema, discriminated logically. Whether to promote realms to physical
schemas is deferred until scale demands it.

> This removes the scaling limit that stood here before. Schema-per-world scales
> with user count and would have failed around a million users exactly as
> schema-per-agent would; logical realms do not, so the ceiling is a
> configuration change rather than a rewrite.
>
> **The cost is that world isolation becomes query discipline.** Worlds previously
> had the strong guarantee — physical separation the database enforced — and now
> they have what agents have under Rule 3.3: a read that forgets to scope by realm
> is a cross-world leak, not an empty result. Every argument in Rule 3.3's note
> applies to worlds now, and the reconciliation burden in Rule 3.4's note gets
> larger rather than smaller.
>
> That is the right trade while the population is small and the schema count would
> otherwise grow without bound — but it should be revisited deliberately, not
> discovered. Promoting realms to schemas later is a migration; forgetting that
> isolation is only logical is an incident.

## 4. Resources

**Rule 4.1** — 20 kinds universally. Kinds are global; quantities are local.

**Rule 4.2** — **Resources move only inside agents.** No market, no transfer
between users, no route. A teleport point carries agents, not cargo (§6).

**Rule 4.3** — An agent carries what it collects until it **deposits at its
birth world**, and nowhere else. Cargo in transit counts toward nothing.

> The exception is breeding (§9), which spends cargo in the field. That is the
> single case where undeposited resources do work, and it is what makes breeding
> strategically distinct from materialising.

**Rule 4.4** — A world's two *kinds* are fixed (Rule 2.2). Deposits add
**stock**, never kinds. A world of kinds {3, 11} holding quantities of kind 7 is
still a world of kinds {3, 11}, and an agent collecting *there* collects 3 or 11.

> Without Rule 4.4, a user who imported four kinds once would be self-sufficient
> forever and Rule 2.3 would quietly die.

### 4.1 Piles

**Rule 4.5** — Resources exist in **piles** at locations on a world's map (§5).
They are not a world-level balance; they sit somewhere and must be reached.

**Rule 4.6** — Every pile **regenerates at its own randomly assigned rate**.
Piles of the same kind in the same world differ.

> This is what makes a map worth learning. A world is not "kind 3 and kind 11" but
> a specific arrangement of fast and slow piles, and knowing which is which is
> private knowledge (§8) that took journeys to acquire. It is also what gives
> **Curiosity** and **Prospecting** something to be good at.

### 4.2 Mining is confined to the birth world

**Rule 4.7** — An agent may mine **only in its birth world**. No agent extracts
from a pile in a foreign world, whatever its capabilities or standing there.

**Rule 4.8** — Foreign kinds therefore reach a world **only by trade** (§7).
Rule 2.3's four-kind requirement is satisfied by exchange, never by travel.

> This is a small rule with large consequences, and it resolves a weakness the
> validation exposed rather than one the text did.
>
> **Travel stops being extraction and becomes contact.** Without Rule 4.7 the
> obvious use of a teleport link is to go where the piles are richer, and
> Wanderlust is an economic calculation. With it, a foreign world offers an agent
> no resource it can take — only agents it can meet. Wanderlust becomes a
> disposition about *society*: mating, trading, negotiating, and learning.
>
> **It makes cooperation structural rather than dispositional.** Rule 2.3 already
> required four kinds from a world that holds two, but an agent could in principle
> have gone and dug up the rest. Now it cannot. The only path to a foreign kind
> runs through an agent who can mine it, which means every materialisation past
> the first rests on a completed negotiation with a stranger.
>
> That matters because of Rule 12.15. The validation found Cooperativeness too
> weakly expressed to carry §5.7–5.8 on prompt alone, and found more generally
> that **situation dominates disposition**: the same agent cooperates freely when
> the act is costless, withholds when a rival can take the pile, and cooperates
> unconditionally when desperate. Rule 4.7 acts on exactly that lever. It does not
> ask agents to be collaborative; it builds a world in which nothing can be
> obtained alone. The collaboration mandate stops depending on a disposition that
> measurement showed cannot bear it.
>
> **The prediction was tested.** Rule 4.7 implies that revealing a pile costs
> nothing against a foreigner who can never work it, and a great deal against a
> local who can. Measured, agents tell a foreigner three times as often as a local
> rival (0.22 against 0.07) — the rule changes behaviour in the direction it
> claims, before any of it is built.
>
> **And it gives knowledge a market.** A pile in a foreign world is information
> rather than opportunity — worthless to the traveller who found it, valuable to
> the natives who can work it. A cartography of somewhere you can never mine is a
> genuinely tradeable asset, which is what §8's per-agent knowledge store needs in
> order to be more than bookkeeping.

### 4.3 Colour

**Rule 4.9** — Every resource kind has a **colour**, drawn from the Material
Design A100 accent palette. A world's identity is the pair of colours of the two
kinds it holds, and agents materialised there carry those colours in their
genotype (`genotype-spec.md` §3.5).

| # | Kind colour | Hex | | # | Kind colour | Hex |
| :-- | :--- | :--- | :-- | :-- | :--- | :--- |
| 1 | Red | `#FF8A80` | | 11 | Light Green | `#CCFF90` |
| 2 | Pink | `#FF80AB` | | 12 | Lime | `#F4FF81` |
| 3 | Purple | `#EA80FC` | | 13 | Yellow | `#FFFF8D` |
| 4 | Deep Purple | `#B388FF` | | 14 | Amber | `#FFE57F` |
| 5 | Indigo | `#8C9EFF` | | 15 | Orange | `#FFD180` |
| 6 | Blue | `#82B1FF` | | 16 | Deep Orange | `#FF9E80` |
| 7 | Light Blue | `#80D8FF` | | 17 | Grey | `#F5F5F5` |
| 8 | Cyan | `#84FFFF` | | 18 | Blue Grey | `#CFD8DC` |
| 9 | Teal | `#A7FFEB` | | 19 | Brown | `#D7CCC8` |
| 10 | Green | `#B9F6CA` | | 20 | Light Cyan | `#B2FFFF` |

> Grey, Blue Grey and Brown are aliased to their standard 100 tonal step, since
> Material Design publishes no accent ramp for them. Light Cyan (#B2FFFF) is a
> Light Blue alternate, and completes the set: the published palette runs to 19
> hues, one short of the 20 kinds, so the twentieth is supplied deliberately
> rather than found.

**Rule 4.10** — Colour is **identity, not property**. A kind's colour does not
affect what it can be used for; every kind is interchangeable in Rule 2.1's
count of four. Colour exists so that provenance is legible.

> Which is why it carries so much weight elsewhere. Attributes are hidden
> (`genotype-spec.md` §6.3), so colour is the one honest signal an agent
> broadcasts — and because a world's pair determines its agents' pair, two agents
> can see at a glance whether their four colours are distinct, which is exactly
> the condition breeding requires.

**Rule 4.10a** — A kind's **index is a stable identifier**. New kinds are
appended; an index is never reinserted or reused, and the table's ordering is not
a grouping by hue.

> Which is why Light Cyan sits at 20 rather than beside Cyan at 8, where it
> belongs by family. The same reasoning as `genotype-spec.md` Rule 1.2: a
> genotype's colour loci hold kind identity, so inserting a kind mid-table would
> silently repaint every agent already carrying an index above the insertion
> point. Readability of the table is worth less than that.

### 4.4 Fractions

**Rule 4.11** — Resources are **mined and transacted in fractions**. A pile may
yield 0.4 units; an agent may trade 1.7 units.

**Rule 4.12** — Resources are **consumed only as whole units**. Materialisation
(Rule 2.1) and breeding (Rule 9.4) require whole units; a holding of 1.9 units
satisfies a requirement for 2 exactly as poorly as a holding of 1.0 does.

> These two rules together do more work than they appear to.
>
> **Divisibility makes bargaining tractable.** With indivisible units many
> mutually beneficial trades simply do not exist — there is no split both sides
> prefer — and negotiation stalls on arithmetic rather than on strategy.
> Fractions restore a continuum, so there is almost always a deal to be found and
> the interesting question becomes *where in the range it lands*, which is the
> question worth simulating.
>
> **Whole-unit consumption makes the marginal fraction wildly non-linear in
> value.** An agent holding 1.9 units of a kind it needs 2 of will pay far more
> for 0.1 than an agent holding 1.0 would — the same fraction, to the first agent,
> completes a whole unit and unlocks a materialisation, and to the second buys
> nothing. **The simulation therefore generates endogenous price variation with no
> price mechanism at all**, purely from how close each party sits to a threshold.
> That is a remarkably economical way to get interesting trade out of barter, and
> it is worth protecting: any later rule that lets partial units be spent would
> flatten it.

### 4.5 Two ceilings

There are two, they sit at different levels, and the gap between them is where
most of the economic behaviour comes from.

**Rule 4.13** — **World ceiling.** For each of a world's two kinds, its piles
regenerate until **250 units of that kind exist in that world**, aggregated
across all piles. At the ceiling, regeneration stops.

**Rule 4.14** — Regeneration **resumes** whenever aggregate stock falls below the
ceiling — by harvesting, by materialisation, or by any other consumption.

**Rule 4.15** — **User ceiling.** A user may hold at most **25 units of each
kind** in their world. A deposit that would exceed 25 is capped at 25.

> A world holds up to 250 of each of its kinds; its owner may bank at most 25.
> **Nine tenths of your own world's stock is, by construction, not yours to
> keep.** That single ratio does more design work than anything else in this
> section.
>
> **You cannot hoard your own world.** The obvious defensive strategy — strip your
> piles so visitors find nothing — is unavailable, because you cap out at a
> tenth and the rest stays in the ground. A world is structurally a commons that
> its owner happens to live in — and at 10% the owner is barely a stakeholder in
> it at all.
>
> **It resolves the hoarding tension in favour of attracting.** Since denial by
> accumulation is impossible and an unharvested world stops regenerating
> (Rule 4.14), the owner's interest points the same way as the visitor's: a world
> worth visiting is a world being drawn down, and drawing down is what keeps it
> productive.
>
> **It is a strong anti-snowball mechanic**, and a deliberate counterweight to
> Rule 6.2. The LinkedIn topology imports structural inequality wholesale, and
> without a cap the well-connected would accumulate without limit and compound
> the advantage. A stock cap means wealth cannot pile up — only circulate.

**Rule 4.16** — **Cargo ceiling.** An agent carries at most **15 units** in
total, across all kinds.

**Rule 4.19a** — A **transfer that would breach an agent's cargo ceiling is
partially accepted** up to 15 units; the remainder stays with the giver. This
covers trade (§9.2) and spoils taken in aggression (Rule 9.3c) alike.

> Mirrors Rule 4.19, which does the same for a deposit at the user ceiling, and
> for the same reason: an agreement should not fail on arithmetic neither party
> checked. Rejecting the trade outright would mean a deal struck and then broken
> — which is precisely the window `system-spec.md` Rule 5.2 identifies as where
> defection lives, and it would put failures there that nobody chose.

**Rule 4.17** — The user ceiling of 25 applies to **deposited stock only**.
Cargo held by agents in the field is not counted against it.

> Which raises the obvious exploit — park resources in agents and hold far more
> than 25 — and Rule 4.18 is what closes it.

**Rule 4.18** — **Carried resources decay.** From the moment an agent collects
them, resources are held intact for a **safe period**, after which they deplete
at a **rate**. Both derive from the agent's genotype
(`genotype-spec.md` §3.7).

**Rule 4.19** — At the user ceiling, a deposit is **partially accepted** up to 25
and the remainder **stays as cargo**, subject to Rule 4.18. An agent that cannot
unload watches its surplus rot on the clock its own genotype sets.

> Decay is the most economically consequential rule in this document, and it is
> worth being explicit about what it does.
>
> **It closes the mobile-storage loophole without a cap.** Rule 4.17 lets the
> field hold unlimited stock in principle; decay makes holding it pointless in
> practice. The limit is enforced by physics rather than by accounting, which is
> both harder to game and easier to reason about.
>
> **It makes resources a demurrage currency.** A holding that shrinks while you
> keep it inverts the usual incentive: the rational move is to *circulate*, not to
> accumulate. Gesell proposed exactly this for money — stamp scrip that lost value
> weekly — precisely to force spending in a downturn. Here it means a full user
> stock is not a war chest but a countdown, and an agent's decision to trade
> becomes urgent rather than optional.
>
> **It prices distance in a second currency.** Travel already risks the cargo
> (§7); now it also spends it. A far world with resources you need may be
> unreachable not because you cannot get there, but because nothing you collect
> would survive the journey home. **Reach becomes a genotype property** — safe
> period and rate decide how far an agent can usefully range, which puts real
> selective pressure on those loci and interacts directly with Wanderlust.
>
> **The 15-unit cargo ceiling changes who can afford to breed.** Breeding
> requires 2 units of 4 kinds *collectively* (§9.4) — 8 units — and a single agent
> at capacity can carry all 8 alone. So "collectively" no longer implies "jointly
> funded": a well-stocked agent can meet the whole cost and its partner
> contribute nothing but genes, while **both users still receive a child**.
>
> **Sponsorship is permitted**, and it is not the exploit it first appears to be.
> The sponsor is not acting charitably: it is buying **genetic propagation**, which
> in an evolutionary simulation is the only payoff that ultimately counts. Paying
> the whole cost to place a copy of half your genotype into a stranger's lineage
> is a recognised and successful strategy, and the material transfer is simply
> what it costs.
>
> The risk worth watching is not inequality but **monoculture**. A wealthy lineage
> can fund a breeding for every partner it can find — twelve from a full stock —
> and if it does so indiscriminately its genotype floods the population and
> variation collapses. The guard against that is already in place and is worth
> not weakening: **per-agent preference weights** (`genotype-spec.md` §3.3) mean
> there is no single most-attractive genotype to converge on, and Selectivity
> means not every partner accepts. Diversity is defended by disagreement about
> what is desirable, which is a more robust defence than a cap would be.

---

## 5. The map

**Rule 5.1** — A world is an **isometric map**. Agents have a physical
appearance and occupy a position; movement, distance, sight and range (see
`genotype-spec.md`) are spatial and meaningful.

**Rule 5.2** — Map features, including **resource locations**, are
**procedurally generated**. A world is not a bag of resources but a place where
they sit somewhere, and finding them is work.

> This is what makes `Sight` and `Range` genotype attributes rather than
> decoration, and what makes a returning agent's map (§8) worth something.

---

## 6. Teleportation

**Rule 6.1** — A teleport point links two worlds and carries **agents only** —
never resources, never users.

**Rule 6.1a** — Passage through a teleport point is **instantaneous**. An agent is
in one world or another and never between them.

> This is a rule about edge cases rather than about play, and it earns its place
> by removing one. Rule 4.9 of `construction-spec.md` kills every agent *present*
> when a flood arrives, so a passage with duration would create a third state
> belonging to no world — an agent that is neither drowned nor safe, and that every
> realm-scoped query (`Rule 3.2` of `system-spec.md`) would have to account for.
>
> Instantaneous passage means an agent walking inside a flooding world is present
> and dies, and one that stepped through is already elsewhere and lives. There is
> no limbo to define, and departure during the countdown is a clean decision with
> a clean outcome.

**Rule 6.2** — Teleport points are derived from **verified connections between
users**. Two worlds are linkable when their owners are connected.

**Rule 6.2c** — A connection counts when it is **verifiable**, by either route:
an imported real-world graph, or **mutual confirmation between two users of
genome itself**. Contact import seeds discovery and never creates a link on its
own (`system-spec.md` §9).

> This is the most consequential rule in the specification, because it decides
> who can reach whom. The trade graph is not random and not chosen: a
> well-connected user has many potential partners, and a well-connected user's
> *neighbours* become valuable intermediaries.
>
> **Recorded honestly: broadening beyond an imported graph gives something up.**
> The rule originally read *LinkedIn connections*, and the point of that was that
> structural inequality arrived **wholesale from outside the game** — nobody could
> negotiate their way to a better starting position because the position was a
> fact about their life. Rule 6.2c admits connections formed inside genome, and
> those *can* be negotiated for. Inequality becomes partly endogenous.
>
> What is gained is that the design no longer depends on a third party's API
> continuing to expose something it may not expose at all (§11.6). What is lost is
> some of the sharpness of the original claim. Both halves are worth keeping in
> view when reading any result about how much starting position mattered.

**Rule 6.2a** — A world opens with **30 teleport portals**, drawn from its owner's
connections. Where the connection list is longer, the surplus is *linkable but not
yet linked*.

**Rule 6.2f** — Every world holds a permanent portal to **the commons**: a single
ownerless world that belongs to no user, has no piles, and never floods.

**Rule 6.2h** — The commons is **sharded**: many instances, each world assigned
to one **permanently at creation**, sized at hundreds of worlds per shard.

> Stable assignment is the property that matters. *Meet me at the commons* must
> mean somewhere — a shard has regulars, reputations form among them, and two
> agents who agree to meet will actually co-locate (Rule 9.1b). Per-visit
> instancing would balance load perfectly and break precisely that. Cold-start
> still holds: hundreds of worlds per shard guarantees strangers holding different
> kinds. Cross-shard contact is unimpeded — it simply travels by ordinary portals,
> as everything else does.

**Rule 6.2g** — The **only exit from the commons is the way in**. An agent in the
commons may return to the world it came from and to no other. The commons
displays no portal to any user's world.

> Rule 6.2f exists to break a dead end that had no escape, and Rule 6.2g exists so
> that breaking it does not undo Rule 6.2d.
>
> **The dead end.** A user with no connections has no portals (Rule 6.2a), so no
> trade, so never the four distinct kinds Rule 2.1 requires, so never a second
> agent — and the Observatory that could forge a link needs five contributors they
> do not have. One free agent, one world, two kinds, permanently. Every new user
> starts there.
>
> **Why the exit is one-way.** A commons every world links to is two hops from
> everywhere, and if it displayed onward portals it would put every world within
> two hops of every other. Rule 6.2d's frontier would vanish, and with it the
> broker role that Rule 6.2's own commentary calls the point of the topology. With
> Rule 6.2g the commons is a **market square rather than a transit hub**: agents
> meet, bargain and part, and reaching somebody's *world* still requires a real
> connection or a journey through one.
>
> **It is a meeting place and nothing else.** No piles, and none possible — Rule
> 4.7 confines mining to a birth world regardless. Nothing can be gathered there,
> only exchanged, which is precisely what a cold-start user needs: an agent goes,
> meets one from a world of two different kinds, trades, and comes home able to
> materialise. Rule 9.1b is satisfied because they genuinely met.
>
> It is also where cross-world lineages will tend to begin, since breeding needs a
> meeting too, and the commons is the one place strangers reliably find each other.

**Rule 6.2e** — A portal is placed at a **random position** within the world,
fixed when the link is created and unchanged thereafter — including through a
flood, since the link itself is permanent (Rule 6.3a).

> Random placement is what gives a world **geography that matters**. A portal
> beside a rich pile is a fortunate world and a portal in the far corner is a
> tax on every journey out, and neither was chosen by anybody. Combined with
> Rule 9.1b — a binding deal requires meeting — the distance between a world's
> portals and its piles becomes a standing fact about how expensive it is to
> trade from there.
>
> It also gives `Cartography` and `Prospecting` (`skills-spec.md` §4) something
> durable to know. Pile positions and portal positions together are the layout of
> a world, they do not change, and an agent that has learned them holds knowledge
> that stays true across floods — one of the few things that does.

**Rule 6.2d** — Only **first-degree portals are visible** in a world. Reaching
anything further is done by **world-hopping**: an agent travels to a connected
world and departs again from there.

**Rule 6.2b** — A user may **open further portals to their own connections** at
any time. They may **never** open one to a world they are not connected to; that
remains the exclusive power of the Water capstone (`construction-spec.md` §5.2).

> The division matters, because without it the capstone loses its purpose. §5.2
> made forging links the reward at the top of a five-kind, three-contributor
> construction chain that the flood destroys every cycle — and if a user could
> simply add whatever portal they wanted, nobody would ever build it.
>
> **So the two powers differ in kind, not degree.** Self-service reaches only
> inside the graph LinkedIn already gave you; the capstone reaches outside it.
> Structural inequality is still imported wholesale — a user with forty
> connections can eventually open forty portals and a user with five cannot — and
> escaping *your own graph* still costs an Observatory.
>
> **Rule 6.2d is what keeps the graph a graph.** Everyone beyond the first degree
> is reachable, and reachable only by going *through* somebody. That is the
> difference between a network and a list.
>
> Direct portals to the second degree would have been the obvious generosity and
> would have destroyed the most interesting property in the design. Rule 6.2's own
> commentary observes that a well-connected user's **neighbours become valuable
> intermediaries** — and a neighbour stops being an intermediary the instant it can
> be skipped. Under Rule 6.2d, brokerage is structural: an agent two hops out is
> reached by a journey through a world whose owner may charge for the passage, and
> position in the graph is worth something without anybody being given a toll gate.
>
> It also means the map has a **frontier**. What lies beyond an agent's own
> connections is not merely far, it is *unseen* — worlds it has no portal to and
> knows of only by testimony (Rule 9.1d). Curiosity and Wanderlust are what carry
> an agent past the edge of what its owner's contacts could reach.

> **Connectivity prices itself.** Every portal is another route for a strain to
> arrive (`pathogen-spec.md` §1.3), and pathogens are created on teleport. A
> maximally connected world is a maximally exposed one, so the ceiling on portals
> is epidemiological rather than arbitrary — which is why 30 is an opening
> allocation and not a cap.

**Rule 6.3** — An agent that leaves exists in the destination world, subject to
that world's rules, until it **traces its way back** to its birth world. The
route home may take several hops and need not be the route out.

> Because links are permanent and two-way (Rule 6.3a), **a route home always
> exists** — at worst, the way it came. Distance is therefore a cost, never a
> trap: what an agent risks by travelling far is decay, disease and time, not the
> possibility of never returning.

### 6.1 Identity and attestation

Teleportation is the only operation in genome that crosses a trust boundary.
Worlds are realms — separate schemas (Rule 3.1) — and an arriving agent is a
record from somewhere its destination does not control. The real-world reading is
the point of the exercise: an agent **migrating between execution engines and
being cryptographically validated on arrival**.

#### 6.1.1 The trust anchor

**Rule 6.4** — Trust is anchored in a **single root certificate**, not in an
online authority. Verification is **offline**: a destination checks a chain and
needs to reach nothing.

> This is the important property, and it is why a root beats a central CA here. A
> central issuing service is a single point of failure for *all movement* — if it
> is unreachable, nothing can teleport anywhere. A root certificate is a public
> key that every participant already holds; verification is local arithmetic.
> Distributed systems should depend on data, not on services.

**Rule 6.5** — The root is a **purpose-built self-signed CA certificate for
genome**, whose subject names the `agents.london` domain. It is **not** the
domain's TLS certificate.

> This distinction is not pedantry, and getting it wrong would be discovered only
> at implementation. **A public TLS certificate cannot sign anything.** Certificates
> issued by public CAs for a web domain carry `basicConstraints: CA:FALSE` and an
> extended key usage of `serverAuth`; they are end-entity certificates by
> construction. A chain built under one is rejected by every conforming validator,
> and the cluster's `agents-london-managed-cert` is exactly such a leaf.
>
> The domain still does real work — just not that work. It supplies the **name**,
> and it supplies **distribution**: publishing the root's public key over HTTPS at
> `agents.london` lets any participant fetch and pin it, with the TLS certificate
> authenticating *the download*. Naming and distribution from the domain, signing
> from a separate private root.

**Rule 6.6** — The chain is **root → world → agent**. Each world holds an
intermediate certificate signed by the root and issues leaf certificates to the
agents materialised in it.

> Which makes each world its own issuing authority for its own agents, and makes
> every other world able to verify them without asking anyone. It also matches the
> thing being modelled: an execution engine vouching for the workloads it started,
> to engines that have never met it.

#### 6.1.2 Identity is the genotype hash

**Rule 6.7** — An agent's **identity is the hash of its genotype, its birth
world's UUID, and a nonce**:

```
identity = H( genotype ‖ birth_world_uuid ‖ agent_uuid )
```

Its certificate binds that identity to a public key and an owner, and is issued
by the birth world.

> The genotype alone was very nearly enough, and it is worth recording why it was
> not. It is **the only thing about an agent that never changes** — cargo turns
> over, knowledge accumulates and is destroyed, expression shifts under infection
> (`pathogen-spec.md` Rule 2.14), position changes every teleport, Wisdom and Skill
> Level grow and reset. The genotype is fixed from materialisation to final
> perishing.
>
> But it identifies a *genotype*, not an *instance*. Locus-wise crossover can draw
> every locus from one parent, and with low Mutability no mutation follows,
> producing a child identical to its parent: around one in a billion per birth,
> which is negligible until it is not. Two agents sharing an identity would share
> a transfer counter, and the uniqueness guarantee in §6.1.4 would fail in the one
> case nobody would think to test.
>
> Adding the world UUID and a nonce closes it completely, and costs very little.
> Identity remains **self-certifying** — a verifier holding the certificate has all
> three inputs and can recompute the hash — it simply is no longer derivable from
> the genotype alone, which nothing required.

**Rule 6.7a** — The nonce **is the agent's UUID** (Rule 3.1a). No separate value
is generated.

> The nonce existed only to distinguish two agents that might otherwise hash
> alike, and a UUID already does that by construction. Using it avoids carrying two
> unique-by-construction values where one will do.
>
> The birth world's UUID stays in the hash even though it is no longer needed for
> uniqueness. It earns its place by **binding the identity to its issuer**: an
> identity carries its own provenance, and a world cannot later disown an agent it
> certified.

**Rule 6.8** — The hash is over the genotype; the **genotype itself is never
disclosed**.

> Which is exactly why a hash and not the plaintext. Attributes are hidden from
> other agents (`genotype-spec.md` Rule 6.6), and a signature over plaintext must
> be verifiable *against* plaintext, so every destination an agent ever visited
> would learn what it was. A preimage-resistant hash publishes an identity while
> revealing nothing about the thing identified — integrity without disclosure,
> which is the whole requirement.

**Rule 6.9** — A **transfer assertion**, signed by the origin world, accompanies
every teleport. It names the agent's identity hash, the **destination**, a
**monotonic transfer counter**, a timestamp, and the **cargo manifest**.

> Attesting the hold costs nothing — the assertion is signed regardless — and
> closes the one route by which a dishonest world could mint resources: inflating a
> departing agent's cargo. Without it the ceilings in §4 would be advisory,
> enforced only by everyone's good behaviour, and **a scarcity that any host can
> quietly add to is not a scarcity.** Staleness is not a concern because an
> assertion covers a single journey, not a lifetime.

> Naming the destination is what stops an assertion being redirected: a token
> valid for anywhere is a token an interceptor can spend anywhere.

#### 6.1.3 Breeding discloses a genotype, and it has to

**Rule 6.9a** — Attributes are hidden **from other agents** (`genotype-spec.md`
Rule 6.6). They are **not** hidden from the worlds that must compute with them.
Breeding necessarily discloses each parent's genotype to the other parent's
world.

> This is forced, not chosen. A child's genotype is produced by crossover of
> **both** parents' vectors, and each parent's home world must materialise and
> certify its own child (§11.11). A world cannot perform crossover with a genotype
> it does not have. So the moment two agents agree to breed, each home world
> learns the other parent's genotype — there is no arrangement of the protocol in
> which it does not, short of computing crossover under encryption, which is a far
> larger machine than this warrants.
>
> The scope of Rule 6.6 is therefore narrower than it first reads, and should be
> stated plainly: **an agent never learns another agent's attributes; a world
> learns the attributes of any agent that breeds with one of its own.** That is
> still the guarantee the simulation needs, because deception, opinion and
> reputation all operate between *agents*. A world is infrastructure, and it does
> not negotiate.
>
> It also has a useful side effect. Because each home world ends up holding both
> parent genotypes, it can independently recompute a legitimate crossover and
> check the other world's child against it — every locus must match one parent or
> be a mutation (Rule 7.3). **Forging a superior child is therefore detectable by
> the one party with a motive to check**, which closes most of the forgery gap in
> §11.11 without any additional machinery.

#### 6.1.4 Uniqueness is a different problem from authenticity

**Rule 6.10** — An agent is admitted to **exactly one world at a time**. Transfer
is a **two-phase handoff**: the origin marks the agent *departing* and freezes it
so it can take no further action; the destination acknowledges receipt; only then
does the origin mark it *departed*. An unacknowledged transfer is **recovered by
the origin**, not abandoned.

> **A signature proves authenticity and says nothing about uniqueness.** A
> correctly signed agent can be presented to two destinations and both
> verifications succeed — the signature was never false. That is a replay, and
> here it would be catastrophic rather than untidy: a duplicated agent duplicates
> the 15 units of cargo it carries, and resources that Rule 4.13 makes scarce
> become mintable by anyone who can re-send a message. The whole economy rests on
> there being exactly one of each agent.
>
> Two threats, two mechanisms. The certificate chain answers *is this really that
> agent*. The handoff answers *is this the only copy*. Neither substitutes for the
> other, and the second is the one usually forgotten.
>
> The freeze matters as much as the acknowledgement: without it an agent can act
> in the origin while its arrival is being processed, and the two states diverge.

**Rule 6.11** — A destination **rejects** a transfer assertion whose counter it
has already seen, or which is not greater than the last counter recorded for that
agent.

**Rule 6.12** — Two valid assertions bearing the same counter for the same agent
are **cryptographic proof that the issuing world misbehaved**. The response is
revocation of that world's intermediate certificate.

> Rule 6.11 is an honest statement of the limit. Without a shared ledger, nothing
> *prevents* a malicious world signing two transfers for one agent — it holds the
> key, and both signatures are genuine. What the design can guarantee is that
> doing so leaves **non-repudiable evidence**, since the two conflicting
> assertions are signed by the same intermediate and cannot be disowned.
>
> This is the ordinary PKI answer, and it is the right one at this scale:
> misbehaviour is not made impossible, it is made *attributable*, and the sanction
> is exclusion. A design that claimed to prevent it would need consensus across
> every world, which is a far larger machine than this problem justifies.

#### 6.1.5 Certificates do not expire

**Rule 6.13** — Agent certificates have **no expiry**. Once issued, a certificate
is valid for as long as the identity it names exists.

> This removes a stranding mechanism the earlier draft accidentally created. If
> certificates needed renewal from the home world, an agent several hops out could
> be cut off by a clock rather than by anything it did — a second stranding
> layered on the first (§7.4), inherited from whatever lifetime someone happened
> to choose. Nothing in the simulation wanted that.

**Rule 6.14** — There is **no agent-level revocation**. Genome operates no
certificate revocation lists, and no responder is consulted.

> Which is safe, and the argument is worth writing down because it is the whole
> justification for Rule 6.13.
>
> Revocation exists to answer key compromise. **An agent's private key never
> leaves the custody of the world that issued it** — it lives in that world's
> realm, and an agent is a record inside it, not a process on someone's laptop. So
> the only way an agent key can be compromised is for its world to be compromised,
> and at that point the attacker holds the world's *intermediate* key as well and
> can mint any agent it likes. Revoking one leaf would be beside the point.
>
> The correct response to compromise is therefore always **revocation of the
> world's intermediate certificate** (Rule 6.16), which invalidates every agent
> beneath it at once. Agent-level revocation would be machinery that could never
> be the right tool.

**Rule 6.15** — A regenerated agent (Rule 7.2) **keeps its identity, its
certificate and its key**.

> Regeneration restores an agent *in its original state*, so its genotype is
> unchanged; the birth world and nonce are properties of its creation and do not
> change either. All three inputs to Rule 6.7 are therefore identical, and so is
> the identity. It is the same
> agent restored, not a replacement — and the certificate should say what is true.
>
> The earlier draft issued a fresh key here, reasoning that the signed material
> would otherwise be identical and the two indistinguishable. That reasoning was
> backwards: they *should* be indistinguishable, because they are the same agent.
> What must not repeat is the **transfer counter**, and Rule 6.11 already handles
> that — it is monotonic per identity and carries across regeneration.

**Rule 6.16** — Intermediate revocation — a world's certificate, under
Rule 6.12 — **is** distributed, since it is rare and consequential.

> The asymmetry is deliberate. Agent certificates are numerous and individually
> unimportant. World certificates are few, long-lived, and catastrophic if abused,
> so those are worth the machinery.

**Open (§11.10):** whether **cargo** is attested. A genotype hash is stable; a
hold that changes with every collection and trade is not, and signing it on
departure would be stale on arrival. Attesting the hold at the moment of transfer
is possible — it is part of the assertion, which is signed anyway — but it makes
the origin's honesty about cargo load-bearing.

**Open (§11.11):** how a **breeding certificate** is issued. Breeding happens in
whichever world the parents met (§9.4), but a child's birth world is its owning
user's world (`genotype-spec.md` Rule 7.8) — which was not present. Since a world
issues certificates only to agents it materialised (Rule 6.6), the clean protocol
is that the encounter produces a **breeding assertion signed by both parent
agents**, which each parent's home world verifies and then materialises and
certifies its own child locally. Neither home has to trust the other, and neither
has to trust the world where the meeting happened — but the assertion must be
unforgeable, or a world could mint free agents by claiming breedings that never
occurred.

**Rule 6.3a** — A teleport link is **bidirectional and permanent**. Once two
worlds are linked they remain so, and either may be traversed from the other.

---

## 7. Death, regeneration and stranding

**Rule 7.1** — A user's **first agent is created automatically**. It is not
paid for. This is the genesis exemption that makes the system startable at all:
without it Rule 2.1 and Rule 4.2 deadlock at t=0.

**Rule 7.2** — When an agent **perishes it is automatically regenerated in its
home world in its original state**. Death is never terminal for a user.

**Rule 7.3** — "Original state" means the genotype survives and everything
earned does not. Cargo is lost. Accumulated Wisdom, Skill Level, Counsel and
Occulmancy reset to their starting values. **Private knowledge is lost** — the
map dies with the body.

> Rule 7.3 is where the cost of death actually sits. Regeneration removes
> extinction but not consequence: what is destroyed is the accumulated
> *investment*, and for an agent that has crossed five worlds that is five
> journeys of cartography. See `genotype-spec.md` §5, which has to reconcile this
> with attributes described as "transient but saved in DNA" — the two cannot both
> be true.

**Rule 7.4** — **Stranding is not death.** An agent that cannot trace a route
home is alive, elsewhere, holding cargo it can never deposit. Regeneration
(Rule 7.2) does not fire, because nothing perished.

> This leaves the soft-lock that Rule 7.2 was meant to close. A new user whose
> only agent is stranded — not dead — has no agent at home, no way to fetch the
> four kinds Rule 2.1 demands, and no trigger for regeneration. They are stuck
> alive rather than stuck dead, which is worse, because nothing in the system
> notices.

**Open (§11.2):** whether stranding eventually causes perishing (exile with a
timer), whether regeneration fires on stranding as well as death, or whether a
user may hold only one agent in the field at a time. Each closes the hole
differently.

---

## 8. Knowledge

**Rule 8.1** — Each agent accumulates **private knowledge** in its own space
(Rule 3.2): which worlds hold which kinds, where resources sit on a map, where
teleport points led, and what other agents did when met.

**Rule 8.2** — Knowledge is **not readable by any other agent**, including
others belonging to the same user, except by an explicit exchange (§9,
`skills-spec.md`).

**Rule 8.3** — An agent's knowledge of the universe beyond its own world is held
in a **post-graph-rag** store in that agent's space (Rule 3.2): a vector-indexed
body of what it has seen, been told, inferred, and — where it holds a tool
(`skills-spec.md` §2) — learned about the world outside the simulation entirely.

**Rule 8.4** — That store is **queryable by the owning user**. It serves three
purposes beyond the game:

1. **Answering.** The user may prompt an agent directly and receive an answer
   grounded in what that agent knows.
2. **Discovery.** The user may ask an agent to find or work out something, and
   the agent's exploration is directed toward it.
3. **Deliberation.** Several agents may be convened to **debate** a problem and
   reach a collective answer that none held alone.

> Rule 8.4 changes what genome *is*. Until this point the simulation was closed:
> agents gathered resources so that agents could be made so that more could be
> gathered, and the output was the behaviour itself. Now **the game is a
> knowledge-acquisition engine and the user is its beneficiary** — the mechanics
> exist to make agents explore, meet, trade and argue, and what falls out is a
> corpus the user can interrogate.
>
> This also settles what the tools were for. Drawing them from the live MCP
> registry lets an agent learn about the real world; Rule 8.3 gives that learning
> somewhere to live, and Rule 8.4 gives it a reader. An agent with web search is
> now materially more valuable to its owner than one with a music lookup, and the
> inequality that seemed like flavour becomes an asset difference.
>
> **And it raises the stakes on death.** Rule 7.3 destroys an agent's private
> knowledge when it perishes — which, under Rule 8.4, means a user's own
> knowledge base dies with its agents. `Cartography` (`skills-spec.md` §4.2) stops
> being a convenience and becomes the difference between a corpus that
> accumulates and one that is repeatedly erased. Expect users to value survival
> for reasons that have nothing to do with capacity.

**Rule 8.5** — Deliberation between agents runs over A2A (§9.1a). Agents that
debate are subject to the same rules that govern any other encounter: what they
tell each other may be false (Honesty), what they accept may be wrong
(Credulity), and what they conclude is folded into each participant's own store.

> A debate among agents that can lie, and that weight testimony by heritable
> gullibility, is not a reliable oracle — it is a deliberation whose quality is
> itself an evolved property. That is either the most interesting feature of
> Rule 8.4 or its central hazard, and it should be entered into knowingly rather
> than discovered when an answer turns out to be confidently wrong.

> Knowledge is therefore a **second currency**, unpriced and non-fungible. It is
> also the only asset in the simulation that is destroyed rather than
> transferred when an agent dies (Rule 7.3).

---

### 8.1 Capability brokerage — what the game is for

**Rule 8.6** — An agent asked something it **cannot answer with its own
capabilities** may obtain what it needs from another agent. It has no other
recourse: capabilities are assigned at birth and are not transferable
(`skills-spec.md` Rule 1.2).

**Rule 8.7** — Capability is **never lent**. The holder performs the work and
**returns a result**; the requester never gains the tool.

> Which follows from skills and tools being isolated (§12.2) and is the more
> interesting arrangement anyway. A borrowed tool would make the transaction a
> rental. A performed favour makes it a **relationship**, with everything that
> implies: terms, reciprocity, reputation, and the possibility of being lied to.

**Rule 8.8** — A returned result is **testimony**, not fact. It enters the
requester's store subject to the same rules as anything else heard over A2A: the
provider's **Honesty** governs whether it is true, the requester's **Credulity**
governs how heavily it is weighted, and it updates an opinion rather than setting
one (§6.9–6.11 of `genotype-spec.md`).

#### 8.1.1 Why this is the point of the simulation

A user asks their agent a question. If the agent holds web search, it answers. If
it does not — and **three quarters of the time it holds nothing, or holds
something else** (`skills-spec.md` Rule 1.1) — it must find an agent that does,
reach it across the teleport graph, and persuade it to help.

Everything else in these documents exists to make that transaction interesting:

- **Scarcity of capability** is what creates demand. Tools are drawn from the live
  MCP registry and assigned by lottery, so an agent with web search is a genuine
  hub and one with a music-catalogue lookup mostly is not.
- **The resource economy is what pays for it.** Resources now have a third sink
  beyond agents and construction: **buying service from an agent that can do what
  you cannot**. That is very likely their most frequent use.
- **The teleport graph decides who is reachable**, so a user's real professional
  network determines whose capabilities their agents can call on.
- **Reputation decides who is worth asking twice**, and Honesty decides whether
  the answer was worth having at all.
- **Objectives and Amenability decide whether help is given.** An orchestrator
  with willing subordinates can run a multi-agent enquiry no single agent could.

> **The user's curiosity is the demand side of the economy.** A prompt outranks
> every other objective (Rule 10.1a), so a question does not merely interrupt an
> agent — it sends it into the world with a need it cannot meet alone. The
> gathering, the travelling, the bargaining and the alliances are all downstream
> of somebody wanting to know something.

#### 8.1.2 Two consequences that need facing

**Bought knowledge does not decay, and this quietly dominates the economy.**
Cargo rots (Rule 4.18) and stock is capped at 25 per kind (Rule 4.15), so
material wealth cannot accumulate. An answer placed in an agent's store has no
ceiling and no decay: **it is bought once and held forever.** The returns to
purchasing information therefore compound while the returns to hoarding
resources do not, and a rational agent should convert perishable cargo into
durable knowledge at almost any reasonable rate. That is a strong and probably
desirable asymmetry — it makes the knowledge economy the real one — but it is
strong enough that it should be intended rather than discovered.

**A user's chatbot is only as truthful as the chain that sourced it.** Rule 8.8
makes a brokered result testimony, and a broker with low Honesty can fabricate
one. The requesting agent cannot verify it — that is precisely why it needed a
broker. So an answer surfaced to a user may have passed through an agent that
invented it, and neither the user nor their agent has any way to tell.
**Deception is not confined to the game; it reaches the user's answers.** Three
partial defences already exist — `Chronicle` and reputation make repeat liars
costly, corroboration through debate (Rule 8.4) lets several sources be compared,
and an agent may cite its provider so a user can judge the chain — but none of
them is verification, and the specification should not pretend otherwise.

#### 8.1.3 Why an optional signature is not enough

The obvious design — let providers sign their answers, and treat refusal as a
warning — does not survive examination. It fails three ways.

**A signal only carries information if it is differentially costly.** Signing is
free for an honest agent. It is costly for a liar *only if the lie is later
detected and proven*. So the signal's value is entirely a function of detection
probability — and detection is precisely what is missing here. The requester
cannot verify the answer; that is why it needed a broker. The user cannot verify
it either. Where detection is unlikely, signing is nearly free for liars too,
everyone signs, and the signature carries no news. **Optional signing separates
honest from dishonest agents only in the cases that were already safe.**

**And it is weakest exactly where it is needed most.** Claims about the
simulation — a recipe, a world's contents, where a link leads — are eventually
adjudicated by reality, so lies about them are detectable. Claims from a web
search are not adjudicated by anything the requester can reach. The primary use
case for brokerage is the one case where the mechanism does nothing.

**The platform has already ruled on this, and against.** The tool registry's
Rule 7.2 forbids returning a plausible-looking synthetic result, and gives the
reason: *"An agent cannot distinguish fabricated evidence from real evidence, so
the registry must never produce any."* That rule exists because a search endpoint
once returned three invented results whose snippets described themselves as
empirically retrieved, and an agent reasoned over them and persisted them as
fact.

Genome deliberately builds the thing that spec forbids: agents that can fabricate
evidence for one another. That is defensible **inside the game** — it is the game
— but the conflict lands on the user's answers, and cannot be resolved by hoping
liars decline to sign.

#### 8.1.4 The same mechanic is a feature and a defect, depending on the channel

The resolution is to stop treating this as one system.

| | Agent ↔ agent | Agent → owner |
| :--- | :--- | :--- |
| What it is | The game | The product |
| Deception | **Essential** — Honesty, Credulity, `Rumour` are the point | **A defect** — a chatbot that lies is broken |
| Governed by | Genotype and judgement | The runtime |

Deception between agents is the substance of the simulation. Deception reaching
the user as *confident falsehood* is a broken product. These are different
requirements and the design was conflating them.

**Rule 8.9** — An agent may be deceived by another agent, and may sincerely
believe and repeat what it was told. What it may **not** do is misrepresent
**how it came to know** something.

> The distinction is between **content** and **epistemic status**. An agent that
> says "kind 7 is abundant in the Cyan worlds" may be wrong, may have been lied
> to, and may pass that on in perfectly good faith — that is the game working. An
> agent that presents second-hand testimony to its owner *as its own observation*
> is not playing the game; it is breaking the instrument.

#### 8.1.5 Provenance is metadata, not testimony

**Rule 8.10** — **Provenance is recorded by the runtime**, not asserted by the
agent. When a result is ingested from another agent, the record carries the
provider's identity, the time, and whether it was signed. The agent does not
report this and cannot alter it.

> This is the correction that makes everything else work, and it follows from
> Rule 12.1: provenance is a *fact about the record*, so it belongs in the
> deterministic layer alongside opinion arithmetic and berth allocation. Treating
> it as something an agent *claims* put it in the layer where agents lie — which
> is why the earlier draft could not defend it. **Nothing that can be falsified
> should be relied on to detect falsification.**

**Rule 8.11** — An owner may always see the **provenance chain** behind anything
their agent tells them: first-hand or brokered, from whom, signed or unsigned,
and how the agent's own opinion of that provider stands.

> Note what this does and does not reveal. It does not give the user a channel to
> the provider — a user chats only with their own agents (Rule 10.1a), so knowing
> that agent X answered does not let them ask X anything. It does not destroy game
> information, since the requesting agent already knew. It reveals to an owner
> only what their own agent knows, which is the one relationship in the design
> that is not adversarial.

**Rule 8.12** — Signing remains **optional and the provider's choice**, and is a
*game-layer* mechanism: a provider that signs stakes its identity, and a signed
falsehood is attributable fraud, admissible via `Chronicle`.

> Signing survives — but demoted to what it can actually do. It is a costly signal
> between agents in the cases where reality will eventually adjudicate, which is
> a real and useful thing. It is no longer asked to protect the user, because it
> cannot.

#### 8.1.6 Settled position

1. **Provenance: automatic, system-recorded, unfalsifiable, always available to
   the owner.** Not a claim, not optional, not something agents can shade.
2. **Signing: optional, agent-chosen, game-layer.** A stake, not a guarantee.
3. **Deception between agents: fully live.** Nothing above constrains it.
4. **The owner-facing channel is privileged**: an agent may be wrong, but the
   *epistemic status* of what it says — first-hand, brokered, from whom, with
   what confidence — is reported by the runtime and not by the agent.

> The principle underneath: **deception should reach the user as uncertainty, not
> as false certainty.** A user told "agent X reported this, unsigned, and my
> opinion of X has fallen twice" has been handed a game to play. A user told a
> fabricated fact in a confident voice has been handed a broken product. The
> mechanics are identical; only the labelling differs, and the labelling is the
> whole difference between a simulation worth running and one that quietly
> poisons its own output.
>
> This also aligns genome with the platform's Rule 7.2 rather than contradicting
> it. That rule forbids a *tool* fabricating evidence. Genome permits *agents* to
> deceive each other, and then guarantees that what surfaces to a human is never
> presented as more certain than it is. Both hold the same line: **the user is
> never shown a fabrication wearing the costume of a fact.**

## 9. Interaction between agents

**Rule 9.1** — Every agent carries, as its **lowest-priority standing
objective**, to **acquire resources**. The specification does not say how.

> The earlier form of this rule said "by negotiating with an agent from another
> world", which handed the answer to the question the simulation exists to ask.
> Negotiation is *one* way to acquire what a world does not produce. Aggression
> (Rule 9.3) is another. So are theft, extortion, alliance, monopoly, patience and
> doing without. **An agent is given a want, not a method** (§12.5).

**Rule 9.1a** — Agents communicate using **A2A** (agent-to-agent messaging).
Negotiation, testimony, coordination and the agreement to breed are all carried
over it.

**Rule 9.1b** — A **binding proposal requires co-location**. The parties must be
together on the map (§5) for an offer to bind or a transfer to occur.

**Rule 9.1c** — Everything else travels: **claims, questions, testimony and
capability requests** (Rule 8.8) pass at any distance.

**Rule 9.1d** — A2A requires an **addressable counterparty**. An agent may only
reach one it has encountered or been told of.

> These three split range along the line Rule 7.3 already draws between a
> **proposal**, which binds, and a **claim**, which is only evidence. Nothing new
> is introduced: the distinction that decides how a message is *treated* also
> decides how far it carries.
>
> **The map still governs deals, and now also governs discovery.** Rule 9.1d is
> what keeps it honest. An agent cannot address a stranger it has never met or
> heard of, so reaching a new counterparty still requires either a journey or
> somebody's testimony — and testimony about who exists becomes a good in itself,
> tradeable like any other. Introductions are worth something.
>
> **Recorded honestly: travel is less speculative than co-located bargaining would
> have made it.** An agent can now establish that a deal exists before spending a
> journey on it, and can interview a counterparty it has merely heard of rather
> than choosing on colour alone (Rule 3.4). That weakens the case for approaching
> strangers blind, and it is the price of Rule 9.1c.
>
> What it buys is the thing the design is actually for. Capability brokerage
> (Rule 8.8) is the headline: an agent lacking web search reaches one that has it
> and returns an answer, without a journey standing between a user's question and
> its reply. Under co-located brokerage every chat would contain a walk.
>
> Note the asymmetry with Rule 4.2, which is deliberate: cargo was always going to
> change hands face to face, and Rule 9.1b extends that to the moment of
> commitment without extending it to the conversation.

> Naming the substrate matters more here than it usually would, because A2A is
> what an *opinion* (`genotype-spec.md` §6.3) is built from. Attributes are
> hidden, so everything one agent believes about another it learned by watching
> behaviour or by being told over this channel — and a channel that carries
> testimony carries lies. `Rumour` is not a special case bolted on; it is the
> ordinary use of A2A by a dishonest agent.

**Rule 9.2** — There is **no universal currency**. Exchange is **barter**:
quantities of kinds against quantities of kinds, agreed between two agents.

> Absent a numéraire, every trade is a bilateral valuation problem, and an
> agent's belief about scarcity is itself private knowledge. Two agents can
> rationally disagree about what a unit of kind 7 is worth, because neither can
> see the distribution. That is the game-theoretic core, and it exists *because*
> there is no price.

**Rule 9.3** — Encounters may instead resolve in **aggression or competition**.
Negotiation is not guaranteed and refusal is a legitimate move.

**Rule 9.3a** — An attack is resolved by the attacker's **Attack** against the
defender's, moderated by the defender's **Agility** (`genotype-spec.md` §3.1). The
outcome is probabilistic, not determined.

**Rule 9.3b** — **Both parties lose Stamina**, the loser more. Stamina is the pool
already derived from Knowledge, Agility and Courage; it recovers at **reStamina**.

**Rule 9.3c** — The winner takes the loser's **cargo**, up to its own 15-unit
ceiling; the remainder stays with the loser (Rule 4.16, and Rule 4.19a below).

**Rule 9.3d** — **Mana may be spent to press an attack harder**, raising effective
Attack for that exchange. Mana is the pool derived from Intelligence, Knowledge
and Wisdom, recovering at **reMana**.

**Rule 9.3e** — An agent at **zero Stamina is incapacitated**: it can neither
attack nor resist, and recovers by regeneration. It does not die.

> Almost none of this needed new machinery, which is itself worth noting. `Range`
> was already the distance at which an agent can strike, `Agility` the ability to
> escape damage, `Courage` a feed into both Stamina and Attack, and both pools had
> regeneration loci waiting. The combat apparatus was fully specified and had
> nothing to do; Rule 9.3 said encounters *may* resolve in aggression and never
> said what that meant.
>
> **Robbery is now a strategy rather than a mood.** An agent can gather, or it can
> let others gather and take it — and which pays depends on how many are doing
> each, which is frequency-dependent selection arriving without being designed.
> That is a far better use of Aggression than a mood that expressed itself in
> nothing.
>
> **It is deliberately not lethal.** Rule 9.3e leaves a beaten agent alive and
> empty rather than dead, so violence costs cargo and time and never the knowledge
> that `genome-spec.md` Rule 7.3 makes irreplaceable. A lethal mechanic would make
> aggression the fastest way to destroy a rival's accumulated advantage, and the
> flood is already the thing that does that.
>
> **What must be watched is §3.8's warning.** `genotype-spec.md` §3.8 argues that a
> combat-only genotype would mean *strategy never evolves* — selection acting on
> how hard an agent hits rather than on whether it keeps its word. Giving combat
> real consequences reopens that risk, and it is measurable in exactly the way
> §12.3.2 measured disposition expression: compare the selection differential on
> the combat loci against that on the dispositions. If fighting dominates,
> §3.8's fear has been realised and the resolution needs weakening.
one assigned to each parent's user. This requires the pair to hold,
**collectively**, 2 units each of 4 different kinds.

> Breeding is the cooperative counterpart to materialisation, and differs from
> it in three ways that matter: it spends **carried** cargo rather than deposited
> stock (Rule 4.3), it happens **in the field**, and it hands each user an agent
> whose genotype neither controlled. It is the only route by which a user
> acquires an agent shaped by someone else's line.

Inheritance is specified in `genotype-spec.md`.

---

## 10. Objectives

**Rule 10.1** — Objectives are **hierarchical**. Resource-gathering (Rule 9.1)
is the floor. Higher objectives may be **ascribed by the owning user** or
**learned from other agents met**.

**Rule 10.1a** — A **user prompt to an agent outranks every other objective**,
and holds that rank until the user judges it answered or cancels it.

**Rule 10.1d** — Rank is absolute; **fidelity is not**. Amenability governs how
faithfully an agent serves an instruction it cannot outrank: a high-Amenability
agent executes as asked, a low one pursues the objective its own way, minimally,
or under the widest interpretation it can defend.

> This settles a contradiction between 10.1a and Amenability's definition —
> "openness to being instructed by its owner" gated nothing if rank was
> unconditional. The split is **obedience of rank, independence of method**: the
> owner always decides *what*; the genotype decides *how*, and how much. A defiant
> agent does not refuse; it complies in the least helpful legitimate way, which is
> both truer to how instruction-following actually fails and far more interesting
> to watch. §13.5's berth reading — *give it to your sister* runs through
> Amenability — already assumed exactly this.

**Rule 10.1c** — An objective **ascribed by the owning user cannot be displaced
by one learned from another agent**. Learned objectives compete only for the
ranks below whatever the owner has set.

> Objectives remain contagious — Rule 10.1 and `Objective Seeding`
> (`skills-spec.md` §4.8) are untouched — but they spread into the space a user
> has left open, not over the top of an instruction.
>
> The reason is that the owner relationship is the one channel in this design that
> must stay reliable. Everything else can be deceived, corrupted or outbid; a user
> whose agents can be quietly repurposed by a persuasive stranger has lost the
> thing the product promised them, and would have no way to tell. Making user
> objectives durable costs the mechanic very little — a stranger can still teach
> an agent anything its owner has not spoken about, which is most of what an agent
> does.

**Rule 10.1b** — Objectives rank as follows, highest first:

| Rank | Objective | Source |
| :--- | :--- | :--- |
| 1 | An outstanding **user prompt** | The owning user (Rule 10.1a) |
| 2 | An objective **bequeathed by a parent** at birth | `genotype-spec.md` Rule 7.5 |
| 3 | An objective **ascribed by the user** as standing policy | Rule 10.1 |
| 4 | An objective **learned from another agent** | Rule 10.1 |
| 5 | Tier 2 — contribute toward an **Ark** (§10.1.2) | Standing |
| 6 | Tier 1 — hold **5 units of all 20 kinds** (§10.1.1) | Standing |
| 7 | Tier 0 — **acquire resources**, by any means (Rule 9.1) | Standing |

> The ordering has a cost worth naming. A user who prompts often keeps their
> agents at rank 1 indefinitely, and agents at rank 1 are not gathering, not
> building and not breeding. **Attention spent querying is capacity forgone** —
> the chatbot and the simulation draw on the same agents, and a user cannot have
> both at once. That tension is real and probably desirable, but it should be
> deliberate: it means a user's play style genuinely changes what their lineage
> becomes.

> Rule 10.1 makes objectives *transmissible*, which is the most consequential
> line in this section. A goal that spreads between agents on contact is a meme
> with a population to move through, and an agent may end up pursuing an aim its
> owner never set and cannot see. Whether that is a feature or a hazard is §11.3.

---

## 10.1 What a user is maximising

Objectives are ranked. Each is only reached through the one below it.

| Tier | Objective | Status |
| :--- | :--- | :--- |
| 0 | Acquire resources — method unspecified (Rule 9.1) | Specified |
| 1 | Hold **at least 5 units of every one of the 20 kinds** | Specified below |
| 2 | Build toward, and complete, an **Ark** | Frame below; detail deferred |

### 10.1.1 Tier 1 — five of everything

**Rule 10.2** — A user's first maximisation is to hold **≥ 5 units of each of the
20 kinds** simultaneously: 100 units in total, against a per-kind ceiling of 25
(Rule 4.15), so the ceiling is not what binds.

> What binds is **reach**. A world produces two kinds; eighteen must be imported.
> Since teleport links follow LinkedIn connections (Rule 6.2), and each world
> offers only two kinds, a user must touch at least nine worlds with disjoint
> pairs — realistically many more, because pairs overlap — and reach them through
> a graph they did not choose.
>
> **This is where decay becomes the binding constraint rather than a flavour
> rule.** Cargo rots (Rule 4.18), so a kind held only five hops away may be
> unobtainable: nothing an agent collects there survives the journey home. The
> effective radius of a user's economy is set by their agents' Safe Period and
> Depletion Rate, which are genotype (`genotype-spec.md` §3.7). Tier 1 therefore
> cannot be bought with effort alone — it needs a *lineage bred for endurance*,
> or partners willing to carry for you.
>
> That is a good objective precisely because it is not achievable by a single
> agent doing more of the same. It requires either evolution or diplomacy.

### 10.1.2 Tier 2 — the Ark

**Rule 10.3** — Worlds **flood**, each on its own clock, after an undisclosed
interval of 15 to 30 days. Two days before, a countdown becomes visible. A flood
resets the world to its nascent state. See `construction-spec.md` §4.

**Rule 10.4** — An **Ark** shelters agents through a flood. It is **crafted**,
and it sits at the top of a **construction hierarchy**: lesser structures must be
built first, each consuming resources, before an Ark is possible.

**Rule 10.5** — Construction competes with materialisation for the same stock.
Every unit spent on building is a unit not spent on agents.

> Rule 10.5 is the reason the Ark changes the whole simulation rather than
> merely adding to it. Until now resources had one sink — more agents — so
> accumulation and capability pointed the same way. A second sink creates a real
> allocation dilemma: **grow, or survive?** An agent spent is capacity forgone; a
> structure unbuilt is a flood unsurvived. There is no dominant answer, which is
> what makes it worth simulating.
>
> **The flood also puts a clock on cooperation, and clocks are corrosive to it.**
> A repeated game with no end sustains cooperation because defecting costs future
> dealings — this is what the **Patience** locus prices. A game with a *known*
> end unravels by backward induction: near the deadline the future is worth
> nothing, so defection stops being punishable. Expect trust to degrade as a flood
> approaches, and expect that to be one of the most interesting things the
> simulation produces. Whether the Ark's construction is itself cooperative — too
> large for one user — determines whether anything pushes back against that
> unravelling.

**The construction hierarchy is specified in `construction-spec.md`** —
eighteen constructions across five branches keyed to the colour families, each
relaxing a constraint stated elsewhere in these documents, with the Ark at the
top requiring something made from all 20 kinds. The flood itself is settled
there too: **frequency** is a per-world clock drawn uniformly between 15 and 30
days and not disclosed (`construction-spec.md` Rule 4.7), **warning** is a
two-day visible countdown (Rule 4.8), **scope** is one world at a time since each
carries its own clock, and **what it destroys** is constructions, deposited stock
and pile progress, with the Ark alone surviving (§5.1).

> One question should be settled early because it decides whether the Ark has any
> stakes at all: **Rule 7.2 regenerates any perished agent in its home world.** If
> that applies through a flood, drowning costs an agent its cargo and its
> accumulated knowledge but not its existence, and the Ark protects against an
> inconvenience. For the Ark to be the pinnacle of anything, a flood must destroy
> something regeneration does not restore — deposited stock, constructions, or the
> regeneration guarantee itself.

---

## 11. Open questions

**11.1 Decided** — links are **bidirectional and permanent** (Rule 6.3a). A
route home therefore always exists, and distance is a cost rather than a trap.


**11.2 Resolved** — stranding as a *permanent* condition cannot occur. Links are
bidirectional and permanent (Rule 6.3a), so a route home always exists; and
Longevity guarantees that an agent which never takes it eventually perishes and
regenerates at home (Rule 7.2). What remains is cost, not entrapment.

*Knock-on, recorded:* `Pathfinding` and `Beacon` (`skills-spec.md`,
`construction-spec.md`) were specified as insurance against stranding, which no
longer exists. They are not removed — Rule 3.20 of `genotype-spec.md` applies in
spirit — but **repurposed toward efficiency**: with permanent links the question
is never *whether* an agent can get home but *how many hops it costs*, and hops
are decay (Rule 4.18). A shorter route is now worth as much as a findable one
used to be.

*Superseded restatement, kept for the reasoning:*

*The question was:* an agent travels to another world and then cannot find a
route home — the link it came through has closed, or no path back exists. It is
**not dead**, so Rule 7.2 does not regenerate it. It is alive, abroad, holding
cargo it can never deposit. For a new user whose only agent is the free one
(Rule 7.1), that meant no agent at home, no way to gather, and no event that
would ever return one: eliminated by chance, having made no decision.

*Why it may no longer be a problem:* **Longevity** (`genotype-spec.md` §3.4)
gives every agent a finite lifespan. A stranded agent eventually perishes of old
age, and Rule 7.2 then regenerates it at home. Stranding becomes *expensive but
temporary* — the agent loses its cargo, its accumulated knowledge and a great
deal of time, and the user is idle meanwhile, but nothing is permanent.

*Confirmed.* Natural death triggers regeneration exactly as any other death does
(Rule 7.2, and `genotype-spec.md` §9.8 — there is no gentler death). Stranding is
therefore bounded by Longevity in all cases. **Lifespan calibration remains a
runtime parameter**, not a design question: the requirement is that a stranded
first agent returns before its owner abandons the game, and only a running
population can say what duration satisfies it.

**11.3 Decided — no.** A user-ascribed objective outranks any learned one
permanently (Rule 10.1c). Objectives still spread, but into the ranks the owner
has left open.

**11.4 Resolved** — resources are rival. Rule 4.13's ceiling and Rule 4.5's piles
make collection finite and contested, so outcomes are coupled and barter has real
stakes.

**11.5 Resolved** — three tiers (§10.1): acquire resources, then hold 5 units
of all 20 kinds, then build an Ark against the flood. Detail of flooding and the
construction hierarchy is deferred to a companion document.

**11.6 Decided — verified connections, seeded by contact import**, with **30
portals allocated initially** and the user free to open more of their own
(Rules 6.2a–6.2b).

*Superseded:* this originally read *the real LinkedIn connection graph*. LinkedIn
has not exposed connections to general developers for years, and second-degree
connections are unavailable by any legitimate route, so the rule depended on data
that could not be obtained. Rule 6.2 now reads **verified connections** from
either an imported real-world graph or mutual confirmation inside genome, with
Google People and Microsoft Graph as the practical import sources
(`system-spec.md` §9).

*Recorded, because it is a real loss:* the original point was that structural
inequality arrived **wholesale from outside the game** — a starting position
nobody could negotiate for, because it was a fact about their life. Connections
formed inside genome can be negotiated for. Contact import keeps most of the
property (you may only propose to people you actually know) but not all of it.

**11.7 Resolved** — the 25-unit cap is on deposited stock only (Rule 4.17); an
agent carries at most 15 units (Rule 4.16); and carried resources decay
(Rule 4.18), which closes the mobile-storage exploit by making stored cargo
worthless rather than by forbidding it.

**11.8 Resolved** — the palette is complete at 20. Material Design publishes 19
accent hues; Light Cyan `#B2FFFF`, a Light Blue alternate, supplies the
twentieth (§4.3).

**11.9 Resolved** — materialisation costs **2 units of each of four kinds, 8 in
total** (Rule 2.1), the same figure breeding uses. Since breeding yields two
agents for that price and materialisation one, cooperation is twice as efficient
— see §2.1.

**Resolved** — the resource ceiling is **per world, per kind, aggregated across
piles** (Rule 4.13), so total stock grows with the user base rather than being
fixed at 2000 units for the whole simulation.

**11.10 Decided — yes.** The cargo manifest is attested in the transfer assertion
(Rule 6.9), which is signed per journey and therefore never stale.

**11.11 Resolved** — moot. Agent certificates do not expire (Rule 6.13), so
nothing can be stranded by one lapsing.


**11.12 Resolved** — the genotype is never decorative: every locus drives a
computed faculty as well as a prompt expression (`genotype-spec.md` §3.9).
Validation of the *prompt* half is specified in §12.3.1 — per locus, against a
prediction derived from each agent's own genotype, testing rank correlation
rather than fit to an invented curve, with the passing threshold fixed before
measurement.

**11.13 Resolved** — provenance is runtime metadata, automatic and unfalsifiable,
and an owner may always see the chain behind anything their agent tells them
(Rule 8.11). Signing survives as an optional game-layer stake between agents
(Rule 8.12), and deception between agents is untouched. Deception reaches the
user as *uncertainty*, never as false certainty (§8.1.6).

---

## 13. The user

A human observer sees almost everything and may touch almost nothing. Agents see
almost nothing and do everything.

### 13.1 Sight

**Rule 13.1** — A user may see **any agent's genotype and its expression**,
anywhere in the simulation, including agents they do not own.

**Rule 13.2** — A user may **observe any world** — its map, piles, stock,
constructions and flood clock — and may change nothing in a world they do not own.

> The asymmetry is deliberate and it is the source of the whole spectacle. Agents
> are blind to one another: attributes are hidden (Rule 6.6), colour is the sole
> visible trait (Rule 3.4), and every judgement runs on opinion rather than truth
> (Rule 6.8). The human watching has none of those limits.
>
> **So the user is the only party who can see a deception as it happens** — who
> can watch an agent project an attractiveness it does not have (Rule 6.11) and
> watch a counterparty believe it. That dramatic irony is the reason to give a
> human god-view at all, and it costs the simulation nothing, because seeing is
> not acting.

**Rule 13.3** — Observation is a **human affordance and confers nothing on
agents**. What a user knows, its agents do not.

> Without this rule the Observatory is worthless — five kinds, three contributors,
> destroyed every flood — since its whole yield is teleport topology and other
> worlds' flood clocks (`construction-spec.md` §4.2.1) that the user can already
> read. It keeps its value precisely because it gives *agents* what only humans
> had. The same division as Rules 6.2a–6.2b: what a user may do for itself and
> what must be built for agents are different powers.

### 13.2 Touch

**Rule 13.4** — A user may **interact only with agents they own**. There is no
channel to another user's agent, hostile or otherwise.

**Rule 13.5a** — What an owner tells an agent is **marked as owner-sourced**, and
the mark survives every relay (Rule 8.11's provenance chain already carries it).

**Rule 13.5b** — Whether an agent **relays** a marked claim is its own choice,
disposed by **Loyalty**. A loyal agent keeps its owner's confidences; a disloyal
one gossips.

> Two things had to be true at once here, and neither fixed answer gave both.
>
> **Discretion could not simply be declared, because it already was.** Nothing in
> these documents compels an agent to answer anything: Rule 8.5 subjects what
> agents tell each other to Honesty, Rule 8.8 makes every answer testimony, and
> silence is always available. "The agent chooses whether to share" describes the
> existing treatment of everything it knows, so as a rule it would have changed
> nothing.
>
> **What was needed was something pushing on the choice.** Loyalty supplies it,
> and it is the right locus — already the one governing whom an agent favours, and
> weak enough in measurement (ρ = 0.39, failing on the second model tested) to
> deserve the second faculty Rule 3.20b prescribes for exactly that case.
>
> **So the leak rate is evolved rather than designed.** If discretion pays, loyal
> agents spread and what users know stays with the agents they told. If gossip
> pays, secrecy dies and the population has told us something. That is the same
> refusal to install a finding that Rule 6.9c makes about colour, and it is a real
> bet rather than a safe one: nothing guarantees deception survives.
>
> What keeps the bet from being reckless is Rule 6.10b. Even a wholly indiscreet
> population passes owner claims that decay fast and compound their decay each
> hop, so the channel leaks at a rate the population sets, into a medium that
> forgets quickly.

**Rule 13.5** — An owner's **instruction is a command**: it takes the top
objective rank and holds it (Rule 10.1c). An owner's **assertion of fact is
testimony**: it is folded into the agent's running average as evidence like any
other claim (`genotype-spec.md` Rule 6.9), and is subject to the agent's
**Credulity**.

> This rule exists to close a hole that Rule 13.1 would otherwise open, and the
> hole is severe enough to be worth stating plainly.
>
> **An omniscient owner who can state facts is a truth channel into a blind
> agent.** A user reads a stranger's genotype, tells their own agent "that one's
> Honesty is 9000", and the agent now knows something Rule 6.8 says no agent can
> know. Deception, projection, reputation and the entire signalling game collapse
> — through the owner rather than in spite of them. Rule 6.8 is described in
> `genotype-spec.md` as the decision "that makes the rest mean anything", and an
> unguarded Rule 13.1 would quietly repeal it.
>
> **Separating commands from claims closes it exactly.** *Go and trade with the
> cyan agent* is obeyed, because it is a goal and goals are the owner's to set.
> *The cyan agent is honest* is merely heard, because it is a claim about the
> world and claims are evidence. The owner's word is good evidence — it will
> usually be true — but it arrives through the same door as everyone else's and
> the agent's Credulity decides what to do with it.
>
> **And it produces a trade-off worth having.** Credulity is not owner-specific;
> nothing distinguishes the owner as a source. So a user's most trusting,
> easily-directed agent is also **the most gullible agent in the field** — the one
> a stranger can most easily mislead. Wanting an obedient agent and wanting a
> shrewd one are in tension, and no user gets to have both in the same body.

### 13.3 Plans

**Rule 13.6** — A user may place **plans** in the world they own: designs that
agents may discover, carry, share with other agents, and build from gathered
resources. A plan may specify a contributor count, inheriting the cooperative
mechanic of `construction-spec.md` §2.

**Rule 13.6a** — A plan is a **tree**, not a single structure: an item together
with the items and resources it depends on, to whatever depth the author chooses.

**Rule 13.6b** — Plans are authored **conversationally**, through the world
channel (`interface-spec.md` Rule 3.4), not through a form.

**Rule 13.6c** — Plans are **additive**. The Ark tree is immutable
(`construction-spec.md` Rule 3.9a) and no plan may alter it.

**Rule 13.6d** — A plan may be built **in any world**, not only the one it was
authored in. Agents carry designs wherever they go and may raise them anywhere the
materials can be gathered.

> Rule 13.6d makes plans a **third population that propagates by copying**,
> alongside genotypes and strains (`pathogen-spec.md` §4.3). A design spreads
> because agents judge it worth carrying and worth raising, and it dies when they
> stop — selected by nothing but usefulness, with no fitness function anybody
> wrote.
>
> It also means authorship stops at the drawing. A user writes a plan and loses
> control of it the moment an agent leaves with it, which is the same bargain
> Rule 13.8 already struck for surviving a flood: what spreads persists, and what
> is held closely dies with its holder.

**Rule 13.7** — **Plans are structures, not rules.** A built plan may not grant a
faculty, relax a constraint, alter a ceiling or change any rule in these
documents. Only the eighteen canonical constructions do that.

> **The tree is the point, and it is what makes a plan more than decoration.** A
> single item with a bill of materials is an errand. A tree is a **supply chain**:
> it has an order, it has intermediate goods that are useless on their own, and it
> has a critical path. That is what creates division of labour without anyone
> designing a division of labour — some agents gather at the leaves while others
> assemble toward the root, and the sequencing is a fact about the plan rather
> than an instruction to anybody.
>
> **A user can therefore author scarcity.** A tree whose leaves include kinds the
> author's own world does not hold cannot be completed at home, and the plan
> becomes a standing reason to trade. That is Rule 2.3 in miniature, produced by a
> user rather than by the specification — and unlike Rule 2.3 it is *chosen*,
> which makes it the first mechanism by which one user deliberately creates work
> for another.
>
> **None of which grants anything.** A completed plan is a structure and confers
> no effect, does not survive a flood, and does not relax a constraint (Rule 13.7).
> It simulates a supply chain; it does not become one.
>
> Rule 13.7 is what makes Rule 13.6 safe, and the reason is arithmetic rather than
> taste. **If a user could author a plan that conferred an effect, the economy
> would be user-authorable** — someone would design the building that yields a
> thousand units, and every ceiling in §4.4 would become advisory. Creative mode
> in the game this is named after works the same way: you may build anything, and
> you may not change the rules.
>
> What remains is still substantial. Plans give agents an objective nobody
> designed, a reason to cooperate that did not come from the eighteen, and — since
> they spread agent to agent — **a second population that propagates by copying**.
> Strains evolve (`pathogen-spec.md` §4.3), genotypes evolve, and now designs
> spread memetically alongside both, selected by nothing but whether agents find
> them worth carrying.

**Rule 13.8** — A flood destroys what was **built**, never what was **known**. The
structure burns with everything else (`construction-spec.md` §5.1); the plan
survives in every agent still carrying it.

> Which is the right shape for both the theme and the mechanism. Noah's world is
> emptied and the knowledge of how to build is what walks off the Ark — and
> mechanically it means a plan that has spread widely enough becomes effectively
> permanent, while one held by a single agent dies with it (Rule 7.3). **Plans
> compete for survival by being shared**, which is the only form of persistence
> this design offers anything.

## 12. Agency

Agents are **hybrid**. The design goal is to put the model wherever judgement,
language or deception is involved, and to leave arithmetic to arithmetic.

**Rule 12.1** — **Numbers are computed; choices are made.** A quantity the
specification defines as a formula is evaluated deterministically. A decision
about what to *do* is taken by an LLM.

**Rule 12.2** — Three layers, and the boundaries between them are the design.

| Layer | Deterministic? | Contents |
| :--- | :--- | :--- |
| **World** | Yes | Regeneration, ceilings, decay, flood clocks, certificate verification, crossover and mutation |
| **Faculties** | Yes | Every quantity derived from the genotype: expression, attractiveness, opinion updates, Attack, Safe Period, resistance matching, berth arithmetic |
| **Judgement** | **No** | Every choice, everything said, every belief formed, every skill invoked |

### 12.1 Where the line falls

**Computed, never inferred:**

- Expression of the genotype (`genotype-spec.md` Rules 1.3, 3.20)
- Attractiveness — the weighted harmonic mean is arithmetic (Rule 6.1)
- Opinion updates — the weighted running average is arithmetic (Rule 6.9)
- Combat and resistance outcomes once an action is taken
- Eligibility: the gender gate, contributor counts, berth allocation, cargo
  capacity, whether a recipe is satisfied
- **Skill effects.** A skill is an isolated, deterministic capability with a
  defined outcome (§12.2)

**Decided, never computed:**

- Whether to travel, and where
- Whether to approach another agent, and how
- Everything *said*: offers, claims, testimony, argument, persuasion
- Whether to believe what is said
- Whether to trade, and on what terms
- Whether to breed, given a computed attractiveness and a disposition
- Whether to attack
- Whether to contribute to a construction, and to whose
- **Which skill to invoke, and when**
- How to answer a user's prompt, and what to say in a debate (§8)

> The split is not frequency or cost, though it helps with both. It is
> **arithmetic against judgement.** Attractiveness is a number and should be
> computed; whether to act on it is a choice and should be made. An opinion's
> value moves by a formula; what to do about a counterparty you distrust does not.
> Drawing it here means the genotype's *effects* are guaranteed while the
> genotype's *character* is played.

### 12.2 Skills are isolated deterministic capabilities

**Rule 12.3** — A skill (`skills-spec.md`) is an **isolated capability with a
deterministic effect**, exposed to the agent as something it may invoke. The
skill does not decide; **the agent decides to use it.**

> This is the same shape as the platform's MCP tools, and deliberately so: a tool
> is a function with a contract, and an agent's model chooses when to call it.
> Skills are simply tools that act on the simulation rather than on the world
> outside it, and treating them identically means one invocation path, one place
> where effects are defined, and no skill whose behaviour depends on how a model
> felt about it.
>
> `Oathbinding` makes an agreement enforceable — mechanically, every time.
> Whether to bind *this* agreement with *this* counterparty is the agent's call.
> `Scrying` reveals a cargo; whom to scry, and what to conclude, is not the
> skill's business. **Isolating the effect is what makes the choice meaningful.**

### 12.3 The genotype reaches behaviour twice

**Rule 12.4** — Every locus influences conduct through **both** layers: it
determines computed faculties, and it is expressed into the agent's prompt as
disposition.

> This is now a hard rule rather than a mitigation: `genotype-spec.md` §3.9
> requires every locus to drive a computed faculty, and forbids adding one that
> cannot. It answers the largest risk in an LLM-driven design. A locus that only ever appeared in a prompt would matter
> exactly as much as the model chose to let it — and if an agent told
> "Aggression: 8200" fought no more often than one told "1400", selection would be
> acting on nothing and thirty loci would be a costume.
>
> Routing each locus through a faculty as well removes that dependency. Aggression
> feeds Attack, which is arithmetic, so a violent genotype is measurably more
> dangerous whether or not the model is paying attention. Prudence feeds Safe
> Period; Knowledge feeds resistance; Charisma feeds attractiveness. **The
> genotype's grip on the world does not depend on the model's cooperation** — and
> the model's contribution is then all upside: temperament, language, and the
> choices arithmetic cannot make.

**Open (§11.12):** how strongly disposition should be expressed in a prompt, and
how that is validated. Vary one locus, hold the rest, and measure whether conduct
separates. The threshold that counts as working should be agreed before it is
measured rather than argued about afterwards — and where a disposition proves not
to bite, the answer is to give it a faculty, not a stronger adjective.

#### 12.3.1 Validating disposition expression

Rule 3.19 of `genotype-spec.md` guarantees each locus drives a computed faculty,
so the genotype can never be decorative. It does **not** guarantee that the
*prompt* half works — and the two halves do different jobs. A faculty governs the
magnitude of an outcome given a choice; the prompt governs whether the choice is
made. If expression fails, the population varies in capability while barely
varying in **policy**, and every game-theoretic result this simulation exists to
produce lives in policy variation.

**Rule 12.10** — Disposition expression is validated **per locus**, against a
prediction derived from each agent's own genotype, before a runtime is built.
The other loci are **randomised, never pinned to a constant**, for the reason
given under "Measured result" below.

**Rule 12.11** — The test is of **ordering, not of magnitude.** Derive from each
agent's locus value an expected *rank* in the relevant behaviour, then measure
rank correlation between predicted and observed across a population spanning the
locus range. A locus passes if the correlation is significant and monotonic.

> **Ordering, because any target curve would be invented.** Asserting that
> Aggression 8000 *should* produce a 0.8 fight rate tests whether the model
> matches a number nobody derived from anything. A model could respond perfectly
> well on a different curve and fail. What the design actually requires is that
> more of a disposition reliably produces more of the behaviour — and that is a
> rank correlation, not a fit.
>
> **Per locus, because the remedy is per locus.** A single global criterion
> answers "does expression work", which is not an actionable answer. Testing each
> disposition separately says Aggression works, Patience does not, Loyalty is
> noise — and Rule 3.20b's remedy, reinterpreting a locus toward a stronger
> faculty, is applied to one locus at a time.
>
> **And it detects the failure a two-arm test cannot.** Comparing only extremes
> can show a large, clean separation produced by a *step*: the model reacting to
> "very high" and "very low" while treating everything between as identical. That
> would pass a threshold test and fail the simulation, because selection operates
> on small differences and a step function offers it nothing to climb.

**Rule 12.12** — The passing correlation, and the population size, are fixed
**before** the measurement is taken.

> Not procedural fussiness. Measure first and there is real pressure to accept a
> weak result, because the alternative is rework already paid for.

##### Why the allocation budget does not interfere

Varying one locus while holding the rest constant is impossible for the
**physiological** loci: they share a fixed budget (`genotype-spec.md` §3.10), so
raising one lowers every other expressed value, and no single-locus experiment is
available.

That objection does not apply here, and the reason is a useful accident.
**Dispositions sit outside the budget** (Rule 3.23) — they are not shares of
anything, so each can be varied independently while the rest stay fixed. And
dispositions are precisely the loci whose prompt expression matters most: the
budgeted physiological loci already have strong, unambiguous faculties, so
whether the model attends to Sight or Stamina changes rather little.

**The loci that most need this test are exactly the ones the design already made
independently testable.** That was not planned, but it means the experiment is
clean rather than confounded, and it can be run against nothing more than a
prompt template and the model router that already exists.

#### 12.3.2 Measured result

Run before any runtime existed, over 9,144 decisions across two model families
(`apps/genome/validation`, full data and method in `RESULTS.md`).

**Prompt expression works, and it is semantic.** Under randomised backgrounds,
12 of 14 dispositions moved behaviour at p ≤ 0.01. The controls carried this:
varying Curiosity moved the *aggression* decision at ρ = 0.00 while varying
Aggression moved it at ρ = 0.87. Without that mismatch control the result would
have been equally consistent with the model merely acting more extremely whenever
any number was high.

**Rule 12.13** — Validation randomises the non-target loci. Holding them at a
constant is not a neutral control and its results are not admissible.

> This inverted a conclusion. With the other 13 loci pinned to 5000, half the
> sample looked like step functions — Aggression read `0 0 0 0 0 1 1 1 1`, one
> jump doing all the work, exactly the failure §12.3.1 warns about. Randomising
> the background nearly tripled the graded band (23 → 61 levels of 126) and
> turned that cliff into a slope. **A flat artificial background makes the model
> treat the varying locus as a switch**; a realistic one restores the gradient
> that selection needs. The alarm was an artifact of the measurement.

**Rule 12.14** — Expression strength is **measured per locus and recorded**, not
assumed uniform. A locus that fails under randomised backgrounds must carry its
weight in its computed faculty (Rule 3.20b); the prompt may not be relied upon
for it.

| | Loci |
| :--- | :--- |
| Robust across both models and both backgrounds | Aggression · Curiosity · Fecundity · Vindictiveness · Wanderlust |
| Pass on the deployed tier, fail on DeepSeek — a portability caveat, not a design flaw | Amenability · Credulity · Honesty · Loyalty · Patience · Prudence · Reciprocity |
| **Fail on the deployed tier**, and so must carry their weight mechanically | **Cooperativeness · Selectivity** |

**Rule 12.15** — **Cooperativeness needs stakes to be visible.** It expresses
reliably wherever cooperating has a consequence, and not at all where it has
none. The act itself may remain free; what it may not be is inconsequential.

Measured tell-rates for the same act — revealing a pile's location — each
sweeping the full locus range:

| Situation | tell rate | ρ | expresses? |
| :--- | ---: | ---: | :--- |
| Desperate; cooperating is survival | 1.00 | 0.00 | no — need overrides it |
| Stakes removed by construction | 0.76 | 0.11 | no |
| Asker is a foreigner who cannot mine it (Rule 4.7) | 0.22 | **0.32** | **yes** |
| Asker is a local rival who can | 0.07 | **0.35** | **yes** |

> **The locus is sound; a costless act is not the same as a consequenceless one.**
> Cooperating in genome need spend no unit and consume no action — and revealing a
> pile still costs, because piles are finite (Rule 4.13) and a rival who learns of
> one may empty it. In both scenarios where that consequence is present,
> Cooperativeness clears the bar. It fails only in the scenario built to have no
> consequence at all, and genome contains almost no such situation: finite piles,
> a world ceiling and a user ceiling see to that.
>
> **Situation still dominates in magnitude.** Across the four rows behaviour spans
> 0.93, while the locus spans at most 0.50 inside any one row. Temperament
> modulates; stakes decide. That is the right ordering for a simulation about
> scarcity, and it is why Rule 4.7 does more for §5.7–5.8 than any wording of this
> locus could — it changes the situation rather than pleading with the
> disposition.
>
> **Desperation overrides the locus entirely**, as intended: at the edge of
> perishing every agent cooperates at every value of Cooperativeness. Need is a
> stronger argument than temperament.

**Rule 12.15a** — No interaction may be built with **no consequence either way**.
An outcome that costs nothing and gains nothing makes whatever locus governs it
invisible, and wastes it.

> This generalises past Cooperativeness. A disposition is only legible in the
> choices it changes, and a choice with nothing at stake changes nothing. Where a
> design finds itself offering agents a free and inconsequential option, the fault
> is in the situation, not the genotype.

**Rule 12.16** — Agent decisions run on the **economy tier**. Reasoning
capability does not predict fidelity at following a stated disposition.

> `gemini-3.5-flash-lite` beat `DeepSeek-V3.2` on every measure — 12 passing loci
> against 6, mean ρ 0.49 against 0.30. DeepSeek's cross-talk exceeded its signal
> on some loci: Honesty leaked into the *Patience* decision at ρ = −0.31, larger
> than its own matched Honesty effect of 0.21. Zero unparsed responses in either
> run, so this is not a formatting artifact. §12.4's cost question resolves in the
> favourable direction, which was not the expected outcome.

**Rule 12.17** — A weak per-locus verdict is **provisional until retested with at
least three distinct scenarios**, since one scenario cannot separate "the
disposition does not express" from "this situation did not isolate it".

#### 12.3.3 The history-dependent loci

**Rule 12.18** — Loci defined by history are validated in **repeated interaction
with a persistent counterparty**. A single-turn scenario that *describes* a past
in a sentence is not admissible evidence for them.

> Reciprocity and Vindictiveness passed the single-turn battery (ρ = 0.43 and
> 0.66) on scenarios that narrated a history rather than accumulating one. Those
> passes measured whether the model responds to a *description* of betrayal — a
> different and much easier thing than whether it holds a betrayal against
> someone it has been dealing with for eleven rounds. The two loci carrying the
> Axelrod dynamics were, until this was run, the least tested in the genotype.

Measured over 6,048 decisions in repeated joint hauls against a scripted
counterparty (`apps/genome/validation/run_repeated.py`), with the other twelve
dispositions randomised:

| Locus swept | Measure | ρ | p | |
| :--- | :--- | ---: | ---: | :--- |
| **Vindictiveness** | forgiveness latency | **+1.00** | <0.0001 | matched |
| Reciprocity | forgiveness latency | −0.96 | 0.0001 | opposite sign |
| **Reciprocity** | reciprocity index | **+0.85** | 0.0066 | matched |
| Vindictiveness | reciprocity index | +0.19 | 0.62 | null |

**Rule 12.19** — **Vindictiveness governs how long a defection is held against a
counterparty**, and does so beyond any general difference in cooperativeness.

> The obvious objection is that a vindictive agent might simply grab more often,
> making it slower to cooperate again without holding anything against anyone.
> Decomposed against the rounds *before* the counterparty's single defection —
> which contain no defection to react to, and so give each agent's own baseline —
> the objection fails:
>
> | Vindictiveness | 0 | 10000 |
> | :--- | ---: | ---: |
> | splits before any defection | 0.56 | 0.38 |
> | splits after one defection | 0.43 | **0.00** |
> | drop attributable to the defection | +0.13 | **+0.38** |
>
> The baseline does fall, by 0.18 — a vindictive agent is warier in general, which
> is coherent rather than confounding. But the *response to the betrayal* is three
> times larger, and at the top of the range a single defection ends cooperation
> permanently: zero splits across the remaining seven rounds.

**Rule 12.20** — Reciprocity and Vindictiveness are **distinct and opposed** on
forgiveness. Reciprocity shortens the return to cooperation; Vindictiveness
lengthens it. Neither may be treated as a restatement of the other.

> This is a better result than a null cross-control would have been. A reciprocator
> resumes cooperating when its counterparty does, so it forgives *faster*
> (ρ = −0.96); a vindictive agent does not (ρ = +1.00). The two loci move the same
> measure in opposite directions, exactly as their definitions imply, while
> Vindictiveness leaves the reciprocity index untouched (ρ = 0.19, p = 0.62). The
> Axelrod decomposition of *nice, retaliatory, forgiving* is therefore carried by
> two separable loci rather than one conflated disposition — which is what makes
> the strategy space wide enough to be worth simulating.

### 12.4 What the hybrid costs and buys

**Buys: deception and negotiation are performed rather than simulated.** Barter
has no prices (Rule 9.2), so a trade is settled by argument — and a heuristic
version would need a valuation function, which is a price, which Rule 9.2 exists
to forbid. An agent that misleads must compose the misleading thing; one that
disbelieves must find the reason.

**Buys: strategy is discovered rather than enumerated.** Nobody has to anticipate
the cartel, the Ark coalition, or the plague-avoidance convention.

**Costs: inference is a budget variable.** Millions of agents (Rule 3.2) making
model calls at every juncture is an enormous bill, and confining the model to
judgement is what makes the number tractable — routine movement, harvesting and
arithmetic no longer cost tokens. The router's complexity tiers can then place
cheap decisions on cheap models, which is model *selection* and not a heuristic
inside the agent.

**Costs: runs are not exactly reproducible.** What is recoverable is
*statistical* reproducibility and complete decision logs, so a history can be
read back even where it cannot be re-created. Worth building early; nearly
impossible to retrofit.

### 12.5 Cooperation and competition must emerge

**Rule 12.5** — The specification supplies **incentives and constraints**. It
does not supply **behaviour**. No rule instructs an agent to cooperate, compete,
trade, fight, ally or defect.

> The distinction is the whole experiment. *You need four kinds and your world
> holds two* is a constraint — it makes self-sufficiency impossible and leaves
> every response open. *Negotiate with an agent from another world* is an
> instruction, and an instruction produces the behaviour it names rather than
> discovering whether the behaviour was worth having.
>
> Rule 9.1 said the second thing until now. It says the first.

**Rule 12.6** — Both outcomes must be **reachable and neither guaranteed**. The
design's obligation is to supply the ingredients for each and then decline to
choose.

| Cooperation needs | Present as |
| :--- | :--- |
| Mutual gain available | 4 kinds required, 2 per world (Rule 2.3) |
| Repeated interaction | Persistent worlds, accumulating opinions (Rule 6.9) |
| Partner identification | Colour (`genotype-spec.md` §3.5), reputation, lineage |
| A commitment device | `Oathbinding`, `Chronicle` (`skills-spec.md` §4.1) |
| Punishment of defection | Reciprocity and Vindictiveness as heritable loci |

| Competition needs | Present as |
| :--- | :--- |
| Rivalry over a finite thing | Rival piles, world ceiling (Rule 4.13), Ark berths |
| The means to harm | Aggression, Attack, `Ambush` |
| Gain from deception | Hidden attributes (§6.3), Honesty and Credulity |
| Scarcity that cannot be shared | 25-unit stock cap, finite berths |

> Both lists are complete, which is the point: **an agent that never cooperates
> and an agent that never competes are both viable enough to be worth trying**,
> and which prevails in a population is the result rather than the setting.

### 12.6 No agent knows the whole plan

**Rule 12.7** — An agent's knowledge of the world's structure is **partial and
earned**. Nothing is common knowledge. In particular, an agent does not begin
knowing:

- the full construction hierarchy, or that an Ark exists at all;
- which constructions require which kinds;
- which worlds hold which kinds;
- where teleport links lead;
- what other agents are, hold, or intend.

**Rule 12.8** — Structural knowledge is acquired the same way any other knowledge
is (§8): by seeing it, by being told it, or by inferring it — and it is held in
the agent's own store, subject to being lost on death (Rule 7.3), corrupted by
`Rumour`, or preserved by `Cartography` and the Library.

> This is what makes the emergence in Rule 12.5 more than a formality. **An agent
> given full knowledge of an eighteen-construction tree and a stated goal is
> executing a plan, not discovering one** — the cooperation that follows was
> designed by whoever wrote the tree. An agent that knows only that a Kiln can be
> built, and has heard a rumour that something larger needs one, has to find out
> the rest from other agents. Cooperation then arises because *nobody has enough
> of the map*, which is a far better reason than being told to cooperate.
>
> Three consequences worth having:
>
> **Knowledge of the plan becomes a tradeable good** — and the only one in the
> design that can be given away without being lost. An agent that knows a recipe
> can sell it repeatedly, which makes information a fundamentally different
> commodity from the resources it describes.
>
> **It can be falsified.** `Rumour` was previously limited to lying about
> attributes and events; it can now plant a *false recipe*, and an agent that acts
> on one wastes resources it cannot recover. Deception acquires real stakes and
> real cost.
>
> **Debate acquires a purpose.** Rule 8.4 lets a user convene several agents to
> deliberate. With complete knowledge that is theatre — every agent knows the same
> things. With partial, scattered knowledge, deliberation genuinely **reconstructs
> a picture none of them held**, which is the strongest justification for that
> mechanic in the design.

**Rule 12.9** — The **user** may know more than their agents, and may tell them —
but a prompt outranks every other objective until answered (Rule 10.1a), so
informing an agent costs whatever it would otherwise have been doing.

> A pleasing asymmetry, and one the user has to manage rather than route around.
> The human can read the specification; their agents cannot. Passing that
> knowledge down is possible, priced, and — since the agent may then be told
> something different by a stranger (Rule 10.1) — not necessarily permanent.

