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
