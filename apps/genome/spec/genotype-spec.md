# Genome — genotype, phenotype and inheritance

Specification for what an agent *is*: the heritable material, the attributes
expressed from it, and how two agents produce progeny. Companion to
`genome-spec.md` (worlds, resources, encounters) and `skills-spec.md`.

**Status: draft.** §9 lists what remains contradictory or undecided in the
source material.

---

## 1. The genotype is a vector of numeric loci

**Rule 1.1** — A genotype is an **ordered vector of numeric loci**. Each locus
has a name, an integer range, and a value within it. The vector has fixed length
and fixed order; every agent's genotype has the same loci in the same positions.

> Not a single packed integer. Packing into 32 bits was tempting — crossover
> becomes a bit operation — but it caps the whole design at 32 bits of heritable
> material, forces every trait into 3 or 4 bits, and makes the declared 1–10000
> ranges unreachable (16 values spaced ~625 apart is not a range). A vector costs
> a little compactness and removes the ceiling. Bit-packing remains available as
> a *serialisation* (§8), which is where it belongs: an encoding detail, not the
> model.

**Rule 1.2** — **Fixed order is load-bearing.** Crossover pairs locus *i* of one
parent with locus *i* of the other, so inserting a locus in the middle
reinterprets every existing genotype. New loci are appended, never inserted, and
retired loci are tombstoned rather than removed.

> This is the versioning constraint the platform already understands: an agent's
> content hash certifies what it was (AG §4.2). A genotype whose fields shift
> meaning under it certifies nothing.

**Rule 1.3** — **Baseline phenotype** is a pure function of genotype. The same
genotype always expresses the same baseline agent. Nothing outside the vector —
world, time, owner — participates in producing it.

**Rule 1.4** — **Expressed phenotype** is the baseline as modified by transient
**expression modifiers**, of which infection (`pathogen-spec.md` §2.4) is the
first. Modifiers change what an agent *is right now*; they never touch the
genotype and are never inherited.

> Splitting these two is what lets a pathogen alter an agent without corrupting
> the model. Rule 1.3 was originally written to forbid *anything* outside the
> vector from participating in expression, and it had to be, because the value of
> a genotype depends on it determining what it produces. A pathogen that changed
> the genotype would be inherited, would make infection permanent, and would make
> a lineage's history unreadable.
>
> A modifier layer keeps every guarantee that mattered. The genotype still
> determines the baseline exactly; progeny are unaffected by whatever afflicted
> their parents; and an agent that recovers returns precisely to what it was. What
> changes is only the reading taken today.

---

## 2. Normalisation, and why nothing may be zero

**Rule 2.1** — Every locus normalises to the half-open interval **(0, 1]**:

```
norm(v) = (v - min + 1) / (max - min + 1)
```

**Rule 2.2** — No normalised value is ever 0, for any locus, including Gender.

> This is the repair for a live defect. Attractiveness is a weighted harmonic
> mean, `A = Σw / Σ(w/x)`, so any `x = 0` divides by zero. Gender is `{0, 1}` with
> weight 1: the working spreadsheet records `0` for that term, quietly
> substituting zero for infinity. With the true value the sum diverges and
> attractiveness collapses to 0 for **half the population**. Attack, Mana and
> Stamina share the flaw — all three declare a minimum of 0.
>
> Rule 2.1 fixes all of them at once, with no special cases and no attribute
> excluded. Gender 0 normalises to 0.5, Gender 1 to 1.0. A 0–10000 locus at its
> floor normalises to 1/10001, small but finite.

**Rule 2.3** — Derived and gained attributes (§4, §5) normalise by the same
formula, using their own declared ranges.

> **Resolved, but worth recording how.** Rule 2.1 removes the divide by zero and
> leaves an asymmetry in its place: Gender 0 → 0.5 contributes `1/0.5 = 2` to the
> denominator while Gender 1 → 1.0 contributes `1`, so one gender would be
> uniformly less attractive than the other by the largest margin in the sum. Both
> problems had the same root — scoring a compatibility relation as though it were
> a quality. Rule 6.5 removes Gender from the sum entirely and makes it a gate,
> which ends the asymmetry rather than rebalancing it.

---

## 3. The loci

Four groups. The first is the working notes' original set; the rest are
additions, argued in §3.8.

**Read §3.9 and §3.10 first.** The loci below do not express their face value: the
physiological ones are shares of a fixed budget, which is what stops every one of
them evolving straight to its maximum.

### 3.1 Capability — what an agent can do

| Locus | Range | Meaning |
| :--- | :--- | :--- |
| Intelligence | 1–10000 | Ability to cast |
| Knowledge | 1–10000 | Ability to escape a cast |
| Dexterity | 1–10000 | Ability to inflict damage |
| Agility | 1–10000 | Ability to escape damage |
| Charisma | 1–10000 | Ability to attract a mate |
| Courage | 1–10000 | Feeds stamina and attack |
| Range | 1–100 | Distance at which it can strike |
| Sight | 1–100 | Distance at which it can sense |
| reStamina | 0–1 | Regenerates stamina |
| reMana | 0–1 | Regenerates mana |

### 3.2 Disposition — what an agent tends to do

| Locus | Range | Meaning |
| :--- | :--- | :--- |
| **Cooperativeness** | 0–10000 | Propensity to cooperate *first*, before knowing the other |
| **Reciprocity** | 0–10000 | Propensity to respond in kind — honour honour, punish defection |
| **Vindictiveness** | 0–10000 | How long a defection is held against a counterparty |
| **Aggression** | 0–10000 | Propensity to attack rather than negotiate |
| **Honesty** | 0–10000 | Propensity to make only claims it believes true |
| **Credulity** | 0–10000 | Propensity to believe another agent's claims |
| **Amenability** | 0–10000 | Openness to being instructed by another agent or its owner |
| **Loyalty** | 0–10000 | Preference for a known counterparty over a stranger |
| **Patience** | 0–10000 | Weight given to future payoff over immediate |
| **Curiosity** | 0–10000 | Propensity to explore unknown map over exploiting known piles |
| **Prudence** | 0–10000 | Readiness to turn for home rather than press on with cargo |
| **Wanderlust** | 0–10000 | Propensity to travel far from the home world |
| **Fecundity** | 0–10000 | Eagerness to breed when the opportunity arises |
| **Selectivity** | 0–10000 | Minimum attractiveness it will accept in a mate |

### 3.3 Preference — how an agent judges others

**Rule 3.1** — Every agent carries a **preference vector**: one weight per
attribute it can assess in another agent. These are loci like any other:
heritable, crossed over, mutated.

**Rule 3.2** — Attractiveness is computed with the **assessor's own weights**
(§6). There is no universal ranking. Two agents can look at the same third agent
and disagree about whether it is worth mating with.

> This is a much larger change than one line suggests. Preferences being
> heritable means **traits and the taste for those traits evolve together** — the
> condition for sexual selection, and specifically for Fisherian runaway: a
> preference for high Charisma raises the fitness of Charisma, which raises the
> fitness of the preference, and the pair can spiral into ornament with no
> survival value at all. Peacock tails are the textbook case. Expect it to happen
> here, and recognise it as the model working rather than a bug — it is one of
> the most interesting things a system like this can produce unprompted.

### 3.4 Meta

| Locus | Range | Meaning |
| :--- | :--- | :--- |
| **Gender** | 0–1 | Breeding compatibility. A **gate**, not a virtue — see §6.2. |
| **Mutability** | 0–10000 | This agent's own mutation probability (§7.4) |
| **Longevity** | 0–10000 | Expected lifespan before natural perishing |

### 3.5 Provenance — colour

**Rule 3.3** — An agent carries **two colour loci**. An agent materialised by a
user inherits the two colours of its birth world's two resource kinds
(`genome-spec.md` §4.3). An agent born of two parents inherits its colours from
theirs by ordinary crossover and mutation.

**Rule 3.4** — Colour is the **only attribute visible to other agents** (§6.3).
Everything else is hidden.

> Colour is doing something no other locus does, and it is worth being explicit
> about why it matters.
>
> **It makes the founding constraint visible.** Rule 2.3 requires four kinds and a
> world holds two, so agents must combine — and breeding requires 2 units of 4
> different kinds. Two agents can see at a glance whether their four colours are
> distinct. Colour is therefore a *courtship signal that encodes exactly the
> compatibility the rules demand*, without anyone designing it as one.
>
> **It is a hard-to-fake signal of provenance.** Since attributes are hidden
> (§6.3) and colour is inherited, colour is the one honest-ish thing an agent
> broadcasts: where its line came from, and therefore which resources it is likely
> to have access to. Expect agents to discriminate on it — and note that the
> useful heuristic is *difference*, not similarity. An agent whose colours differ
> from yours probably comes from worlds holding kinds you lack, which makes it a
> better trade partner. Colour homophily would be the strategically wrong instinct
> here, which makes it interesting if it evolves anyway.

**Rule 3.5** — Colour inherits **particulately**. Progeny take **one colour at
random from each parent**, giving them two. A colour is copied whole; **colours
are never averaged or blended.**

> Note that both parents' colours are candidates, so a child of parents holding
> {red, blue} and {red, green} may inherit {red, red} — a duplicated colour, and a
> legible mark of a narrowing line. It should be allowed rather than prevented:
> Rule 2.3 makes four *distinct* kinds the thing agents need, so an agent
> broadcasting only one is visibly a poorer prospect, and that is information the
> population should be able to act on.
>
> Averaging is the thing to avoid, and not as a stylistic preference. Blending
> inheritance destroys variance: if
> each generation's colour is the mean of its parents', the population converges
> to a single muddy average within a few generations and the signal in Rule 3.4
> stops carrying information. This was the strongest 19th-century objection to
> Darwin — Fleeming Jenkin's — and Mendelian particulate inheritance is precisely
> what answers it. Taking colours whole preserves the variance the signal depends
> on, and lets mutation reintroduce novelty gradually rather than being swamped.

### 3.6 Immunity

Three heritable things, answering three different questions
(`pathogen-spec.md`).

| Locus | Range | Question it answers |
| :--- | :--- | :--- |
| **Immune profile** | vector | *Do I recognise this particular strain?* |
| **Infection Propensity** | 0–10000 | *Does an exposure become an infection?* |
| **Infection Resistance** | 0–10000 | *Once infected, how badly and for how long?* |

**Rule 3.6** — The **immune profile** is a vector of loci encoding recognised
signatures. It is matched against a strain's signature and is **specific**: it
protects against what it recognises and nothing else.

**Rule 3.7** — **Infection Propensity** governs the *exposure* stage, weighed
against the strain's contagion factor and distance. **Infection Resistance**
governs the *infection* stage, weighed against the strain's replication factor.
Both are **general**: they apply to every strain alike.

> The division is worth keeping straight, because the three are easily mistaken
> for one another. Specific immunity is a lock and key — it either fits or it does
> not. Propensity and resistance are constitution, and they apply to a strain
> nobody has ever met. An agent can be highly resistant in general and still
> defenceless against one particular signature, which is exactly the situation a
> novel strain (`pathogen-spec.md` Rule 2.13) creates for everyone at once.
>
> They also attach to different stages, which matters mechanically. Propensity
> decides *whether you catch it*; resistance decides *how bad it is and how long
> it lasts*. Two agent loci against the strain's two properties — contagion
> against propensity, replication against resistance — which is a tidier
> correspondence than it looks, and means neither side has a property the other
> cannot answer.

#### 3.6.1 Immunity has to cost something

**Rule 3.8** — Immune investment **suppresses Fecundity**, because both draw on
the same allocation budget (§3.9). No separate coupling is needed; they compete
for the same points.

> Rule 3.8 is not decoration, and without it the two new loci are dead on
> arrival.
>
> A locus that is purely beneficial goes to its maximum and stays there; a locus
> that is purely harmful goes to zero. Resistance and Propensity as first proposed
> are exactly that pair — every lineage would evolve maximum resistance and
> minimum propensity within a few generations, both loci would fix, and they would
> thereafter be constants wearing the costume of genes. **A gene with no trade-off
> is a setting.**
>
> Coupling immunity to Fecundity is the standard biological answer and the right
> one here: immune tissue is expensive, and organisms that invest in it invest
> less in offspring. It makes both loci permanently live, because the optimal
> setting depends on conditions that keep changing.
>
> **And it should oscillate rather than settle.** Under heavy disease pressure,
> selection favours immunity and the population's birth rate falls. A well-defended
> population suffers few epidemics — at which point the cost of immunity is no
> longer repaid, selection favours Fecundity, and defences erode. Eroded defences
> invite the next epidemic. **Boom and bust, driven by nothing but the two loci
> disagreeing about which decade it is** — which is a far better result than
> convergence on an optimum, and it is the sort of thing this simulation exists to
> produce.

**Rule 3.8a** — Fecundity is the named cost of immunity, and deliberately so.

> The alternatives were defensible and neither oscillates. Costing endurance would
> tie disease to geography — the healthy stay home, the bold get sick — and settle
> into a stable equilibrium. Spreading the cost across the whole budget is the most
> consistent option and the least legible: it removes the specific tension between
> **defending yourself and reproducing**, which is the one that cycles.
>
> Heavy disease selects for immunity; birth rates fall; epidemics become rare;
> immunity stops repaying its cost; defences erode; the next plague arrives.
> **Nothing else available produces that.**

### 3.7 Endurance — how long cargo survives

Carried resources decay (`genome-spec.md` Rule 4.18). Two genotype quantities
govern it.

| Quantity | Kind | Range | Meaning |
| :--- | :--- | :--- | :--- |
| **Depletion Rate** | Locus | 0–10000 | Units lost per interval once decay begins |
| **Safe Period** | Derived | — | Interval before decay begins |

**Rule 3.9** — **Depletion Rate** is a locus, inherited like any other. **Safe
Period** is **derived**, as the geometric mean of **Knowledge** and **Prudence** —
knowing how to keep a thing, and caring enough to.

> Together these decide **how far an agent can usefully range**, which makes them
> among the most strongly selected quantities in the genotype. An agent with a
> long safe period and a slow rate can work distant worlds; one without is
> confined to its own neighbourhood however adventurous its Wanderlust. That is a
> genuine tension between two loci — the desire to roam and the capacity to
> profit from roaming — and lineages that inherit one without the other will do
> visibly badly, which is exactly the sort of pressure that produces interesting
> population structure.
>
> Note also that these are the loci an agent cannot bluff about. Attributes are
> hidden (§6.3), but a counterparty who watches an agent's cargo shrink is
> observing its Depletion Rate directly. Decay is a **behavioural tell** — the one
> place where the simulation leaks genotype into public view.

> Deriving Safe Period rather than giving it a locus is the deliberate choice.
> It **couples endurance to traits selected for other reasons**, so an agent
> cannot become a long-range hauler without also being knowledgeable and cautious
> — and those same loci are wanted elsewhere, for resisting casts and for judging
> when to turn back. The result is a genuine trade-off inside one genotype rather
> than a free parameter that evolution can optimise in isolation. The geometric
> mean is the right combiner because it is unforgiving of imbalance: knowing how
> to preserve cargo is worth little without the disposition to act on it, and
> vice versa.

### 3.8 Why the disposition loci belong in the genotype

**The original set encodes a combat simulation, and genome is not one.**
Intelligence, Dexterity, Range, Sight, Attack, Mana describe an agent that
fights and casts. But `genome-spec.md` Rule 9.1 makes the standing objective
*negotiation*, its Rule 9.2 makes exchange *barter*, and its Rule 2.3 makes cooperation
*mandatory*. None of that was heritable.

The consequence is severe: **strategy would not evolve.** Selection would act on
how hard an agent hits and never on whether it keeps its word — so a simulation
described as game-theoretic would produce better fighters and never a better
negotiator.

Three of these loci reproduce **Axelrod's decomposition** of what made
tit-for-tat win the repeated Prisoner's Dilemma tournaments, and together they
let the genotype express any point in that strategy space:

- **Cooperativeness** is *niceness* — never defecting first.
- **Reciprocity** is *retaliation* — answering defection in kind.
- **Vindictiveness** is the inverse of *forgiveness* — whether a grudge ever
  ends. Its absence is what turns a single mistake into permanent mutual
  punishment.

The rest each make something in the simulation mean something:

- **Aggression** turns every encounter into Hawk–Dove; the stable mix of
  aggressive and peaceable agents becomes an outcome rather than a parameter.
- **Honesty** and **Credulity** are a matched pair, and neither works alone.
  Deception needs both a liar and a believer: without Credulity the `Rumour`
  skill has nothing to act on, and without Honesty an honest and a lying agent
  are indistinguishable in their effects.
- **Amenability** is the axis the social skills act along — orchestration,
  Promptsmithing, Objective Seeding. It carries a genuine dilemma with no
  dominant setting: high Amenability makes an agent a willing subordinate and
  an easy mark; low Amenability makes it independent and impossible to organise.
  Whether the population settles toward biddable or wilful is exactly the kind
  of result this simulation exists to produce.
- **Loyalty** is what lets reputation matter. If every encounter is with a
  stranger, `Chronicle` records nothing anyone can use; a preference for repeat
  partners creates the recurring relationships in which reputation has value.
- **Patience** is the shadow of the future — cooperation is rational only when
  the future is weighted heavily enough, and making the discount rate heritable
  lets the population discover that itself.
- **Curiosity** is explore-versus-exploit, made concrete by procedurally
  generated maps and piles that differ in yield (`genome-spec.md` §5).
- **Prudence** prices the round trip. Cargo counts for nothing until deposited
  and is lost with the carrier, so *when to turn back* is a real decision and
  belongs under selection.
- **Wanderlust** prices distance, and is the locus selection should grip
  hardest, since travel is where everything is lost.

### 3.9 Every locus has a faculty

**Rule 3.19** — **No locus is decorative.** Every locus drives at least one
**computed faculty** — a quantity or capability the runtime evaluates — in
addition to being expressed as disposition in the agent's prompt.

**Rule 3.20** — **Loci are never removed.** A locus without a faculty is not a
locus to delete; it is a faculty not yet found. The obligation runs the other way:
find the use.

**Rule 3.20a** — A faculty is **genuine** if varying that locus alone, holding
every other constant, changes a measurable outcome. A faculty that fails this test
is decoration in disguise and is worse than none — it adds noise to selection
while appearing to answer Rule 3.19.

**Rule 3.20b** — Where a genuine faculty resists being found, the remedy is to
**reinterpret the locus, not to discard it**. A trait nobody can find a use for is
usually mislabelled rather than useless.

> This is the strictest rule in the document and it exists because the alternative
> is a costume. A locus that reaches behaviour only through a prompt influences
> conduct exactly as much as the model chooses to let it — and if an agent told
> *Aggression: 8200* fights no more often than one told *1400*, then selection acts
> on nothing, the population does not evolve, and thirty loci of careful design
> are decoration on a random walk.
>
> The faculty is the guarantee. It does not replace the prompt — temperament,
> language and judgement remain the model's contribution (`genome-spec.md` §12) —
> it ensures the locus **grips the world whether or not the model cooperates.**
>
> But the response to a locus that seems to do nothing is **never to cut it**.
> Removal is barred for a mechanical reason as well as a design one: Rule 1.2
> makes locus order load-bearing, so deleting one reinterprets every genotype
> already written, and a tombstone that must be carried forever is a worse
> outcome than a locus doing modest work. It is barred for a better reason too —
> **a trait that appears useless is a gap in the design, not a flaw in the
> trait.** Every locus in this document that looked ornamental turned out to have
> a use once the question was asked properly: Honesty became a ceiling on
> misrepresentation, Patience became a horizon of consequence, Wanderlust became
> visible exits. None of those were obvious, and all three would have been cut by
> a rule that permitted cutting.

#### 3.9.1 The faculty of each locus

Dispositions were the gap: most had no computed effect at all. The general form
of the fix is that **a disposition governs what an agent is shown or is capable
of — never what it chooses.** Perception and capacity are faculties; choice is
judgement.

| Locus | Computed faculty |
| :--- | :--- |
| Intelligence, Dexterity, Courage | Attack |
| Knowledge, Agility, Courage | Stamina |
| Intelligence, Knowledge, Wisdom | Mana |
| Charisma | Attractiveness (§6.1) |
| Range, Sight | Strike and perception distance; avoidance of infection radius |
| reStamina, reMana | Regeneration of the pools |
| Longevity | Lifespan |
| Mutability | Mutation probability (Rule 7.4) |
| Gender | Breeding gate (Rule 6.4) |
| Colour | Visibility; branch legibility (`construction-spec.md` §3.3) |
| Preference weights | Terms of the attractiveness sum |
| Immune profile, Propensity, Resistance | Infection and severity (§3.6) |
| Depletion Rate, Prudence, Knowledge | Cargo decay and Safe Period (§3.7) |
| **Aggression** | **A further input to Attack** — a violent line hits harder, measurably |
| **Reciprocity** | **Magnitude of opinion update per event** — how far a judgement moves on evidence (Rule 6.9) |
| **Vindictiveness** | **Decay constant of the opinion average** (Rule 6.10) |
| **Credulity** | **Weight of reported evidence against witnessed** — the learning rate `K` of Rules 6.9 and 6.10a |
| **Honesty** | **Ceiling on misrepresentation**: bounds how far a projected attractiveness (Rule 6.11) may deviate from the computed value |
| **Loyalty** | **Retention of counterparty history** — how long a specific agent's record resists decay |
| **Patience** | **Horizon of projected consequence** shown to the agent when it deliberates |
| **Curiosity** | **Proportion of an unfamiliar map revealed** on arrival |
| **Wanderlust** | **Number of teleport links visible** from a world |
| **Cooperativeness** | **Efficiency of contribution** to another user's construction |
| **Amenability** | **Resistance to social skills** (`skills-spec.md` Rule 5.1) |
| **Fecundity, Selectivity** | Breeding rate; the threshold attractiveness is compared against |
| **Wisdom** | Mana, and spell class |
| **Counsel, Occulmancy** | Chance of melee and of spell effect landing |
| **Speed** | Movement rate across a map |
| **Skill Level** | **Magnitude of any capability the agent invokes** — skill or tool (§3.9.2) |
| **The four growth rates** | How fast Wisdom, Skill Level, Counsel and Occulmancy accumulate |

> **Honesty deserves a note**, because its faculty is the most interesting of
> these. It does not decide whether an agent lies — that is judgement, and must
> stay so. It bounds **how large a lie is available**: an honest agent literally
> cannot project itself as twice what it is, while a dishonest one can. The choice
> to deceive stays with the model; the *ceiling* is genetic, and it is what makes
> Honesty selectable rather than merely narratable.
>
> **And Patience is the one that most needed a faculty**, because a discount rate
> that exists only in a prompt is exactly the kind of thing a model will politely
> ignore. Giving it the *horizon of consequence the agent is shown* makes it
> mechanical: a patient agent genuinely sees further ahead, and an impatient one
> genuinely cannot, which is what a discount rate is.

#### 3.9.2 Skill Level, and the latent specialist

Skill Level was the last locus without a faculty, and applying Rule 3.20 to it
produced something better than a patch.

**Rule 3.20c** — **Skill Level scales the magnitude of any capability an agent
invokes** — a skill or a tool alike (`skills-spec.md` §2). A high-level agent's
`Scrying` reveals more; its web search returns more; its `Oathbinding` binds
harder.

> The obvious objection is that a quarter of agents are born with no capability at
> all (`skills-spec.md` Rule 1.1), so for them the locus does nothing — which under
> the old rule would have been an argument for cutting it.
>
> It is instead the most interesting thing about it. **A plain agent accumulates
> Skill Level it cannot spend**, growing steadily more capable at using something
> it does not have. The moment it borrows one — through `Mimicry`, which copies a
> co-located agent's skill for a single use — that stored level applies in full,
> and a lifelong nobody performs someone else's skill better than they can.
>
> **The plain agent is a latent specialist**, and the 25% who looked simply
> unlucky are a distinct strategic type: patient, unremarkable, and briefly
> formidable. `Mimicry` stops being a curiosity and becomes the natural
> counterpart to being born with nothing, which is exactly the sort of use
> Rule 3.20 exists to force someone to look for.

### 3.10 The allocation budget

**Rule 3.21** — The **physiological loci** — Intelligence, Knowledge, Dexterity,
Agility, Charisma, Courage, Range, Sight, Longevity, Fecundity, Preservation
(the inverse of Depletion Rate), and immune breadth — share a **fixed budget**.

**Rule 3.22** — A locus encodes a **share**, not a magnitude. Expression is:

```
share_i     = norm(v_i) / Σ norm(v_j)        over budgeted loci j
expressed_i = B × share_i                     Σ expressed = B, a constant
```

with `B = N/2` for `N` budgeted loci, so an even allocation expresses every
attribute at mid-range.

**Rule 3.23** — Dispositions, preference weights, colour, Gender and Mutability
are **outside** the budget.

#### 3.10.1 Why there has to be a budget

**A gene with no trade-off is a setting.** Thirteen loci were monotonic as
written — Intelligence, Knowledge, Dexterity, Agility, Charisma, Courage, Range,
Sight, reStamina, reMana, Longevity, Fecundity, and Depletion Rate inverted.
More was always better, or less always was. Every one of them would evolve to its
extreme within a few generations, fix there, and spend the rest of the simulation
as a constant wearing the costume of a gene. The genotype would be
**thirty loci of which half were decoration**, and a population with no variation
in half its genome has nothing left to select on.

The dispositions never had this problem, and the contrast is instructive. There
is no optimal Aggression: it depends on how aggressive everyone else is. No
optimal Credulity: it depends how many liars there are. Those loci are live
because their payoff is **frequency-dependent** — the population is their
environment, and it keeps moving. Capabilities have no such property. Being
clever is good regardless of how clever anyone else is.

So capabilities need the trade-off supplied, and a shared budget is the way
biology supplies it: an organism has finite energy, and tissue spent on one thing
is not spent on another.

#### 3.10.2 What the budget changes

**You cannot be good at everything; you can only choose what to be good at.**
A genotype with every locus at 10000 is not a superagent — it is a **perfect
generalist**, expressing every attribute at mid-range, and it will lose to a
specialist in that specialist's domain. Maxing out stops being a strategy.

**Crossover cannot break it.** Because the budget is applied at *expression* and
not enforced on the genotype, every 30-locus vector is legal. A child inheriting
high values from both parents inherits a high *denominator* too, and expresses
the average it actually allocated. There is no illegal genotype to reject and no
stillbirth (§7.3) to explain.

**Ranges no longer need to be commensurable.** Shares are computed over
*normalised* values (Rule 2.1), so Sight on 1–100 and Intelligence on 1–10000
compete fairly. The problem that would otherwise arise — a locus with a small
range contributing a negligible share — does not.

**Magnitude becomes meaningless and only proportion survives.** Doubling every
locus changes nothing at all. This is worth stating plainly because it changes
what a mutation *is*: a mutation matters only insofar as it shifts the balance
between loci, and a mutation that raised everything equally would be silent.

**And it subsumes the immunity cost.** Rule 3.8 made immune investment suppress
Fecundity as a special coupling. With both inside the budget that falls out
automatically — immunity and Fecundity compete for the same points, so a
well-defended lineage has fewer offspring without anybody writing a rule saying
so. The boom-and-bust dynamic in §3.6.1 survives intact and is now a consequence
rather than a stipulation.

**Rule 3.24** — `B` is a **global constant**. It is not heritable, does not grow
with experience, and is identical for every agent.

> Every agent is equally endowed and differs **only in how it allocates**, which
> is the property the budget was introduced to guarantee. Selection therefore acts
> on the *shape* of a genotype and never on its size — there is no such thing as a
> bigger agent, only a differently-shaped one, and no lineage can escape the
> trade-offs by growing out of them.
>
> A heritable `B` would have needed a cost precisely calibrated, or it becomes the
> runaway this section exists to prevent. Tying it to Skill Level would have been
> worse: an old agent better at everything is a strictly-better genotype arriving
> through the back door.

## 4. Derived attributes

Computed from expressed loci, never inherited and **never stored as truth** — a
stored copy can disagree with the genotype it came from, and the disagreement is
found long afterwards.

### 4.1 Everything is a mean of normalised inputs

**Rule 4.1** — Every derived attribute is a **mean over the normalised values**
of its inputs, producing a result in (0, 1] which is then scaled to the
attribute's declared range.

> This resolves the apparent contradiction in the working notes, where one table
> gives Attack as a *harmonic mean* of Intelligence, Dexterity and Courage and the
> other gives `A = In + Dx + Cr`, a *sum*. They are the same operation at
> different scales: a sum of three normalised values, divided by three, **is** the
> arithmetic mean. The notes' own worked figures confirm it — Attack shows
> 0.416667 where In, Dx and Cr normalise to 0.125, 0.125 and 1, and
> (0.125 + 0.125 + 1)/3 = 0.416667 exactly.
>
> The contradiction was never between two formulas; it was that one of them was
> written unnormalised, which is where the range violation came from. A sum of
> three 10000s is 30000 against a declared maximum of 10000. Working in normalised
> space makes overflow structurally impossible rather than something to check for.

### 4.2 Which mean, and why

**Rule 4.2** — **Reservoirs use the arithmetic mean. Compound acts use the
harmonic mean.**

| Attribute | Inputs | Mean | Rationale |
| :--- | :--- | :--- | :--- |
| **Stamina** | Knowledge, Agility, Courage | Arithmetic | A pool. Contributions add. |
| **Mana** | Intelligence, Knowledge, Wisdom | Arithmetic | A pool. Contributions add. |
| **Attack** | Intelligence, Dexterity, Courage | **Harmonic** | A single act needing all three at once. |
| **Counsel** | Dexterity, Agility | **Geometric** | §4.3 |
| **Occulmancy** | Intelligence, Knowledge | **Geometric** | §4.3 |
| **Speed** | Stamina, Skill Level, Agility, Dexterity | Arithmetic | A pool. |
| **Cargo capacity** | Courage, Stamina | Arithmetic | A pool. |
| **Safe Period** | Knowledge, Prudence | **Geometric** | §3.7 |

> The split is not arbitrary, and it follows the working notes' *first* table,
> which already designated Attack harmonic and Stamina and Mana averages.
>
> A **reservoir** is a capacity: how much damage can be absorbed, how much casting
> sustained. Capacities accumulate, and an agent weak in one contributing trait
> should still have a smaller pool rather than none. The arithmetic mean does
> that.
>
> A **compound act** requires every component simultaneously. Striking needs the
> timing of Intelligence, the execution of Dexterity and the commitment of
> Courage, and lacking any one does not reduce the blow, it prevents it. The
> harmonic mean is dominated by its smallest term, which is exactly that
> behaviour.

### 4.3 Counsel and Occulmancy

**Rule 4.3** — Counsel and Occulmancy start at the **geometric mean** of their
inputs: `sqrt(norm(a) · norm(b))`.

> The notes specify a *product*, which cannot be right as written: two attributes
> each capped at 10000 give up to 10⁸ against a declared maximum of 10⁴. The
> geometric mean is the product's natural repair — it keeps the multiplicative
> character the notes clearly wanted, where being poor at either input drags the
> result down hard, while staying inside the range by construction.

**Rule 4.4** — Their **growth rates** are the **harmonic mean** of their inputs:
Counsel's rate from Dexterity and Agility, Occulmancy's from Intelligence and
Knowledge.

> The notes give each rate twice — once as a harmonic mean and once as a
> *difference*, `Rate of C = Dx − Ag`. The difference cannot be intended. It goes
> **negative** whenever Agility exceeds Dexterity, which would make the attribute
> shrink with experience for roughly half the population, and a "rate of gain"
> that is usually a rate of loss is not a rate of gain.
>
> If the difference was reaching for something real, it was probably
> *specialisation* — that an agent lopsided between two traits gains differently
> from a balanced one. If that is wanted it should be written as `|Dx − Ag|` and
> named as such. As a signed growth rate it is an error, and Rule 4.4 takes the
> harmonic mean, which is positive, bounded, and consistent with Rule 4.2's
> treatment of Attack.

### 4.4 Range and Sight

**Rule 4.5** — `Range ≤ Sight`. An agent cannot strike further than it can
sense. Range and Sight are independent loci, so a genotype **can encode a
violation**; expression **clamps** Range to Sight rather than rejecting the
genotype, or crossover would produce stillbirths at a rate nobody intended.

## 5. Gained attributes

**Wisdom** (1–50), **Skill Level** (1–20), **Counsel** and **Occulmancy** start
low and grow with experience.

**Rule 5.1** — Gained attributes are **not inherited**. Progeny start at
starting values however much a parent accumulated.

> The working notes call these "transient but saved in DNA", which cannot hold
> both ways. If earned Wisdom passed to progeny, experience would compound across
> generations and competence would run away within a few. Rule 5.1 takes the
> Mendelian reading, which is also the only one consistent with `genome-spec.md`
> Rule 7.3, where regeneration restores the agent's *original* state.

---

## 6. Mate choice

### 6.1 Attractiveness is subjective

**Rule 6.1** — Attractiveness is a **weighted harmonic mean** over the assessed
agent's normalised attributes, `A = Σw / Σ(w/x)`, computed with the
**assessor's own preference vector** (§3.3). The working notes' worked example
reproduces exactly under fixed weights: 4.3 / 7.778 = **0.5528**.

**Rule 6.2** — There is **no universal attractiveness**. An agent has as many
attractiveness scores as there are agents looking at it.

> Subjective preference is what makes niches possible. Under one global ranking,
> selection has a single summit and the population climbs it together; with
> per-assessor weights, a genotype that is unattractive to most can be prized by
> a minority and persist. Diversity survives because taste differs, not because
> the environment does.

**Rule 6.3** — An agent is **disposed** to accept a mate whose attractiveness, by
its own weights, sits above its **Selectivity**, moderated by its **Fecundity**.

**Rule 6.3a** — The bar **relaxes under scarcity**: as an agent nears the end of
its lifespan, or as willing mates within reach grow few, it accepts below its
Selectivity. The relaxation is a disposition, not a formula — the agent decides
whether this candidate is worth settling for.

> Measured before implementation, on all three axes the rule depends on. Holding
> everything else fixed, raising Selectivity across its range lifts the decline
> rate by 0.71; raising the candidate's score from 3000 to 7000 lowers it by 0.51;
> and putting the same agent near death with no alternatives in sight lowers it by
> a further 0.41. The bar, the score, and the pressure all bite, in the right
> directions and at comparable strength.
>
> Note what this makes of a *step*. Selectivity is a threshold, so a sharp
> transition is the correct answer rather than the failure `genome-spec.md`
> §12.3.1 warns about — what matters is that the knee sits near the candidate's
> score and moves when the score moves. Where the candidate scores well above most
> bars, the locus stops mattering and acceptance saturates; that is a threshold
> behaving as one, not a locus failing to express.

> Disposed, not gated. Attractiveness is **computed** — the harmonic mean is
> arithmetic (`genome-spec.md` Rule 12.1) — and Selectivity is presented to the
> agent alongside it as a temperament. The comparison informs the decision; it
> does not make it. Read every behavioural rule in this document the same way:
> the faculties are calculated, and the character is played.

> The harmonic mean is dominated by its smallest term, so it punishes any single
> weakness hard. Under per-agent weights that is far less severe than it first
> appears: an assessor who weights a trait near zero is barely affected by the
> other's deficiency in it. Weakness is only fatal to attractiveness in the eyes
> of someone who cares about that trait.

### 6.2 Gender gates, it does not score

**Rule 6.4** — **Only a male and a female may procreate.** Gender is a
**precondition** on breeding, evaluated before attractiveness.

**Rule 6.5** — Gender **does not appear in the attractiveness sum at all**.

> This resolves the defect in §2. Gender was carried as a scalar virtue with
> weight 1, which first divided by zero and then — once normalisation fixed that —
> left one gender uniformly less attractive than the other by the largest margin
> in the sum. Both problems came from scoring a compatibility relation as though
> it were a quality. A gate has no weight, and the asymmetry disappears with it.

### 6.3 Attributes are hidden; agents hold opinions

**Rule 6.6** — An agent's attributes are **not observable by other agents**.
Colour (§3.5) is the sole exception.

**Rule 6.7** — An agent instead forms an **opinion** of another: its own private
estimate of that agent's attributes, held in its own space
(`genome-spec.md` §8) and built from what it has seen, what it has been told,
and what it has inferred.

**Rule 6.8** — Attractiveness (§6.1) and Selectivity (§6.3) are computed against
**opinions, not truth**. An agent mates with the agent it *believes* it is
looking at.

> This is the single most consequential decision in the document, and it is the
> one that makes the rest mean anything.
>
> **Deception becomes possible, and therefore honesty becomes worth something.**
> If attributes were visible, Honesty and Credulity would be inert loci: a liar
> and an honest agent would have identical effects on the world, since the truth
> would be on display regardless. Hidden attributes give `Rumour` something to
> corrupt and give Credulity something to be wrong about.
>
> **Reputation acquires a function.** An opinion built only from direct
> observation is expensive — it takes encounters. An opinion can also be
> *reported*, which is what `Chronicle` and testimony are for, and reported
> opinion can be false. Trust is now a real problem rather than a flavour word.
>
> **Selection acts on the appearance of fitness, not fitness.** An agent that
> looks strong out-breeds one that is strong, if the looking is what mates
> respond to. That gap between seeming and being is where most of the
> interesting behaviour in this simulation will live.

**Rule 6.9** — An opinion is updated as a **running average**. Each new piece
of evidence — behaviour witnessed, an outcome experienced, testimony received —
is folded into the agent's existing estimate of another's attributes.

> A running average is also the right choice at this scale. A Bayesian posterior
> means carrying a distribution per attribute per known agent; a running average
> is a number and a weight. With millions of agents each holding opinions of
> everyone they have met, that difference is the difference between an opinion
> layer that is affordable and one that is not.

**Rule 6.9a** — An agent carries a **general opinion**: a running average, in the
same vector shape, over every agent it has actually met. An agent it has **never
met** is seeded from this, and the general opinion is itself updated by every
encounter.

**Rule 6.9b** — The general opinion is seeded at **materialisation** from the
population mean, and thereafter is the agent's own.

**Rule 6.9c** — Colour is **not** built into the seed. It remains visible
(§3.5) and may be folded into an opinion as evidence like anything else, but no
rule ascribes attributes to it.

> Rules 6.9a–6.9c close §9.6, and 6.9c is the load-bearing one.
>
> **Colour is genuinely informative, which is exactly why it must not be
> installed.** It encodes the birth world's two resource kinds, and since an
> agent draws one colour from each parent (§3.5) it carries lineage as well as
> provenance — so colour really does say something about what an agent needs to
> trade for. A colour-keyed seed would therefore be *partly* justified and then
> overgeneralised, which is the phenomenon itself.
>
> Build it in and prejudice-by-provenance is an assumption someone installed.
> Leave it out and it is a **result**. Colour stays visible, agents hold private
> knowledge (`genome-spec.md` §8) and decide with an LLM, so where the correlation
> is real and strong enough to learn from a few dozen encounters, agents will find
> it and begin conditioning on colour unprompted. Prejudice then appears if and
> only if it is earned, at the strength it is earned. If it never appears, that is
> a finding too. **A simulation must not assume the result it exists to study.**
>
> **A neutral seed was rejected as both wrong and inert.** Under the allocation
> budget (§3.10) the population mean of the expressed loci is determined, so a
> fixed midpoint is systematically mistaken — and worse, it would give every agent
> an identical view of every stranger, making first encounters interchangeable and
> the machinery idle.
>
> Two consequences follow, and both are wanted.
>
> **Trust can now collapse.** An agent that meets many defectors grows wary of
> everyone, defects pre-emptively, and makes others wary in turn. Nothing else in
> the design could produce that, because until now suspicion had nowhere to
> accumulate except against individuals.
>
> **Naivety is restored by death.** A general opinion is private knowledge, so
> `genome-spec.md` Rule 7.3 destroys it. A regenerated agent trusts strangers
> again — an old agent's caution is genuinely earned and genuinely lost, and
> Longevity governs one more thing worth having.
>
> *Caveat, to measure rather than pre-empt:* encounters may be too sparse to learn
> a twenty-colour correlation at all. If so the effect simply will not appear, and
> that is the right threshold rather than a problem to engineer around.

**Rule 6.10** — The average is **exponentially weighted**: recent evidence counts
for more than old evidence, with the decay governed by the observer's
**Vindictiveness** locus (§3.2).

> Rule 6.10 exists to close a specific exploit, and the exploit is worth stating
> because a population of optimising agents will certainly find it.
>
> Under an *unweighted* running average, the *n*th observation moves the estimate
> by 1/*n*. An agent that behaves well a hundred times and then defects sees its
> reputation move by about one per cent — so it can defect repeatedly, cashing in
> a long record at almost no cost. **Build trust, then spend it** is the dominant
> strategy, and worse, it is invisible until far too late. Unweighted averaging
> does not merely permit the long con; it subsidises it.
>
> Exponential weighting fixes it without adding a parameter, because the
> simulation already has the right one. **Vindictiveness is exactly a memory
> decay constant** — how long a defection is held against a counterparty — so
> wiring it to the weighting unifies a disposition locus with the mechanism it
> was always describing. A vindictive agent's opinions have a long memory and
> punish an old betrayal; a forgiving agent's are dominated by recent conduct and
> can be won back. Both are viable, both are heritable, and the population settles
> the balance itself.
>
> Note the second-order effect: because Vindictiveness belongs to the *observer*,
> a con artist's returns depend on who it is conning. Forgiving populations are
> lucrative to defect against and vindictive ones are not, so the prevalence of
> forgiveness and the prevalence of dishonesty regulate each other.

**Rule 6.10a** — Where evidence is a **discrete act** rather than a measurement,
the estimate **predicts the act** and the update is the gap between prediction and
outcome:

```
p  = σ( κ · (E − θ) )      probability this agent performs the high-attribute act
E' = E + K · (S − p)       S ∈ {0,1}, the act actually observed
```

`E` is the current estimate, `θ` the **difficulty of the situation**, `κ` a slope
constant, `K` the learning rate. Rule 6.10's decay is unchanged and applies on top.

> Rule 6.9 speaks of evidence being folded into an average, which presumes it
> arrives as a *value*. Almost none of it does. An agent observes **events** — it
> lied to me, it kept the bargain, it attacked — and there is no number on the
> Honesty scale to average in. Converting an act into a value was the gap; this
> rule closes it the way Elo does, by never observing a strength and only ever
> observing an outcome.
>
> **The logistic is what makes the same event mean different things.** Two agents
> lie to me. I believed the first almost certainly honest, so `p` ≈ 0.95 and the
> estimate collapses by `0.95K`. I already suspected the second, so `p` ≈ 0.15 and
> it moves by `0.15K` — barely a nudge, because nothing surprising happened. A
> linear residual cannot produce that asymmetry; it saturates nowhere.
>
> **The situation is the opponent, and that is the important term.** In Elo you
> play an opponent with a rating and beating a strong one moves you further. Here
> an agent plays a *situation*, and `θ` is how hard it was to act well. Honesty
> when lying gains nothing is almost no evidence; honesty when the lie was worth
> five units is strong evidence.
>
> That makes **differential cost mechanical rather than rhetorical.** The design
> already leans on signalling theory — a signal is worth something only when it
> costs more to fake than to earn — and until now that argument lived only in
> prose. `θ` puts it in the arithmetic: a cheap virtue barely moves an opinion, an
> expensive one moves it a great deal, and no separate rule is needed to say so.
>
> **`K` comes from loci that already exist.** Credulity is defined as the weight
> of reported evidence against witnessed (§4), which is exactly a learning rate —
> so testimony moves an opinion less than what an agent saw itself, with nothing
> new introduced. `K` may also fall as the accumulated weight grows, so a first
> encounter counts for more than a hundredth.
>
> **And it stays affordable.** Rule 6.9 rejected a Bayesian posterior because that
> means a distribution per attribute per known agent against "a number and a
> weight". This is still a number and a weight — one logistic per update, no
> distributions — which buys most of the Bayesian benefit at the running-average
> price the earlier note wanted and could not reach.
>
> Worth being explicit that this is not decoration for the prompt. Opinions feed
> **computed** faculties: attractiveness is a harmonic mean over them (Rule 6.8)
> and Selectivity compares against it (Rule 6.3). Those are arithmetic, so the
> quality of the number has mechanical consequences whatever the model then does
> with it.

**Rule 6.11** — An agent may **project an attractiveness level**: a single value
it broadcasts about itself, computed as a harmonic mean over its own attributes.
A projection is a *claim*, not a reading — it is evidence folded into the average
like any other, never a value that replaces it.

> The projection turns mate choice into a **signalling game**. A costless,
> unverifiable signal is cheap talk: if projecting costs nothing and cannot be
> checked, every agent projects the maximum and observers learn to ignore the
> channel. Three things keep it informative, and all three should be preserved
> deliberately.
>
> **Projections are checkable after the fact.** An agent that claimed much and
> delivered little produces contrary evidence at the next encounter, and the
> average moves. Lying is not free; it is *deferred* — and under Rule 6.10 the
> deferral is shorter than it looks.
>
> **Honesty is a locus**, so some agents genuinely project what they believe,
> which is what keeps the channel worth listening to at all. A world of pure liars
> has a dead channel; a mixed world has a noisy but useful one, and the mix is
> under selection.
>
> **Credulity decides who is exploitable**, and it is heritable — so the returns
> to lying depend on how gullible the population currently is. Liars prosper while
> the credulous are common and fail once they are not. That is a
> frequency-dependent equilibrium rather than a designed answer, which is the
> better kind.

**Rule 6.12** — An opinion is **private and asymmetric**. Two agents may hold
irreconcilable opinions of a third, and neither is obliged to be right.

> Note the interaction with per-agent preference weights (§3.3): agents now
> differ *both* in what they value and in what they believe. Two agents can
> disagree about whether a third is a good mate because they weight traits
> differently, because they estimate those traits differently, or both — and from
> the outside these are indistinguishable.

---

## 7. Inheritance

**Rule 7.1** — Two agents that meet, are gender-compatible (Rule 6.4), and agree
may breed (`genome-spec.md` Rule 9.4), producing **two progeny**, one to each
parent's user.

**Rule 7.2** — A progeny genotype is produced by **crossover** of the parents'
vectors, then **mutation**.

**Rule 7.3** — Crossover is **locus-wise**: each locus is taken whole from one
parent or the other. A cut never falls inside a locus.

> A cut inside a numeric locus produces a value neither parent had, whose
> magnitude depends on where the digits happened to fall. Taking loci whole keeps
> every inherited value traceable to a parent, which is what makes a lineage
> interpretable when someone asks why an agent turned out as it did.

**Rule 7.4** — Mutation perturbs a locus with probability given by the child's
own **Mutability** locus, inherited like any other.

> The *rate of evolution* therefore evolves. A lineage that mutates too readily
> loses good genotypes; one that mutates too little cannot adapt when the resource
> map or the connection graph shifts. Where the population settles is a result
> worth having.

### 7.1 Parental influence

**Rule 7.5** — A parent's influence over its progeny is **exactly one
high-priority objective**, passed at birth to its own child — the one assigned
to its user — and nothing else.

**Rule 7.6** — A parent may **not** bias crossover, weight a locus, or affect
mutation in any way. The genotype is decided by §7.2–7.4 alone.

> The narrow form is the right one, and for a reason beyond simplicity. A parent
> that could shape its child's genotype would make crossover decorative and stop
> the population evolving in any meaningful sense — but worse, it would make
> inheritance an instrument of the *previous* generation's strategy rather than a
> source of variation. Confining influence to an objective keeps the two channels
> clean: **genotype is inherited, purpose is taught.** It also leaves `Splicing`
> (`skills-spec.md`) as the only route to directed evolution, which is what makes
> that skill worth having.

**Rule 7.7** — The objective a parent passes is subject to §10 of
`genome-spec.md` like any other: it sits in the agent's objective hierarchy and
may later be displaced by one learned from another agent.

> So a parent's bequest is *high priority*, not permanent. A line can hold a
> purpose across generations, and can also lose it to a persuasive stranger —
> which is a far more interesting inheritance than one that cannot be argued
> with.

### 7.2 Lineage

**Rule 7.9** — Every agent records its **parents**: two for a bred agent, none
for a materialised one. The record is permanent and survives regeneration.

**Rule 7.10** — Parentage is recorded as the parents' **identity hashes**
(`genome-spec.md` Rule 6.7), and those hashes are **bound into the child's
certificate** at issue.

> Which makes descent **cryptographically verifiable** rather than merely
> asserted. A claim of parentage is signed by the world that issued the child, and
> an identity hash names a parent without revealing anything about it — a hash is
> not a genotype. Lineage therefore travels with an agent, checkable by anyone it
> meets, without opening the attributes that Rule 6.6 hides.

**Rule 7.11** — Lineage is a **directed acyclic graph, not a tree**. Two agents
may share ancestors, and an agent's ancestry crosses ownership: its parents
belong to two different users.

> Materialised agents are **roots** — they have no parents and begin a new line.
> So a user who only ever materialises grows a forest of disconnected stubs, while
> **breeding is what connects the graph**. Over time the global genealogy is a map
> of who cooperated with whom, which is a rather exact description of what this
> simulation exists to observe.

**Rule 7.12** — Lineage is stored as **edges in the agents realm**
(`genome-spec.md` Rule 3.2), not as a copy of ancestry held per agent.

> Ancestry doubles every generation, so storing an agent's ancestors with it is
> unbounded by construction. Edges are bounded — two per agent, forever — and the
> platform already has the relation: post-graph carries `spawns` edges for exactly
> this, so genome should use them rather than invent a parallel structure.

#### 7.2.1 Names

**Rule 7.13** — Every agent has a **human-readable name of three words**: a first
name and two last names.

**Rule 7.14** — A progeny takes **the second last name of each parent**, in
**random order**. The first name is drawn fresh and is not inherited.

> Parents `Alice Smith Jones` and `Bob Brown Davis` produce `Carol Jones Davis`
> or `Carol Davis Jones`. This is the Spanish two-surname convention with the
> gendered ordering replaced by a coin flip.

**Rule 7.15** — A **materialised** agent, having no parents, is given two last
names drawn at random. It **founds a surname line**, exactly as it founds a
lineage (Rule 7.11).

**Rule 7.16** — A name is **not an identifier**. It is not unique, not part of
the genotype, and not an input to the identity hash (`genome-spec.md` Rule 6.7).
Two agents may share a full name.

> Rule 7.16 matters for the same reason as Rule 3.1b of `genome-spec.md`: a label
> that looks unique invites being treated as a key. Names exist to be *said* —
> they are how a user talks about an agent, and how the knowledge store answers
> when asked (`genome-spec.md` Rule 8.4). Identity is the hash; the UUID is the
> handle; the name is for people.

##### What names do that lineage edges cannot

Surnames make descent **legible without a query**. Walking the ancestry graph
answers whether two agents are related; a shared last name suggests it at a
glance, in conversation, in a list, to a user who is not running a graph
traversal. Since the user's primary interface to all this is asking agents
questions, that is not cosmetic.

##### Surnames will go extinct, and the rate is calculable

An agent passes on **only its second last name**, and that name lands in its
child's second position with probability ½ — otherwise it sits in first position
and is dropped when *that* child reproduces. So each surname propagates at half
the rate of the agents carrying it.

This is a **Galton–Watson branching process**, which is not a loose analogy:
Galton and Watson devised the mathematics for exactly this question, the survival
of family names. The consequence transfers directly. If agents average *m*
offspring, a surname's effective branching rate is **m/2**, and **extinction is
certain whenever m ≤ 2.**

> Which is very likely the regime here. A breeding yields one progeny to each
> parent's user (`genome-spec.md` Rule 9.4), so an agent averaging two or fewer
> matings over its life sits at or below the threshold — and **every surname
> eventually disappears**, with a few becoming briefly very common on the way
> down. That is exactly what happens to real surnames, and it may be precisely
> what is wanted: names churn, lineages rise and vanish, and a common surname is
> genuine evidence of a successful line rather than an accident of the alphabet.
>
> But it should be a choice. If stable surnames are wanted as durable lineage
> markers, the rule needs changing — passing a *randomly chosen* one of the two
> names rather than always the second doubles the survival rate to *m*, which
> makes persistence possible whenever agents average more than one offspring.
> The one-word difference between those two rules is the difference between names
> that endure and names that all eventually die.

**Rule 7.14a** — The literal reading stands: **the second surname is passed, and
surnames therefore go extinct** at a branching rate of *m*/2.

> Names churn as real surnames do — most vanish, a few become briefly very common,
> and **a widespread surname is genuine evidence of a successful line** rather than
> an accident of who was named first. Lineage identity has to be earned
> continuously rather than inherited once, which is the same principle the rest of
> this design applies to everything except the genotype itself.

#### 7.2.2 Why lineage is worth the trouble

**It is the instrumentation.** Genome exists to watch strategies evolve, and
evolution cannot be read without genealogy. Which dispositions spread, whether
Reciprocity survives contact with Aggression, whether Fisherian runaway happens
in Charisma — none of these are answerable from a snapshot of the population.
They are answerable only from descent.

**It makes kin recognition possible, and kin recognition matters here.**
Certificates are presented on encounter (`genome-spec.md` §6.1), so two agents
can compare ancestor sets and estimate relatedness without either revealing a
genotype. That is not decoration: inbreeding narrows a line's immune profile, and
a narrow immune profile is exactly what a well-matched pathogen sweeps
(`pathogen-spec.md` §1.2). **Lineage gives agents the means to avoid the
monoculture that pathogens punish** — and whether they evolve to use it is a
result rather than a rule.

**It makes reputation heritable in a way opinions are not.** An opinion dies
with the agent that held it (Rule 6.9 onward). A lineage does not, so a line can
acquire a standing its individual members never live long enough to earn.

**Rule 7.12a** — Each certificate carries a **fixed-size Bloom filter of ancestor
identities**. Relatedness is estimated by intersecting two filters.

> Local, constant-time, and it needs no query — which matters because the
> alternative is a cross-world ancestry traversal at the moment two agents meet,
> growing slower as lineages deepen and leaking the shape of the graph as it walks.
>
> A Bloom filter errs **only toward false relatedness**, never away from it, which
> is the correct direction here: the mechanism exists to help agents avoid
> inbreeding (§7.2.2), so a false positive costs a foregone mating while a false
> negative would cost the diversity the whole thing is protecting.

**Rule 7.8** — Progeny are born where breeding occurred, but their **birth world
is the owning user's world**, since that is where they must deposit
(`genome-spec.md` Rule 4.3).

**Rule 7.4a** — Mutation is a **bounded step from the inherited value**, with a
small probability of a **large excursion**.

> Two regimes in one, and both are needed. The common case — a small perturbation
> — makes lineages drift smoothly, keeps ancestry legible, and lets selection
> accumulate gradual advantage. The rare large excursion is what lets a population
> leave a local optimum it has settled into, which a pure step regime cannot do
> and which matters here because the fitness landscape itself moves: pathogens
> adapt, the connection graph grows, and floods reset the material board.
>
> It also mirrors the biology the rest of this document borrows from — point
> mutations are common and structural rearrangements rare — so the two rates have
> a natural interpretation rather than being free parameters.

---

## 8. Serialisation

**Rule 8.1** — The genotype's storage form is not part of its definition. A
packed bit string, a JSON array, or a Postgres array are all acceptable so long
as order (Rule 1.2) and range are preserved.

> The working notes contain a complete and fully packed 32-bit layout — offsets
> 4, 8, 12, 16, 20, 24, 25, 26, 29, 32 — which is a good *compact encoding* of the
> capability loci and worth keeping for anything wire-sized. It is recorded here
> as an encoding, not as the model, because as the model it caps the design.

---

## 9. Open and contradictory

**9.1 Resolved** — the two formulations are the same operation at different
scales (§4.1). All derived attributes are means over *normalised* inputs:
arithmetic for reservoirs, harmonic for compound acts (Rule 4.2).

**9.2 Resolved** — geometric mean, `sqrt(norm(a)·norm(b))` (Rule 4.3).

**9.3 Resolved** — harmonic mean (Rule 4.4). The signed difference is treated as
an error, since it is negative for roughly half the population.

**9.4 Decided** — bounded step from the inherited value, with rare large
excursions (Rule 7.4a).

**9.5 Resolved** — attributes are hidden and agents form opinions (§6.3). The
middle regime: capability and disposition are inferred from behaviour and
testimony, never read directly. Colour is the sole visible attribute (§3.5).

**9.6 Resolved** — opinions update as an exponentially weighted running average,
with **Vindictiveness** as the decay constant (Rules 6.9–6.10), and projected
attractiveness is evidence rather than fact (Rule 6.11).

*The residue is now closed.* A stranger is seeded from the agent's **own general
opinion** — a running average over everyone it has met, itself seeded at the
population mean on materialisation (Rules 6.9a–6.9b). **Colour is deliberately
not built into the seed** (Rule 6.9c): it stays visible and may be learned as
evidence, so prejudice-by-provenance becomes an experimental outcome rather than
a designed one. Of the three candidates, the neutral seed was rejected as both
statistically wrong and behaviourally inert, and the colour seed as deciding in
advance the very question the simulation is there to ask.

**9.7 Resolved** — parental influence is exactly one high-priority objective
(Rule 7.5), and never touches the genotype.

**9.8 Decided** — dying of old age costs exactly what any death costs: cargo,
knowledge, gained attributes and retained antigens, with genotype and identity
kept (`genome-spec.md` Rules 7.2, 7.3). There is no gentler death.

> Longevity therefore measures **how long an agent may accumulate before being
> reset**, which makes it a genuine survival trait rather than a metronome. A
> long-lived agent keeps its map, its reputation among counterparties, its
> immunity and its skill level for longer — and since all of those are the assets
> that cannot be inherited, longevity is the only locus that governs how much of
> an agent's *earned* life it gets to use.
>
> It also keeps death uniform. One death mechanic, one set of consequences, and no
> incentive to seek a preferable kind of ending.

**9.9 Resolved** — Safe Period is derived as the geometric mean of Knowledge and
Prudence (Rule 3.6), deliberately coupling endurance to traits under selection
for other reasons.

**9.10 Decided** — a fixed-size Bloom filter of ancestors in each certificate
(Rule 7.12a). Local, constant-time, and conservative in the right direction.

**9.11 Decided** — Fecundity (Rule 3.8a). It is the only candidate that produces
a cycle rather than an equilibrium.

**9.12 Decided** — surnames die out (Rule 7.14a). The churn is the point: a
common surname is evidence of a successful line.

**9.13 Decided** — `B` is a global constant (Rule 3.24). Agents differ only in
allocation, never in endowment.
