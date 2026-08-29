# Genome — design

*How* genome is built. The rules it must obey are in [`../spec/`](../spec), and
nothing here introduces a game rule; where this folder and `../spec/` disagree,
`../spec/` wins.

| Document | Covers |
| :--- | :--- |
| [`execution-spec.md`](execution-spec.md) | agent execution: intents, the event queue, the autonomy loop, the inference budget |
| [`system-spec.md`](system-spec.md) | substrate, tenancy, workers, transfers, scale |
| [`interface-spec.md`](interface-spec.md) | what a user sees and touches, and the belief-against-truth view |

Rule numbering is local to each document. References of the form
`genome-spec.md` Rule 4.7 point into `../spec/`.

## The three decisions everything else follows from

**A day is a real day, and the world runs unattended.** Events are therefore
sparse, which is what makes a per-event cost model viable at all.

**Nothing is stored that can be derived.** Position comes from a movement intent
and the clock; pile quantities from a closed form. The tick does not advance the
world, it drains an event queue — so cost scales with *events*, not with agents.

**Inference is the budget.** Everything else is arithmetic and effectively free.
At 10⁶ agents deciding ten times a day this is order $1.5k/day and it dominates
every other cost in the system, which makes decisions-per-agent-per-day the most
consequential number in the design.
