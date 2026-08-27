# shared

Modules imported by **both** the apps and the registry services.

Deliberately not called `platform`: a top-level `platform/` package on
`sys.path` shadows Python's standard-library `platform` module, and the failure
that produces is remote from its cause.

These live here rather than in an app because all three services already depend
on them — `services/*/Dockerfile` copies them into each image, and the service
tests put this directory on `sys.path`. Leaving them inside an application
directory would mean a shared service reaching into one app's folder, which is
exactly what stops a second app being added cleanly.

| Module | Imported by |
| :--- | :--- |
| `metering.py` | agent-registry, tool-registry, document-registry, pipeline_runtime |
| `embedding.py` | agent-registry, tool-registry |
| `pipeline_runtime.py` | agent-registry, the civilization app backend |

Everything here is imported **flat** (`from metering import UsageEvent`), not as
`shared.metering`, because the service Dockerfiles copy the files into the image
root. Keep it that way, or those COPY lines have to become package installs.
