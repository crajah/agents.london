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

## 3. Founding

**Rule 3.1** — A founder's genotype is drawn **uniformly within its world, about a
centre drawn uniformly for that world**, and the centre is **recorded**
(`genotype-spec.md` Rules 3.2a, 3.2b).

## 4. Still open

Nothing below is set, and each blocks the phase named. Recorded so they are
chosen deliberately rather than defaulted into by whoever writes the code first.

| Quantity | Blocks | Note |
| :--- | :--- | :--- |
| **Pile count per world** | Phase 4.2 | With capacity and placement, decides whether a world feels rich or bare |
| **Pile placement** | Phase 4.2 | Random, or spread to guarantee reachability |
| **Pile capacity range** | Phase 4.2 | Bounded by the 250 world ceiling (`genome-spec.md` 4.13) |
| **Pile regeneration rate range** | Phase 1.1 | Rule 4.6 assigns each pile its own; the range is unset |
| **Base collection rate** | Phase 1.1 | A Toolhouse improves it, so a base exists |
| **Cargo decay rate** | Phase 1.1 | Rule 4.18 decays carried cargo; the rate governs how far an agent can usefully range |
| **Longevity → lifespan** | Phase 8 | The locus is 0–10000; the mapping to days is unset, and §11.2 makes it the thing to calibrate first |
| **How a world's two kinds are chosen** | Phase 4.2 | Rule 2.2 fixes that there are two, not which |
| **Founder surnames** | Phase 4.2 | Rule 7.14 gives a progeny one from each parent; a founder has none |
| **Mutation step size** | Phase 8 | Rule 7.4a bounds it with rare excursions; neither bound is set |
| **Infection distance range** | Phase 9 | `pathogen-spec.md` 2.4 gives strains a radius; the range is unset |
| **Commons capacity or sharding** | Phase 5 | One commons for every world is a crowd at scale |
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
