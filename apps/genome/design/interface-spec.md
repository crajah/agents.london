# Genome — user interface

**Status: draft. Nothing is implemented.** Subordinate to `../spec/`; introduces
no game rule. Numbering is local to this document.

## 1. What a user may see and touch

Taken entirely from `genome-spec.md` §13; restated here as a permission matrix
because the interface is where it is enforced.

| | Own world / agents | Any other |
| :--- | :--- | :--- |
| See the isometric map, piles, stock, constructions | yes | **yes** (Rule 13.2) |
| See an agent's genotype and expression | yes | **yes** (Rule 13.1) |
| Chat with, instruct | yes (Rule 10.1a) | **no** (Rule 13.4) |
| Place plans | yes (Rule 13.6) | no |
| Change anything | yes | no |

**Rule 1.1** — The client **never receives** anything an agent may not know that
its user may not see. Sight is broad but it is not unlimited: opinions belong to
the agent holding them, and are shown only for the user's own agents.

> The asymmetry to preserve is `genome-spec.md` Rule 13.3 — observation is a
> human affordance and confers nothing on agents. The interface is where that
> could most easily leak: a convenient endpoint that returns "all piles in this
> world" to a user is correct, and the same endpoint reused to answer an agent's
> query is a repeal of Rule 8's entire knowledge model.
>
> **Agent-facing and user-facing reads must not share a path.** Not for tidiness —
> because they have opposite rules.

## 2. Observation is a read

**Rule 2.1** — The client **interpolates**. Position comes from the movement
intent and the clock (`execution-spec.md` Rule 2.2); pile quantities from the
closed form (Rule 2.3).

**Rule 2.2** — The server pushes **events**, not frames. Movement is smooth on
screen because the client computes it, not because anything streamed it.

> Which is what makes "watch agents move around, resources grow and shrink" cost
> essentially nothing. The wire carries *an agent departed for here, arriving
> then* — two numbers and a timestamp — and the animation is local. A world with a
> thousand agents in it streams no more than a world with ten.

**Rule 2.3** — Watching changes nothing. There is no code path by which an
observed world differs from an unobserved one (`execution-spec.md` Rule 4.2).

## 3. The surfaces

**Rule 3.1** — **World view.** Isometric map (`genome-spec.md` Rule 5.1), any
world, read-only unless owned. Agents, piles, constructions, teleport portals,
and the flood countdown when one is running (`construction-spec.md` Rule 4.8).

**Rule 3.2** — **Agent inspector.** Genotype and expression for any agent
anywhere. Lineage, colour, name, capability, and — for the user's own agents —
cargo, objectives and opinions.

**Rule 3.3** — **Chat.** With the user's own agents only. An instruction is a
command; an assertion of fact is testimony subject to the agent's Credulity
(`genome-spec.md` Rule 13.5), and the interface must **show which of the two it
just sent**.

> Otherwise the most confusing thing in the product is unexplained. A user tells
> their agent something true, watches it disregard the advice, and concludes the
> game is broken. It is not: they made a claim to an agent with low Credulity, and
> claims are evidence rather than fact. Surfacing the distinction at the moment of
> sending turns a bug report into a mechanic — and into a reason to care which of
> your agents is credulous.

**Rule 3.4** — **World channel.** Opened by clicking the world rather than an
agent. It is where plans are authored (`genome-spec.md` Rule 13.6b) — a
conversation in which a user describes an item and the tree of things it depends
on, and the system renders it as a buildable plan.

**Rule 3.5** — The channel may express a **form, a bill of materials, a
dependency tree and a contributor count**, and nothing else. It cannot express an
effect, a yield or a relaxed constraint.

> The grammar is the enforcement. If a plan cannot be *said* as anything but a
> shape and what it is made from, Rule 13.7 needs no runtime check — there is no
> sentence a user could utter that would grant their construction a power.
>
> Authoring by conversation rather than by form is the right call for a tree
> specifically. A form is fine for one item with a bill of materials and becomes
> punishing at depth four, where the useful question is *and what does that need?*
> — which is a dialogue, not a field.

## 4. The view that only this design can offer

**Rule 4.1** — **Belief against truth.** For a user's own agent, its opinion of
another agent is shown beside that other agent's actual genotype, with the gap
rendered.

> This is the screen the whole specification has been quietly building toward, and
> it costs nothing because both numbers already exist.
>
> Agents run on opinion, never on truth (`genotype-spec.md` Rule 6.8). The human
> watching has no such limit (Rule 13.1). **So the user is the only party in the
> system who can see a deception while it is happening** — who can watch an agent
> project an attractiveness it does not possess (Rule 6.11), watch a counterparty
> believe it, and watch the belief harden or decay under Rule 6.10a.
>
> Rendered over time it is a plot of an estimate converging on, or diverging from,
> a line that the agent cannot see. Nothing else in the product is like it, and no
> simulation that let agents read each other's attributes could offer it at all.

**Rule 4.2** — The gap is shown for the **user's own agents' opinions**, never for
another user's. Whose beliefs you may inspect follows who you may instruct.

## 5. Scale of the interface

**Rule 5.1** — A world is the unit of subscription. A client subscribes to one
world and receives its events.

**Rule 5.2** — The map is **rendered from the same closed forms the server uses**.
Divergence between client and server prediction is a bug in one of them, and the
arrival event is authoritative.

> Which gives a free consistency check: if the client's interpolated arrival and
> the server's arrival event disagree, something has drifted. Cheap to assert,
> awkward to discover later.
