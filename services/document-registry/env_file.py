"""Finding a .env, wherever this service happens to be running from.

The document registry ran `load_dotenv(Path(__file__).parents[2] / ".env")`,
with a comment claiming it worked both in the image and from a checkout. It
worked from a checkout only. The image flattens
`services/document-registry/app.py` to `/app/app.py`, so `parents` is
`[/app, /]`, and `parents[2]` raised `IndexError` at import time — the
container could not start, and the traceback pointed at pathlib rather than at
the assumption about directory depth that caused it.

Its own module so it can be tested without importing the service, which needs a
model key, a database and the extraction stack before it will import at all.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

logger = logging.getLogger(__name__)


def find_env_file(start: Path) -> Optional[Path]:
    """The nearest .env at or above `start`, or None.

    Walks up rather than indexing a fixed number of levels, because the number
    of levels differs between the image and a checkout — which is precisely
    what broke. Stops at the filesystem root.
    """
    start = start.resolve()
    first = start if start.is_dir() else start.parent
    for directory in (first, *first.parents):
        candidate = directory / ".env"
        if candidate.is_file():
            return candidate
    return None


def load_env_file(start: Optional[Path] = None) -> Optional[Path]:
    """Load the nearest .env if there is one, and report which.

    Finding none is not an error and must not raise. A container is configured
    through its environment, and there is no file to read — refusing to start
    over a missing convenience file would take down a correctly configured
    deployment.
    """
    found = find_env_file(start or Path(__file__))
    if found is None:
        logger.info("no .env found; using the process environment")
        return None
    load_dotenv(found)
    logger.info("loaded configuration from %s", found)
    return found
