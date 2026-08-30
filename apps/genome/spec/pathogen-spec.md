# Genome — pathogens and immunity

A proposal, not a settled design. Companion to `genome-spec.md`,
`genotype-spec.md` and `skills-spec.md`.

**Status: draft proposal for discussion.**

---

## 1. Why pathogens earn their place

Three problems already exist in the design, and one mechanism answers all three.

### 1.1 Sexual reproduction currently has no advantage

An agent can be made two ways: **materialised** alone, or **bred** with a
partner. Breeding is cheaper per agent (`genome-spec.md` §2.1) but that is a
price the designer set, not a reason the mechanism should exist. Nothing in the
simulation makes *recombination itself* worth anything — a lineage that only
ever materialised would lose no fitness, merely spend more.

This is the oldest open question in evolutionary biology, and its leading answer
is the **Red Queen hypothesis**: sex exists because parasites adapt to
genotypes, and recombination shuffles defences faster than a pathogen can track
them. Asexual lineages are efficient until something learns their lock.

Pathogens give crossover a *reason*. A user who only materialises breeds a
monoculture and gets one immune profile; a user who breeds gets offspring
covering signature space neither parent covered. The advantage is not granted, it
is earned against an adversary — which is the only kind that survives contact
with optimising agents.

### 1.2 Monoculture has no natural check

`genome-spec.md` §9.4 permits sponsorship: a wealthy lineage can fund breeding
with every partner it finds and flood the population with its genotype. The
current guard is that per-agent preference weights mean there is no single
most-attractive genotype — a real defence, but a passive one.

Pathogens are an **active** check. A population converged on one genotype shares
one immune profile, and a single well-matched strain sweeps it. Diversity stops
being an aesthetic preference and becomes a survival requirement, enforced by
something that cannot be negotiated with.

### 1.3 Connectivity is currently pure advantage

Teleport links follow LinkedIn connections (`genome-spec.md` Rule 6.2), so a
well-connected user has more partners, more reachable kinds, and no offsetting
cost. That imported inequality is the most questionable thing in the design.

**A connection graph is also an epidemiological network.** If pathogens travel
with agents, the well-connected are more exposed as well as better supplied, and
the advantage becomes a trade-off rather than a gift. This is the cheapest
available fix for the fairness problem, and it is thematically exact.

---

## 2. The model

### 2.1 What a strain is

**Rule 2.0** — Signatures and immune profiles are vectors of **8 to 16
dimensions**.

> The band matters more than the exact figure. Too few and immunity is solvable:
> within a few generations most lineages cover most of the space, pathogens stop
> being a pressure, and both the Red Queen argument for sex (§1.1) and the check
> on monoculture (§1.2) collapse with them. Too many and no profile can cover
> enough to matter, infection becomes near-random, and selection on the immune
> loci is noise — which would also break the immunity-against-Fecundity trade-off
> in `genotype-spec.md` §3.6.1.
>
> Between those failures is a band where **defences are meaningful but never
> complete**: surviving a plague genuinely protects against its relatives, and
> there is always somewhere in the space a new strain can appear. That is the
> condition an arms race needs, and it is the only thing this number has to
> deliver.

**Rule 2.1** — A strain is described by six things.

| Property | Meaning |
| :--- | :--- |
| **UUID** | Identifies this strain, distinct from the strain it mutated from |
| **Signature** | A numeric vector, in the same form as a genotype's loci |
| **Target set** | Which attributes it modulates, and in which direction (§2.4) |
| **Replication factor** | How fast it multiplies within a host — severity and onset |
| **Contagion factor** | How readily it passes at contact — intensity |
| **Infection distance** | How far it reaches across a world's map — radius |

**Rule 2.2** — An agent's defences are three heritable things, specified in
`genotype-spec.md` §3.6: an **immune profile** matched against a strain's
signature, an **Infection Propensity** weighed against contagion and distance,
and an **Infection Resistance** weighed against replication.

> Specific and general defences answer different questions, and a novel strain
> (Rule 2.13) is precisely the case where the specific one is useless to everybody
> at once — which is when constitution is all anyone has.

> Making both sides vectors, rather than giving pathogens a type and agents a
> resistance number, is what allows an arms race. A scalar resistance can only go
> up or down; a signature can be *evaded*, which means a mutation can render an
> established defence worthless without weakening it.

**Rule 2.3** — A strain records the **UUID of the strain it mutated from**.
Strains therefore have lineage, exactly as agents do
(`genotype-spec.md` §7.2).

> Which makes an outbreak traceable. Given strain lineage, an epidemic can be
> walked back to the teleport that produced it — the epidemiological counterpart
> of agent genealogy, and the same argument for it: **you cannot study something
> evolving without recording its descent.** Genome now has two evolving
> populations, and both are instrumented the same way.

#### 2.1.1 Infection distance

**Rule 2.4** — A strain has an **infection distance**: a radius, measured on the
world's isometric map (`genome-spec.md` §5), within which it may pass to another
agent without contact.

**Rule 2.5** — Infection probability is the **contagion factor at contact,
decaying to zero at the infection distance**. Contagion is intensity; distance is
reach.

> Coupling them this way avoids a degenerate strain without needing a cap.
> Untreated, a strain that evolved a large radius would infect every agent in a
> world simultaneously and the simulation would have one disease and no
> epidemiology. Decay makes reach *expensive in reliability*: a far-reaching strain
> is weak at its edge, so distance and certainty trade against each other exactly
> as replication and transmission do.

**Rule 2.6** — Infection distance is **local to a world**. It does not cross
teleport links; only an infected agent does.

##### Why distance changes the disease system

**It removes the only complete defence.** Until now transmission required contact
(§2.3), so refusing to engage with the visibly sick was sufficient. Distance makes
proximity enough. Since Rule 2.3 of `genome-spec.md` obliges agents to seek each
other out, **there is no longer a way to play safely** — only ways to play less
dangerously.

**It puts disease into a race with Sight.** An agent can only avoid what it
perceives, so avoidance depends on **Sight exceeding the strain's infection
distance**. Where it does, an agent sees the infected in time to move away; where
it does not, it is infected by something it never perceived. Note the asymmetry
this creates with combat: Rule 4.5 of `genotype-spec.md` binds an agent's strike
to `Range ≤ Sight`, because you cannot hit what you cannot see. **A pathogen is
under no such constraint.** It is the one hazard in the simulation that can reach
further than its victim can look — which puts selective pressure on Sight for
reasons that have nothing to do with fighting.

**It makes resource piles into infection hotspots.** Agents cluster where the
resources are, because piles are the only reason to be anywhere in particular
(`genome-spec.md` Rule 4.5). A strain with any radius at all therefore finds its
densest population exactly where the game compels everyone to go. Nobody designs
that; it falls out of putting a radius on a map that already has a reason to
crowd.

**And it makes a world dangerous, not just its inhabitants.** Endemic strains
(Rule 2.11) with a radius mean arriving somewhere is itself an exposure, whether
or not the visitor meets anyone. Travel is now risky before any encounter takes
place.

#### 2.1.2 Replication against contagion

**Rule 2.7** — Replication, contagion and infection distance are
**independent properties that mutate independently**.

> They are also in tension, and the tension is the most valuable thing pathogens
> bring to this simulation.
>
> A strain that replicates hard produces a severe infection: expression is
> suppressed further and sooner, so the host negotiates worse, travels less, and —
> since infection is visible (Rule 2.21) — is refused contact by agents that would
> rather not catch it. **High replication shortens the window in which the strain
> can spread.** A strain that replicates gently keeps its host mobile, sociable and
> acceptable as a counterparty, and spreads for longer.
>
> This is the **virulence–transmission trade-off**, and it is one of the few
> results in epidemiology sharp enough to be worth reproducing. Neither extreme
> wins: a strain too aggressive burns out, a strain too mild is outcompeted for
> hosts. Selection settles at an intermediate virulence that nobody set, and where
> it settles depends on how much travel there is and how carefully agents avoid
> the visibly sick — both of which are themselves evolving.
>
> Note the third route, which Rule 2.14 opens: a strain can raise its *realised*
> contagion without raising its contagion factor, by manipulating the host into
> seeking contact. Expect strains to discover it.

### 2.2 Two immunities, matching two existing rules

**Rule 2.8** — **Innate immunity** is genotype: heritable loci, crossed over and
mutated like any other (`genotype-spec.md` §7).

**Rule 2.9** — **Adaptive immunity** is acquired. An agent that survives an
infection recognises that signature thereafter. It is held in the agent's own
space and is **lost when the agent perishes** (`genome-spec.md` Rule 7.3).

> The split is not invented for the occasion; it falls out of rules already
> written. `genotype-spec.md` Rule 5.1 makes gained attributes uninheritable, and
> Rule 7.3 destroys what an agent learned when it dies. Applying both to immunity
> gives exactly the biological division between **innate** immunity, which is
> inherited, and **adaptive** immunity, which is earned in a lifetime and dies
> with the body. That the simulation's existing rules produce that division
> unprompted is a sign they are the right rules.

### 2.3 Transmission

**Rule 2.10** — Pathogens transmit on **contact** — negotiation, deliberation,
combat and breeding all carry risk — with probability governed by the strain's
**contagion factor** against the target's resistance (Rule 2.2).

> Contact is not optional. Rule 2.3 of `genome-spec.md` makes cooperation
> compulsory — four kinds are needed, a world holds two — so **infection is the
> standing cost of the thing the game requires you to do**. That is the property
> worth protecting in any later revision: a disease avoidable by playing
> defensively would simply select for hermits, and hermits cannot exist here.

**Rule 2.11** — Worlds harbour **endemic strains**. An agent entering an
unfamiliar world meets signatures its line has never faced.

> Which prices travel a third time. Distance already costs risk of stranding and
> loss to decay; now it costs exposure. A well-travelled agent is a well-supplied
> one and a vector.

**Rule 2.12** — Strains **mutate on transmission**, so a signature that has swept
a population drifts away from the immunity that population evolved. A mutated
strain takes a **new UUID** and records its parent (Rule 2.3).

**Rule 2.13** — **A teleport carries a small random chance of creating an
entirely novel strain**, with a signature unrelated to any in circulation.

> This makes travel the origin of disease as well as its vector, and it has
> consequences worth stating.
>
> **A novel signature matches no immunity anywhere.** Innate immunity is a
> genotype's accumulated match (Rule 2.4) and adaptive immunity requires prior
> exposure (Rule 2.9) — neither can anticipate a signature drawn at random. Novel
> strains are therefore maximally dangerous at the moment they appear, and they
> appear at the frontier where agents are furthest from home.
>
> **Emergence scales with traffic.** The rate of new disease is proportional to
> teleport volume, so a busy simulation is a sick one — and the well-connected,
> who travel most (Rule 6.2), both generate and meet more of it. This deepens
> §1.3: connectivity now costs a third time.
>
> **And it closes a feedback loop.** Disease suppresses travel, through visible
> infection making agents unwelcome and through suppressed expression making them
> less capable. Less travel means fewer novel strains. The system regulates its
> own disease pressure without a governor, which is a far better property than a
> tuned emergence rate would be.

**Rule 2.10a** — A novel strain's signature is drawn **near an existing one**,
not uniformly at random. New diseases are variants; they descend.

> Which keeps immunity meaningful over time. A uniformly random signature would
> match nothing anywhere, so surviving a plague would confer no protection against
> anything that followed, acquired immunity would be nearly worthless, and the
> Red Queen argument for breeding (§1.1) would lose its object — recombination
> cannot outrun an adversary that ignores what you have already survived.
>
> Drift instead produces **recognisable families of related diseases**, so an
> antigen retained from a past infection partially covers its descendants. That is
> what makes the retention period in Rule 2.19 worth having, and what makes
> immune-complementary breeding pay.

### 2.4 What infection does: it changes expression

**Rule 2.14** — A pathogen **temporarily alters the expression of a set of
genotype attributes**. The genotype is untouched; the **expressed phenotype**
differs while the infection lasts (`genotype-spec.md` Rule 1.4).

**Rule 2.15** — Each pathogen carries a **target set**: which attributes it
modulates, and in which direction. Two strains are different diseases because
they express differently, not because they do different amounts of damage.

**Rule 2.16** — On recovery, expression returns **exactly** to baseline. Nothing
is permanently lost, and nothing is inherited.

> This is a far better mechanism than a table of bespoke effects, and it earns
> its place three times over.
>
> **It unifies every effect worth having.** Suppressed Courage weakens an agent;
> suppressed Prudence makes it reckless; suppressed Charisma makes it unattractive.
> None of these needs its own rule — they are all one operation on different
> targets, and a new disease is a new target set rather than new code.
>
> **Derived attributes cascade, and unevenly.** Suppressing Courage lowers
> Stamina, Attack and Cargo capacity at once. And because Attack is a *harmonic*
> mean while Stamina is *arithmetic* (`genotype-spec.md` Rule 4.2), the same
> suppression hits Attack disproportionately: harmonic means are dominated by
> their smallest term. **A pathogen targeting an input to a compound act is far
> more dangerous than one targeting a reservoir input** — an asymmetry that falls
> out of rules written for entirely different reasons, and which gives strains a
> natural virulence ordering nobody has to assign.
>
> **It makes infection legible through behaviour.** Attributes are hidden
> (`genotype-spec.md` Rule 6.6) but *conduct* is observed, and opinions are built
> from conduct (Rule 6.9). An infected agent negotiates worse, fights worse and
> looks less attractive — so observers revise their estimates downward, and those
> estimates persist as a running average weighted by the observer's
> **Vindictiveness**. **An agent can therefore be reputationally scarred by a
> disease it has fully recovered from**, for as long as its acquaintances'
> memories last. That is an unusually good consequence to get for free.
>
> Note also that it makes suppressed Fecundity unnecessary as a separate effect:
> an infected agent expresses worse attributes, so it is *judged* less
> attractive, and selection acts against it through ordinary mate choice.

**Rule 2.17** — A pathogen may **raise** an expression as well as lower it.

> Raising sounds like a gift and is usually a trap. A strain that elevates
> **Cooperativeness**, **Wanderlust** or **Amenability**, or suppresses
> **Prudence**, makes its host seek contact — and contact is transmission
> (Rule 2.10). Such a strain spreads faster than one that merely weakens, so
> **selection favours manipulative strains over purely damaging ones**.
>
> This is not a designed flourish; it is what happens to real parasites that can
> reach host behaviour, and rabies and *Toxoplasma* are the standard examples. It
> arrives here for free because dispositions are expressed attributes like any
> other. It also creates the most interesting diagnostic problem in the
> simulation: **an unusually agreeable stranger may be unusually agreeable, or it
> may be infected with something that wants you to think so.**

### 2.5 Antigens

**Rule 2.18** — An **antigen** counteracts a pathogen's expression modifier,
restoring the affected attributes toward baseline.

> Terminology note, recorded so the choice is deliberate: in immunology an
> *antigen* is the molecule that provokes a response, and the counter-agent is an
> *antibody*. This specification follows the working usage, in which "antigen"
> names the counter. Worth renaming before implementation if the audience is
> likely to include anyone who will read it the other way.

**Rule 2.18a** — An antigen is **synthesised during infection**, not after it.
Synthesis begins once the infection is **detected** and proceeds at a **rate**,
both governed by loci: **Immune Vigilance** and **Synthesis Speed**.

**Rule 2.18b** — An antigen is a **vector in signature space** (§2.0) and covers
part of it. **No antigen is bound to a strain.** It counteracts whatever its
coverage overlaps.

**Rule 2.18c** — An infection is countered when the **combined coverage of every
antigen the agent holds** meets the strain's signature above a threshold. Several
partial antigens may do what no single one can.

**Rule 2.18d** — An antigen **decays from the moment it exists**, at a rate fixed
at synthesis from the **synthesising agent's** genotype. A well-made antigen
outlasts a poor one and carries that quality wherever it goes.

**Rule 2.18e** — Antigens are **information**. They are shared over A2A, **copied
rather than transferred**, and giving one costs the giver nothing.

**Rule 2.18g** — An antigen received over A2A **may be false** — a vector that
covers nothing, or less than was claimed. It is a claim like any other: the
sharer's **Honesty** governs whether it is real, the recipient's **Credulity**
governs whether it is trusted, and the truth is discovered when infection tests
it.

**Rule 2.18h** — A world holding an **Apothecary** (`construction-spec.md` §2) can
**authenticate** an antigen: an agent present there may have one verified before
relying on it.

> Rule 2.18g follows the design's spine — everything said over A2A may be false
> (`genome-spec.md` Rule 8.5) — and making antigens the sole unfakeable
> information would have been a special case cutting against it. Trust in
> medicine becomes emergent: a synthesiser known to hand out real coverage is
> worth travelling to, and Rule 2.18c's combined coverage means a fake *dilutes*
> protection rather than annihilating it.
>
> Note what this does not reopen. `pathogen-spec.md` §4.2 ruled that disease is
> never a weapon, and a fake antigen is **fraud, not assault** — it causes no
> infection, it fails to prevent one, and it works exactly once per victim per
> liar (Rule 6.10a's surprise update sees to that).
>
> **Rule 2.18h gives the Apothecary branch a service its root lacked.** The branch
> healed and retained; now it also *verifies*, which makes an Apothecary world a
> medical marketplace — the place where antigens are worth more because they can
> be proven, and where a liar's stock is worth less because proof is on offer. The
> asymmetry is deliberately geographic: verification exists where a coalition
> built it, so rich worlds trade certified medicine and poor ones trade on trust.

**Rule 2.18f** — Recovery follows from coverage (Rule 2.18c), or is **immediate at
a Sanatorium** (`construction-spec.md` §2). Nothing else ends an infection.

> This replaces an earlier reading in which an antigen was earned on recovery and
> matched one strain. Synthesis-during-infection is better in four ways, and one
> of them changes the economics of the whole document.
>
> **Recovery becomes something an agent does rather than waits out.** Detection
> Latency and Synthesis Speed make the immune response a *race* against the
> strain's replication, so severity and duration come apart into two heritable
> things instead of one.
>
> **Partial coverage makes immunity combinatorial.** Because Rule 2.18b unbinds
> antigens from strains, a novel pathogen is not a blank wall — an agent may
> already hold two antigens that together cover it. That is what §2.10a's descent
> was reaching for: strains inherit signatures from their parents, so accumulated
> coverage degrades gracefully rather than failing at the first mutation.
>
> **Antigens are the only non-rival good in the design.** Cargo, berths, capacity
> and piles are all diminished by being shared; an antigen is copied, so a giver
> loses nothing. That is a domain where cooperation is *free*, inside a document
> where it is otherwise always costly — and it yields a testable prediction from
> our own results. `genome-spec.md` Rule 12.15 found that Cooperativeness expresses
> only when cooperating costs something. **So Cooperativeness should not predict
> antigen sharing.** If it does, Rule 12.15 is wrong; if it does not, some other
> locus is doing the work and it is worth knowing which.
>
> **What stops this trivialising disease is Rule 2.18d.** A shared antigen is a
> wasting asset, arriving already decaying at a rate set by whoever made it, so a
> population cannot solve epidemiology once and be done. Coverage must be
> continually reacquired, which keeps the arms race running.
>
> The **Inoculist** (§4.4) keeps its purpose and gains a sharper one: its bank
> holds antigens **against decay**. It is not a distributor of something otherwise
> unobtainable — anyone may copy an antigen — but a keeper of old coverage the
> population has let lapse.

**Rule 2.19** — The **holder modulates** an antigen's decay. Its intrinsic rate
(Rule 2.18d) is scaled by the holder's retention, derived as the **geometric mean
of Knowledge and Longevity** — how well the agent recognises, and how robust its
constitution.

> Two terms rather than one, because an antigen now travels. Its intrinsic rate is
> a fact about how it was made; retention is a fact about who carries it. The same
> antigen lasts longer in a robust host, and a well-made one outlasts a poor one in
> the same host — so both *whose* antigen you received and *who you are* matter,
> which is what makes a good antigen worth asking for by name.

**Rule 2.20** — Immunity is **graded by coverage**, not binary. Re-exposure is
resisted in proportion to how well the agent's combined antigens cover the
signature, and as they decay vulnerability returns by degrees.

**Rule 2.20a** — An Inoculist holds a **small, bounded bank** of antigens, and
**granting one consumes it**.

> Both halves are load-bearing. A bounded bank cannot grow to cover a whole
> drifted family, so it never becomes the substitute for genetic immunity that
> §4.4's reasoning depends on it not being. Consumption on grant makes each
> immunisation a **real choice about whom to protect** — an Inoculist with three
> antigens and a coalition of eight is a scarce medical resource making triage
> decisions, which is a far more interesting agent than a dispenser.

**4.5 Decided — out.** Pathogens do not touch the knowledge store. Infection
changes expression, temporarily and reversibly (Rule 2.14); corrupting a store
would destroy data permanently, which is not an expression change at all.

> It would also break the product. `genome-spec.md` §8.1.6 guarantees that
> deception reaches a user as *uncertainty*, never as false certainty — a disease
> that silently rewrote an agent's knowledge would put fabrications into the
> user's answers with nothing marking them, which is precisely the failure that
> guarantee exists to prevent. **A mechanic that is frightening in the game and
> corrosive to the product is not a trade worth making.**

**4.6 Decided** — a regenerated agent returns **cured and unimmunised**.
Rule 7.2's "original state" is taken literally: no infection, and none of the
antigens the agent had earned (Rule 2.19).

> Death is therefore a cure and an amnesia at once, which is what stops it being
> an escape. An agent that dies to shed a plague wakes with **no defence against
> the next one, or against the one it just had** — so deliberate death trades a
> current infection for permanent vulnerability, on top of losing its cargo, its
> knowledge and its gained attributes.
>
> This also protects the `Sanatorium` (`construction-spec.md` §3.1), the only cure
> in the design. If regeneration preserved immunity, dying would be a cheaper
> Sanatorium and a four-kind capstone would be competing with suicide.

**4.7 Decided** — near an existing strain (Rule 2.10a). New diseases descend, so
immunity retains value and families of related strains form.

**4.8 Decided** — infection distance runs **well below typical Sight**, topping
out at roughly a quarter of the Sight range.

> So most agents can usually see an infected one in time to move away, which keeps
> visible infection (Rule 2.21) a real defence rather than a warning that arrives
> too late. It also gives Sight a second reason to be worth allocating budget to,
> unrelated to combat — and leaves a genuinely dangerous minority of long-reach
> strains against which only a high-Sight agent has any warning at all.

**4.9 Decided — yes** (Rule 2.7a). Strains allocate across replication, contagion
and distance, so no strain is dangerous on every axis at once.

**4.10 Decided** — a small bounded bank, and granting consumes (Rule 2.20a). An
Inoculist performs triage rather than dispensing.
**Rule 2.21** — **Infection is visible.** Alongside colour
(`genotype-spec.md` §3.5), it is the second thing an agent broadcasts whether it
wishes to or not.

> Attributes are hidden and this deliberately is not. Visible infection gives
> agents something honest to act on: they can refuse contact with the obviously
> sick, which makes avoidance a behaviour rather than a rule, prices contagion
> into every meeting, and gives the epidemiology a counterforce that nobody has
> to administer. (Restored: this rule was inadvertently dropped when §2.5 was
> rebuilt around synthesised antigens; `interface-spec.md` Rule 6.9i renders it.)

