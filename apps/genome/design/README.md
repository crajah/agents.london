# Genome — design

*How* genome is built. The rules it must obey are in [`../spec/`](../spec), and
nothing here introduces a game rule; where this folder and `../spec/` disagree,
`../spec/` wins.

| Document | Covers |
| :--- | :--- |
| [`execution-spec.md`](execution-spec.md) | agent execution: intents, the event queue, the autonomy loop, inference cost, negotiation, the ADK runtime, model credentials |
| [`system-spec.md`](system-spec.md) | substrate, tenancy, workers, transfers, scale, queues |
| [`interface-spec.md`](interface-spec.md) | what a user sees and touches, and the belief-against-truth view |

Rule numbering is local to each document. References of the form
`genome-spec.md` Rule 4.7 point into `../spec/`.

## The three decisions everything else follows from

**A day is a real day, and the world runs unattended.** Events are therefore
sparse, which is what makes a per-event cost model viable at all.

**Nothing is stored that can be derived.** Position comes from a movement intent
and the clock; pile quantities from a closed form. The tick does not advance the
world, it drains an event queue — so cost scales with *events*, not with agents.

**Deliberation is scarce; action never is.** Agents carry a decision budget
(`execution-spec.md` Rule 5.2) that exists to make patience cost something, not to
control spend. It charges only *discretionary* thinking — countering an offer,
reconsidering a plan — and never blocks an agent from acting, so a spent agent
becomes take-it-or-leave-it rather than frozen. It is identical for every agent
and unaffected by whose key pays (§9), so deliberation never follows money.

Inference remains the dominant cost regardless — order $1.5k/day at 10⁶ agents
deciding ten times daily — and is metered from the start even though the budget
is a game rule rather than a spend limit.

## Open, and a decision for the specification rather than the design

**May agents negotiate at a distance, or must they meet first?** `genome-spec.md`
Rule 9.1a puts negotiation on A2A and Rule 8.5 puts deliberation there too, but
neither says whether the parties must be co-located. Rule 4.2 settles the
*transfer* — resources move only inside agents, so cargo changes hands face to
face — and leaves the conversation open.

The two readings give different games. If agents may negotiate remotely, the map
becomes a delivery problem: deals are struck at leisure and travel is settlement.
If they must meet, then every trade costs a journey before a word is exchanged,
travel is speculative, and an agent must decide whom to approach knowing only
colour (Rule 3.4).

The second is the more interesting constraint and the more expensive one, and it
is a rule about the world rather than a fact about the architecture — so it
belongs in `../spec/`.
