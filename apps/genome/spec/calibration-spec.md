# Genome — calibration

**Status: draft.** Every quantity the simulation needs, in one place because they
interlock and cannot be tuned apart. Rules elsewhere say *what* happens;
this says *how much* and *how fast*.

Where a number appears both here and in another document, the other document is
authoritative and this one records it for comparison.

## 1. Time and distance

**Rule 1.1** — A **day is a real day** (`system-spec.md` Rule 2.1).

**Rule 1.2** — Crossing a world edge to edge takes approximately **six hours**.
Map coordinates are a unit square and agent speed is expressed against it.

**Rule 1.3** — Passage through a portal is **instantaneous**
(`genome-spec.md` Rule 6.1a), so a *hop* costs only the intra-world travel at
each end.

> Six hours is calibrated against the one constraint the specification already
> states. `construction-spec.md` §4.2 says a two-day countdown is "enough to bring
> nearby agents home or send them out, and not enough to recall one that is four
> hops away" — and at six hours a crossing, four hops is a day or more of travel
> before any decision time. The countdown behaves as described rather than as
> hoped.
>
> It also fits the rest. An agent makes a few legs a day, which matches the
> five-decision routine day in `execution-spec.md` §5.2, and a journey is long
> enough that cargo decay (`genome-spec.md` Rule 4.18) is a real cost rather than
> a rounding error. At one hour a crossing the countdown would recall everybody
> and the flood would stop being a deadline; at twenty-four an agent would manage
> less than a leg a day and watching a world would show nothing happening.

## 2. Set elsewhere, recorded here

| Quantity | Value | Source |
| :--- | :--- | :--- |
| Flood interval | 15–30 days, undisclosed | `construction-spec.md` 4.7 |
| Flood warning | 2 days | 4.8 |
| Ark capacity | 12 slots | 4.3b |
| Materialisation cost | 2 units × 4 kinds = 8 | `genome-spec.md` 2.1 |
| Breeding cost | 2 units × 4 kinds, held collectively | 9.4 |
| Cargo ceiling | 15 units | 4.16 |
| User ceiling | 25 units per kind | 4.15 |
| World ceiling | 250 units per kind | 4.13 |
| Kinds per world | 2 of 20 | 2.2 |
| Opening portals | 30 | 6.2a |
| Decision budget | 10/day, capacity 12 | `execution-spec.md` 5.2 |
| Negotiation cap | 6 turns | 7.2 |
| Model screen bar | 1.5× | 10.6 |
| Pathogen signature | 8–16 dimensions | `pathogen-spec.md` 2.0 |
| Capability roll | 75% | `skills-spec.md` 1.1a |

## 3. Life history

**Rule 3.0** — **Longevity maps to 20–90 real days**: locus 0 → 20 days,
locus 10000 → 90, linear between.

> Spanning one to four flood cycles is the property that matters. An agent
> typically outlives a flood, so an Ark berth preserves knowledge that would
> otherwise have persisted — which is what makes saving it worth bargaining over.
> A stranded first agent self-corrects in weeks (`genome-spec.md` §11.2). The cost
> is accepted openly: roughly 6–10 generations a year, so evolution is read as a
> trend rather than watched as a spectacle.

**Rule 3.0a** — The **ordinary mutation step is ~5% of a locus range**, with
Rule 7.4a's rare large excursions on top.

> Chosen coarse and fast, against the recommendation, and the reasoning is
> recorded. At 6–10 generations a year a fine step would make evolution
> imperceptible for years; 5% makes drift visible within a few generations. The
> risk is that offspring land far from parents and selection loses what it found —
> but two things blunt it. Mutability is itself a locus (`genotype-spec.md` §3.4),
> so lineages that suffer from coarse mutation can evolve it down: **the step size
> is a starting condition, not a constant.** And crossover recombines without
> mutating, so a good combination can still propagate intact between excursions.
> If the population wanders rather than adapts, Mutability's own trajectory will
> show it — falling Mutability is the population voting the step down.

**Rule 3.0b** — **Attrition at mid-range exhausts an agent in ~15 victories**:
locus 5000 costs ~6.7% of maximum Stamina per win, scaled linearly by the locus.

> A raiding career with a visible end. Against Maturation's rise a fighter
> sustains a run and then must stop, so predator and producer coexist and their
> balance stays frequency-dependent — rather than the strongest simply winning
> until checked by nothing.

**Rule 3.0c** — A world's **two kinds are a uniformly random pair** of the 190.

> Scarcity is emergent and mobile: a kind can be globally rare this month and
> common next as users join, and nobody — including the designers — decides what
> is valuable. A balanced allocator would have been fairer and would have removed
> exactly that property.

**Rule 3.0d** — A world holds **6–10 piles per kind**, placed uniformly at random
with a **minimum spacing**, capacities drawn **15–50** and summing near the
250-unit ceiling.

> Enough piles that agents spread out and routes differ; few enough that a good
> pile is worth remembering, which is what gives Cartography and Prospecting their
> value. Minimum spacing keeps a world from being one lucky corner.

**Rule 3.0e** — A **founder draws two fresh surnames** from the name pool, and
becomes the root of a lineage. Every surname in the population traces to some
founder.

**Rule 3.0f** — The flood countdown is a **promise, not a clock reading**: the
flood fires **two full days after the countdown actually became visible**. An
infrastructure delay shifts the flood; it never shortens the warning.

> Agents should lose to the game, never to an outage. Rule 4.8's two days is the
> basis of every evacuation and boarding decision in `construction-spec.md` §4.2,
> and a warning that could silently shrink would make those decisions gambles on
> the platform rather than on the world.

## 3.1 Founding

**Rule 3.1** — A founder's genotype is drawn **uniformly within its world, about a
centre drawn uniformly for that world**, and the centre is **recorded**
(`genotype-spec.md` Rules 3.2a, 3.2b).

## 4. Still open

Nothing below is set, and each blocks the phase named. Recorded so they are
chosen deliberately rather than defaulted into by whoever writes the code first.

| Quantity | Blocks | Note |
| :--- | :--- | :--- |
| **Pile regeneration rate range** | Phase 1.1 | Rule 4.6 assigns each pile its own; the range is unset |
| **Base collection rate** | Phase 1.1 | A Toolhouse improves it, so a base exists |
| **Cargo decay rate** | Phase 1.1 | Rule 4.18 decays carried cargo; the rate governs how far an agent can usefully range |
| **Infection distance range** | Phase 9 | `pathogen-spec.md` 2.4 gives strains a radius; the range is unset |
| **Immune Vigilance mapping** | Phase 9 | Locus to detection delay and to the Stamina-regeneration price (`genotype-spec.md` 3.8e) |
| **Synthesis Speed mapping** | Phase 9 | Locus to antigen produced per interval (2.18a) |
| **Coverage threshold** | Phase 9 | How much combined coverage counters an infection (2.18c) |
| **Antigen decay rate range** | Phase 9 | Set at synthesis from the maker's genotype (2.18d) |
| **Inoculist bank size** | Phase 9 | Rule 2.20a says small and bounded |
| **Wreck decay duration** | Phase 10 | Must complete before the next flood could arrive, guaranteeing single use (`construction-spec.md` 4.4b) |
| **Worlds per commons shard** | Phase 5 | Hundreds (`genome-spec.md` 6.2f-i); the exact figure tunes crowd against liquidity |
| **Stamina lost per exchange** | Phase 6 | Winner and loser both pay (`genome-spec.md` 9.3b); the ratio between them sets how costly winning is |
| **Mana-to-Attack exchange rate** | Phase 6 | Rule 9.3d lets Mana press an attack; nothing sets how far |
| **Maturation curve shape** | Phase 8 | Linear, or accelerating late (`genotype-spec.md` 3.8a) |
| **Attack-versus-Agility resolution** | Phase 6 | Rule 9.3a is probabilistic; the function is unset |

> Two of these are not merely unset but **consequential enough to be experiments
> in their own right**. Longevity's mapping decides whether a stranded first agent
> returns before its owner gives up (`genome-spec.md` §11.2), and the mutation step
> decides whether selection has anything to climb — the same question
> `genome-spec.md` §12.3.2 answered for disposition expression, asked of the
> genotype's own variation.
