"""Path setup, so the backend's tests run from the repository root too.

`backend/` is a directory of top-level modules that import each other by bare
name (`from civilization import …`), which works when pytest is started inside
it and not from the root. That difference meant `python3 -m pytest` at the root
could not even collect these tests, so they were only ever run by someone who
knew to `cd backend` first.
"""
import pathlib
import sys

BACKEND = pathlib.Path(__file__).resolve().parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

# The repository root as well, for the modules that import `backend.x`.
ROOT = BACKEND.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# `pipeline_runtime.py` lives here but its spec models — ExecutionPolicy,
# PipelineVersionSpec — live in the agent registry, and the registry's
# Dockerfile copies this module in beside them. So at run time they are
# siblings, and the checkout is the only place they are not. Putting the
# registry on the path reproduces the deployed layout rather than inventing a
# second one for tests.
AGENT_REGISTRY = ROOT / "services" / "agent-registry"
if AGENT_REGISTRY.is_dir() and str(AGENT_REGISTRY) not in sys.path:
    sys.path.insert(0, str(AGENT_REGISTRY))
