"""A read-through cache in front of post-graph, partitioned by realm.

Tool resolution sits on the hot path of every agent turn, so it is cached. The
two properties that make this a cache rather than a second store (§10):

**It is never written to except after a successful database write.** A cache
that can hold an entry post-graph does not have is a registry that answers
differently depending on which replica served the request — and the replicas
never disagree loudly, they just disagree.

**It is partitioned by realm.** A single flat dictionary shared across realms
makes Rule 2.1 unenforceable at exactly the layer that serves most reads: the
filtering becomes a `.get("org_id") == …` comparison over everyone's data,
which is one forgotten filter away from a cross-tenant leak.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class ToolCache:
    """`realm -> (tool_id, version) -> record`, plus a per-realm identity map."""

    def __init__(self) -> None:
        self._versions: Dict[str, Dict[Tuple[str, str], Dict[str, Any]]] = {}
        self._identities: Dict[str, Dict[str, Any]] = {}
        self.hits = 0
        self.misses = 0

    # ------------------------------------------------------------- reading

    def get_version(self, realm: str, tool_id: str,
                    version: str) -> Optional[Dict[str, Any]]:
        record = self._versions.get(realm, {}).get((tool_id, version))
        if record is None:
            self.misses += 1
        else:
            self.hits += 1
        return record

    def get_identity(self, realm: str, tool_id: str) -> Optional[Dict[str, Any]]:
        return self._identities.get(realm, {}).get(tool_id)

    def realm_tool_ids(self, realm: str) -> list:
        return sorted(self._identities.get(realm, {}))

    def count(self, realm: Optional[str] = None) -> int:
        if realm is not None:
            return len(self._identities.get(realm, {}))
        return sum(len(v) for v in self._identities.values())

    # ------------------------------------------------------------- writing

    def put(self, realm: str, tool_id: str, version: Optional[str],
            identity: Dict[str, Any], record: Optional[Dict[str, Any]]) -> None:
        """Record a tool that post-graph has already accepted.

        Called only after a successful write or a successful read, never
        speculatively — see the module docstring.
        """
        self._identities.setdefault(realm, {})[tool_id] = identity
        if version and record is not None:
            self._versions.setdefault(realm, {})[(tool_id, version)] = record

    def drop(self, realm: str, tool_id: str) -> None:
        """Forget one tool, so the next read goes back to the database.

        Used after a lifecycle change rather than trying to patch the cached
        copy: recomputing from the source is cheap here and cannot go stale in a
        way that survives.
        """
        self._identities.get(realm, {}).pop(tool_id, None)
        versions = self._versions.get(realm, {})
        for key in [k for k in versions if k[0] == tool_id]:
            versions.pop(key, None)

    def drop_realm(self, realm: str) -> None:
        self._identities.pop(realm, None)
        self._versions.pop(realm, None)

    def clear(self) -> None:
        self._identities.clear()
        self._versions.clear()
