# genome

Placeholder for the genome application. Nothing is implemented yet.

## Where things go

This folder holds **only** what is specific to genome. Anything a second
application would also want belongs outside it:

| Need | Put it in |
| :--- | :--- |
| Genome's own UI | `apps/genome/frontend/` |
| Genome's own API / BFF | `apps/genome/backend/` |
| Code another app would also use | `shared/` |
| A registry or long-running service | `services/` |

## Rules the layout depends on

**Never import from another app.** `apps/genome/` may import from `shared/` and
call `services/`, but not from `apps/civilization/`. That direction is the whole
reason the repository was restructured: the registry services used to import
`metering`, `embedding` and `pipeline_runtime` out of the civilization backend,
which meant a second app could not be added without depending on the first.
Promote to `shared/` instead of reaching sideways.

**Shared modules are imported flat.** `from metering import UsageEvent`, not
`from shared.metering import …`, because the service Dockerfiles copy those
files into the image root.

**Build from the repository root.** Any Dockerfile here that needs `shared/`
must be built with a root context and referenced by path, as
`apps/civilization/backend/Dockerfile` is in `.github/workflows/deploy-gke.yml`.
A context scoped to this folder cannot see `shared/`.

**Discover the repository root, never assume a depth.** Three separate
`parent.parent` assumptions broke when the civilization app moved down two
levels, and none failed in a way that named its cause — one reported an
environment variable as unset while naming a `.env` path that had never
existed. Walk up for a marker instead.

## Adding genome to CI

`.github/workflows/deploy-gke.yml` builds an explicit matrix of services, so
nothing here is built until it is added there. That is deliberate: this folder
can exist, and be committed, without changing what is deployed.
