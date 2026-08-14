"""Environment loading for the backend, with required settings that fail loudly.

Secrets come from a .env file that is not committed, or from the real
environment in a deployed container. Nothing in this module carries a default
for a credential: a hardcoded fallback key means a misconfigured deployment
authenticates as somebody else's account instead of refusing to start, and the
mistake is invisible until the bill or the audit log arrives.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# Walk up from this file to the repository root so the same .env is found
# whether a service is started from the repo root, from backend/, or by uvicorn
# with a different working directory.
_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env")


class MissingConfig(RuntimeError):
    """A required setting has no value. Raised at import time, not at first use."""


def require_env(name: str, hint: str = "") -> str:
    """Return a required setting, or raise naming what is missing and where to put it."""
    value = os.getenv(name)
    if not value:
        suffix = f" {hint}" if hint else ""
        raise MissingConfig(
            f"{name} is not set. Add it to {_ROOT / '.env'} (see .env.example) "
            f"or to the container environment.{suffix}"
        )
    return value


def optional_env(name: str, default: str) -> str:
    """Return a setting that has a safe default. Never use this for a credential."""
    return os.getenv(name) or default


# --------------------------------------------------------------------- models

# One name for the model, read once. These were previously ~30 copies of the
# string "DeepSeek-V3.2" spread across the engine, the router, the judge panel
# and the manifest generator — so changing model meant finding all thirty, and
# missing one meant a subsystem quietly kept calling a model nobody else used.
DEFAULT_LLM_MODEL = optional_env("DEFAULT_LLM_MODEL", "gemini-3.5-flash-lite")

# Entity and relationship extraction for post-graph-rag. Separable from the
# conversational model because it is a different workload, but defaulted to it
# so a deployment that sets one setting gets a consistent pair.
RAG_MODEL = optional_env("RAG_MODEL", DEFAULT_LLM_MODEL)

# The embedding model is **not** interchangeable with another. Every vector
# already in the database was written in this model's geometry, so swapping it
# does not degrade search — it makes stored distances meaningless. A change
# here means reindexing the corpus, not restarting the service.
EMBEDDING_MODEL = optional_env("RAG_EMBEDDING_MODEL", "gemini-embedding-001")

# Must match the `vector(N)` column the schema declares (AG §3). A mismatch is
# not caught by a type: it surfaces as a pgvector dimension error at query
# time, in a code path far from the configuration that caused it.
EMBEDDING_DIM = int(optional_env("RAG_EMBEDDING_DIM", "1536"))

# Models the judge panel consults. More than one on purpose — a panel that
# agrees with itself is one model wearing three hats.
JUDGE_MODELS = [
    m.strip() for m in optional_env(
        "JUDGE_MODELS",
        "gemini-3.5-flash-lite,google/gemma-4-26b-a4b-it-maas,"
        "Meta-Llama-3.3-70B-Instruct").split(",") if m.strip()
]
