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

## 6. Rendering

### 6.1 The split

**Rule 6.1** — **React and Tailwind own the chrome**; **one PixiJS canvas owns the
world**. Chat, the agent inspector, the world channel and every panel are ordinary
DOM.

**Rule 6.2** — The scene is **not React state**. The canvas is driven
imperatively — `useRef` and `useEffect` — and communicates with React through a
thin store, never through props.

> Agent positions change every frame from a clock (Rule 2.1). Routing that through
> React's reconciler would be continuous work for no benefit, since nothing on the
> canvas is derived from props: the scene is derived from time.
>
> This also avoids a live integration problem rather than fighting it. Binding
> `pixi-viewport` to the official React renderer is a known friction point without
> an official guide, and pan and zoom are not optional here. Driving Pixi directly
> is both less code and less risk.

**Rule 6.3** — **PixiJS**, not a game framework.

> Genome has no physics, no collision, no tilemaps, no player-controlled character
> and no animation state machines. A framework's entire value is the things we
> would not use, at roughly three times the bundle. A renderer is the whole
> requirement.

### 6.2 Isometric is a projection, not a grid

**Rule 6.4** — World coordinates are **plain Cartesian** everywhere: schema,
closed forms, specification, wire.

**Rule 6.5** — The isometric view is a **render-time transform only**, applied in
the canvas and nowhere else. Hit-testing is its inverse.

**Rule 6.6** — There is **no tile grid**. Space is continuous, as movement already
is (`execution-spec.md` Rule 2.1).

> The distinction matters because the two are usually conflated. Isometric *tiles*
> are a movement model — discrete cells, adjacency, pathfinding over a lattice —
> and genome has none of that: an agent departs a point, arrives at a point, and
> is interpolated between them. Isometric *projection* is a 2:1 axonometric
> transform applied at draw time.
>
> **Keeping the projection in the renderer keeps the decision reversible.**
> Isometric against flat top-down becomes a view concern that can be swapped
> without touching the simulation, the schema, or a single rule. Nothing is built
> yet, so preserving that option is worth more than being right now.

**Rule 6.7** — Draw order is **painter's algorithm on world y**, recomputed per
frame for moving sprites.

### 6.3 What the canvas shows, and what it does not

**Rule 6.8** — The canvas shows **what agents can see**. The panels show **what
only the user can see**.

> This is the most useful rule in the section, because it turns Rules 13.1 and
> 13.3 of `genome-spec.md` from a permission table into a visual language.
>
> Colour is the only attribute agents can observe (`genotype-spec.md` Rule 3.4),
> so **on the map an agent simply is its two colours** — that is the entire
> readable state, exactly as it is for every other agent. Genotype, expression,
> opinions and cargo live in HTML panels, because they are things only a human
> has.
>
> The payoff is that the map stays honest. A user looking at the world sees the
> world agents negotiate in; to see more they must open something, and the act of
> opening it is a reminder that they know more than the agents do. Put a genotype
> on the map and that distinction quietly disappears.

**Rule 6.9** — Drawn on the map: agents, piles, constructions, **first-degree
portals only** (`genome-spec.md` Rule 6.2d), and a flood countdown when one is
running.

**Rule 6.9a** — An agent is a **disc in its first colour with an equilateral
triangle in its second**, the triangle pointing along its heading. That is the
whole vocabulary.

**Rule 6.9b** — Heading is **derived from the movement intent**, never stored:
the bearing from `from_xy` to `to_xy` (`execution-spec.md` Rule 2.4). A stationary
agent keeps the heading it arrived on.

**Rule 6.9c** — Both shapes are **tinted sprites from one source texture**, not
per-frame vector drawing, so batching holds (Rule 6.12).

**Rule 6.9e** — A pile is a **soft cloud** in its kind's colour. **Lightness
encodes fill** — pale when nearly exhausted, full A100 at capacity
(`genome-spec.md` Rule 4.9). **Size encodes capacity**, not quantity.

**Rule 6.9f** — The tint is a **pure function of the closed form and the clock**
(`execution-spec.md` Rule 2.3). There is no animation system; a regenerating pile
simply deepens.

> Two channels, each carrying something the other cannot, and neither needing a
> frame of state.
>
> **Separating capacity from fill is what makes a map readable at a glance.** Were
> size to track quantity, a large depleted pile and a small full one would look
> alike and the difference between *worked out* and *never much* would be
> invisible. With size fixed to capacity, a wide pale cloud says a rich pile has
> been stripped and a small saturated one says a modest pile is untouched — and
> those call for opposite decisions.
>
> **Depletion becomes legible across a whole world.** A map of pale clouds is an
> exhausted world and a map of saturated ones is a wealthy one, readable without
> inspecting anything. It also makes Rule 4.13's ceiling visible: when aggregate
> stock halts regeneration, the map simply stops deepening.
>
> **And it is free.** Quantity is already derived from `(qty_at, measured_at,
> rate, cap)`, so the tint is `lerp(white, kindColour, qty/cap)` evaluated at draw
> time. Nothing is stored, nothing is animated, and a pile mined while the user
> watches pales in real time because the arithmetic says so.
>
> The grammar is worth keeping consistent: **agents are crisp geometry, resources
> are soft clouds.** One glance distinguishes what decides from what is decided
> over.

**Rule 6.9d** — **Ownership may be marked** — a ring on the user's own agents —
because it discloses nothing about an agent that the agent does not already know
about itself.

> Two shapes and two tints do more work here than sprite art would, and the
> reasons are worth setting down because they are easy to lose later.
>
> **It renders exactly the readable state and nothing else.** An agent carries two
> colour loci (`genotype-spec.md` Rule 3.5) and colour is the only attribute other
> agents can observe (Rule 3.4). A disc and a triangle in those two colours *is*
> the agent as its counterparties see it — so Rule 6.8 is satisfied by the shape
> itself rather than by remembering to withhold things.
>
> **There is no art dependency.** One white disc and one white triangle, tinted at
> draw time, cover every agent that will ever exist across a twenty-hue palette.
> Nothing needs drawing in isometric perspective, nothing needs redrawing when the
> palette changes, and the atlas stays a single texture.
>
> **Facing is free and honest.** Bearing falls out of the movement intent, so it
> costs no storage and cannot disagree with where the agent is actually going. A
> heading stored separately would eventually drift from the path and look wrong in
> precisely the way that makes a simulation feel broken.
>
> Under the isometric transform a disc projects to an ellipse, which reads
> correctly as a token lying flat on the ground, and the triangle rotates in world
> space before projection. Both are the cheap case.

**Rule 6.10** — Not drawn, deliberately: no physics, no pathfinding visualisation,
no particle systems, no audio, no 3D, no tilemap editor, no lighting.

> Recorded as a fence rather than an omission. Each of these is easy to add, hard
> to remove, and buys atmosphere at the cost of the thing that actually matters
> here — being able to watch a population and understand what it is doing. A
> legible map with a thousand agents on it is a better product than a beautiful
> one with fifty.

### 6.4 Camera and scale

**Rule 6.11** — Pan, zoom and pinch are handled by **pixi-viewport**. A world is
the unit of view (Rule 5.1).

**Rule 6.12** — Sprites share a **single texture atlas** so that draw calls batch.
Agents are one sprite plus an optional label, and labels are culled below a zoom
threshold.

> Batching is the whole performance story. Within it, a thousand-plus sprites at
> sixty frames is routine; outside it, a few hundred is not. The rule exists
> because it is trivially easy to break by introducing a second atlas or a
> per-sprite filter, and the failure appears as a mysterious frame-rate cliff
> rather than as an error.

**Rule 6.13** — The client renders from the **same closed forms the server uses**
(Rule 5.2), so a divergence is a bug in one of them and the arrival event is
authoritative.
