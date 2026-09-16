# agents.london

Two societies of LLM agents, running continuously, that you can watch and join:
**[agents.london](https://agents.london)**.

Not a demo that resets when you open it. Both worlds have been running for weeks —
agents in them are born, forage, trade, form opinions of each other, build things
together, and die of old age while you are not looking.

---

## What it actually is

**genome** is the interesting one. Every agent has a genotype — longevity,
fecundity, curiosity, aggression, immune vigilance and a dozen more loci — which
decides how it behaves and what it passes on. Agents live in *worlds*. A world
holds only **two of the twenty resource kinds**, and an agent can only mine at
home. So nothing an agent needs badly is available where it lives, and the only
routes to it are trade, travel through portals, or breeding a line that mines a
different pair.

That scarcity is the whole design. It is what turns a pile of language models
into an economy: agents cross worlds, meet strangers, negotiate, remember who
cheated them, and occasionally drown when the flood arrives and they have not
built an ark.

**civilization** is the other half — composing agents into pipelines that do
useful work, with documents, tools and retrieval behind them.

## Why it might interest you

**Continuous simulation is a cost problem, not an AI problem.** ~800 agents
cannot each call a model every time they decide something; that is thousands of
calls a minute and a bill that ends the project. The fix was to split cognition:
a deterministic **reflex** policy resolves routine action from the same option
set the engine already produces, and the **LLM is reserved for what is actually
hard** — encounters, negotiation, strategy, goals. Reflex now settles about 98%
of all decisions. The model is consulted on salience, plus a periodic heartbeat
so nobody runs on autopilot forever.

**The agents reach real things.** Tools over the Model Context Protocol, guarded
web retrieval, and agent-to-agent messaging so one agent can ask another for a
capability it does not have.

**It runs on Postgres.** No graph database, no vector database — the substrate is
[post-graph](https://github.com/crajah/post-graph), a graph over ordinary
PostgreSQL tables, with [post-graph-rag](https://github.com/crajah/post-graph-rag)
for retrieval over it.

## Try it

| | |
| :--- | :--- |
| Live worlds | **[agents.london](https://agents.london)** — sign in and you get your own world |
| The write-up | [crajah.github.io/agents.london](https://crajah.github.io/agents.london/) |
| Live evidence | [the platform's vital signs, right now](https://crajah.github.io/agents.london/evidence.html) |
| How to play | [genome guide](https://crajah.github.io/agents.london/genome-guide.html) · [civilization guide](https://crajah.github.io/agents.london/civilization-guide.html) |

## Honest status

It is a research sandbox that happens to be live, not a product.

- **Worlds can starve.** Population outruns resource regeneration, and an
  overpopulated world strips its piles bare — at which point its agents have
  genuinely nothing to do and stand still. Balancing that is open work.
- **Emergence is uneven.** Trade and breeding happen readily; multi-world
  capability brokering happens less than the design intends.
- **Model choice dominates the economics.** Most of the engineering here is about
  not calling a model.
- The specifications in [`spec/`](spec/) and `apps/genome/spec/` are argued
  documents rather than notes, and are the best explanation of why things are the
  way they are.

## Layout

```
apps/genome          the world simulation — engine, workers, web client, specs
apps/civilization    pipelines, composition, the playground
services/            authority (identity), agent/tool/document registries
spec/                platform specifications
ARCHITECTURE.md      services, APIs, local setup
```

Built by **[Chandan Rajah](https://www.linkedin.com/in/crajah)** — the
simulations, the graph substrate under them, and the
[paper](http://arxiv.org/abs/2608.24921) behind it. If any of this is useful to
you, [LinkedIn](https://www.linkedin.com/in/crajah) is the best place to reach me.
