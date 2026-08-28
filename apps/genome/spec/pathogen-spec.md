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
> since infection is visible (§2.6) — is refused contact by agents that would
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

**Rule 2.19** — An antigen **persists in the immune system for a retention
period derived from the agent's genotype**, then lapses. Proposed derivation: the
**geometric mean of Knowledge and Longevity** — how well the agent recognises,
and how robust its constitution.

**Rule 2.20** — While an antigen is retained, re-exposure to the matching
signature produces no infection. Once it lapses, the agent is vulnerable again.

> **Waning immunity is what keeps the arms race alive**, and it is the reason
> Rule 2.14 matters more than it looks.
>
> If immunity were permanent, an agent that survived enough strains would become
> effectively invulnerable, and for that individual the Red Queen would stop
> running. Worse, a long-lived population would accumulate universal immunity and
> pathogens would cease to be a pressure at all — taking with them the check on
> monoculture (§1.2) and the justification for sex (§1.1). Retention with an
> expiry keeps everyone perpetually re-exposed.
>
> The division of labour is now clean and worth stating plainly. **Innate
> immunity is genetic, permanent, and inherited. Adaptive immunity is earned,
> temporary, and dies with the agent** (Rule 2.9). So surviving a plague is a
> *tactical* advantage that fades, while breeding for resistance is the *strategic*
> one that lasts — which is exactly the conclusion §1.1 needs, reached from the
> other direction.

### 2.6 Visibility

**Rule 2.21** — **Infection is visible.** Alongside colour (`genotype-spec.md`
§3.5), it is the second thing an agent broadcasts whether it wishes to or not.

> Attributes are hidden and this deliberately is not. Visible infection gives
> agents something honest to act on: they can refuse contact with the obviously
> sick, which makes avoidance a real strategy and gives disease a reason to evolve
> toward mildness. An invisible plague selects only for resistance; a visible one
> selects for resistance *and* social judgement, which is far more interesting in
> a simulation about negotiation.
>
> It also sits in productive tension with Rule 2.12. If infection is visible but
> the *manipulation* is not — a strain that makes its host agreeable while
> announcing itself — then agents face a genuine dilemma rather than a lookup: the
> sick are contagious, and this one is being very reasonable about it.

## 3. What this produces

**Disassortative mating, without needing perception.** Parents with
complementary immune profiles have offspring covering more antigen space, so
those offspring survive at a higher rate. The alleles spread even though no
agent can see immunity and none is choosing for it. Selection does the work that
perception cannot — and if immune profiles were ever made perceptible, deliberate
MHC-style mate choice would emerge on top of it.

**A frequency-dependent arms race.** A strain matched to the commonest genotype
prospers, which selects against that genotype, which changes what is common,
which strands the strain. Neither side converges. This is the mechanism that
keeps a population diverse without any rule mandating diversity.

**Genuine value in the diversity that sponsorship threatens.** §1.2 — the check
is automatic and needs no cap.

---

## 4. Open questions

**4.1 Decided** — 8 to 16 dimensions (Rule 2.0), the band in which immunity is
meaningful but never complete.

**4.2 Decided — no.** There is no skill that deliberately infects another agent.
Disease is a hazard of the world, never a weapon in anyone's hand.

> The reason is that pathogens already earn their place without a wielder. They
> punish monoculture (§1.2), price connectivity (§1.3) and supply the Red Queen
> argument for sexual reproduction (§1.1) — none of which needs anyone to aim
> them. Making plague a targeting decision would crowd out the epidemiology that
> made it worth having, and would push a population toward avoiding contact in a
> design that cannot afford isolation (`genome-spec.md` Rule 2.3).

**4.3 Decided — yes.** A strain's signature, replication factor, contagion
factor, infection distance and parent UUID **are a genotype**, and are formalised
as one. Strains are a second evolving population, selected in their own right.

> Which turns the arms race from a metaphor into a mechanism. **Virulence now
> settles where selection puts it rather than where a designer guesses.** The
> replication-against-transmission trade-off in §2.1.2 stops being an argument
> about how strains *ought* to behave and becomes an outcome to observe: strains
> that kill their reach die with it, strains too mild are outcompeted for hosts,
> and the population finds the intermediate on its own.
>
> It also completes a symmetry the design had been building toward. Agents and
> strains now both have: a genotype, mutation, descent recorded by UUID, and a
> fitness landscape composed of the other population. **Neither side is the
> environment; each is the other's.**

**Rule 2.7a** — Replication, contagion and infection distance **share a fixed
budget**, exactly as agents' physiological loci do (`genotype-spec.md` §3.10). A
strain allocates; it does not accumulate.

> The argument that forced a budget on agents applies unchanged: **a gene with no
> trade-off is a setting.** Without one, selection drives every axis upward at
> once and the population converges on a single strain that is severe, contagious
> and far-reaching — which is not an ecology, it is an ending.
>
> With one, a strain must choose what kind of disease to be. Reach costs
> intensity; severity costs transmission. That is the virulence–transmission
> trade-off (§2.1.2) enforced structurally rather than left to behaviour, and it
> is what lets several strategies coexist — a mild endemic and a savage local
> outbreak occupying different corners of the same budget.

**4.4 Decided — yes, as a rare skill.** An **Inoculist** may preserve antigens
past its own death and grant them to other living agents.

> I had argued against this on the grounds that it blurs the innate-versus-adaptive
> split the Red Queen argument depends on. Drift resolves the objection, and it is
> worth setting out because it is what keeps both mechanisms necessary.
>
> Novel strains descend from existing ones (Rule 2.10a). So a banked antigen covers
> what has already been survived and the near descendants of it — **it defends
> against the past.** Genetic recombination covers signature space nobody has met
> yet — **it defends against the future.** Because strains keep drifting, a
> stockpile of antigens is a depreciating asset: valuable now, less so each
> generation, and never a substitute for a diverse immune profile.
>
> So an Inoculist is powerful without being a replacement. It makes a lineage
> resilient against the diseases of its own era, and no better prepared for the
> next one — which is precisely the shape a vaccine bank should have.

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
> visible infection (Rule 2.18) a real defence rather than a warning that arrives
> too late. It also gives Sight a second reason to be worth allocating budget to,
> unrelated to combat — and leaves a genuinely dangerous minority of long-reach
> strains against which only a high-Sight agent has any warning at all.

**4.9 Decided — yes** (Rule 2.7a). Strains allocate across replication, contagion
and distance, so no strain is dangerous on every axis at once.

**4.10 Decided** — a small bounded bank, and granting consumes (Rule 2.20a). An
Inoculist performs triage rather than dispensing.
