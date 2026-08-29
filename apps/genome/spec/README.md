# genome specifications

Specifications for the genome application. Empty so far.

## Scope

App-level specs only — what genome does. Specifications for the shared
platform live in the repository-root `spec/`, which covers the agent graph,
the registries and the founding agents; genome's specs may reference those but
should not restate them.

Anything genome specifies that a second application would also need is a sign
it belongs in the root `spec/` and in `shared/` or `services/`, not here.

## Convention

Named `<thing>-spec.md`, matching the root `spec/`. Each opens by saying what
it specifies and where the implementation lives, then states rules as numbered
`Rule N.M` with the reasoning attached — the existing specs argue for each rule
rather than only asserting it, and their rule numbers are cited from code and
commit messages.

- [`calibration-spec.md`](calibration-spec.md) — every quantity the simulation needs, in one place; what is set, and what is still open.
