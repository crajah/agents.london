"""Writer tests against a fake post-graph client that records every call.

A fake rather than a mock: the idempotency guarantee (Rule 8.1) and the
publish-marker ordering are both claims about *how many* writes happen and in
what order, and only a recorder can show that.
"""
import pytest

from tool_cache import ToolCache
from tool_model import ACTIVE, DORMANT, PUBLISHED, RegistrationError
from tool_store import (
    TOOLS, get_tool, latest_versions, list_tools, register_tool_version,
    resolve_vertex, set_lifecycle, set_version_status,
)
from test_tool_model import identity, version


class FakeClient:
    """Records calls in order and serves vertex history back.

    Models post-graph's id semantics rather than papering over them: vertices
    get integer primary keys from a counter, and `tool_id` lives in the payload.
    """

    def __init__(self, schema_per_realm=True):
        self.schema_per_realm = schema_per_realm
        self.calls = []
        self.data = {}          # pk -> [payload, …] newest last
        self.vertices = {}      # (realm, tool_id) -> pk
        self.payloads = {}      # pk -> identity payload
        self._next_pk = 1

    def _get_table_ref(self, table, realm):
        return f'"{realm}"."{table}"'

    async def _fetch(self, query, *args):
        if "information_schema" in query:
            realms = sorted({r for r, _ in self.vertices})
            return [{"table_schema": r} for r in realms]
        if "current_version" in query:
            realm, pk = args[0], args[1]
            return [{"v": self.payloads.get(pk, {}).get("current_version")}]
        if "SELECT payload FROM" in query:
            realm, pk = args[0], args[1]
            return [{"payload": self.payloads[pk]}] if pk in self.payloads else []
        if "SELECT id, payload FROM" in query:
            realm = args[0]
            return [{"id": pk, "payload": self.payloads[pk]}
                    for (r, _t), pk in sorted(self.vertices.items(), key=lambda kv: kv[1])
                    if r == realm]
        realm, tool_id = args[0], args[1]
        pk = self.vertices.get((realm, tool_id))
        return [{"id": pk}] if pk else []

    async def create_vertex_table(self, table, realm=None, vector_dim=None):
        self.calls.append(("create_vertex_table", table, realm))

    async def add_vertex(self, table, realm=None, space=None, vertex_id=None,
                         payload=None, embedding=None):
        pk = self._next_pk
        self._next_pk += 1
        self.vertices[(realm, payload["tool_id"])] = pk
        self.payloads[pk] = payload
        self.calls.append(("add_vertex", table, payload["tool_id"]))
        return type("V", (), {"id": pk})()

    async def upsert_vertex(self, table, realm=None, vertex_id=None, space=None,
                            payload=None, embedding=None):
        self.payloads[vertex_id] = payload
        self.calls.append(("upsert_vertex", table, payload.get("tool_id")))

    async def add_vertex_data(self, table_name=None, realm=None, vertex_id=None,
                              payload=None):
        self.calls.append(("add_vertex_data", vertex_id, payload.get("status"),
                           payload.get("version")))
        self.data.setdefault(vertex_id, []).append(payload)

    async def get_vertex_data(self, table_name=None, realm=None, vertex_id=None):
        # post-graph returns newest first.
        return [{"payload": p} for p in reversed(self.data.get(vertex_id, []))]


# ------------------------------------------------------------- registration

@pytest.mark.asyncio
async def test_version_is_written_as_history_not_a_second_vertex():
    c = FakeClient()
    await register_tool_version(c, identity(), version())
    assert ("add_vertex", TOOLS, "mcp-x") in c.calls
    pk = c.vertices[("org_a", "mcp-x")]
    assert any(k == "add_vertex_data" and v == pk for k, v, *_ in c.calls)
    assert sum(1 for k, *_ in c.calls if k == "add_vertex") == 1


@pytest.mark.asyncio
async def test_publish_marker_is_written_last():
    """A failure part-way leaves a draft, which is not resolvable."""
    c = FakeClient()
    await register_tool_version(c, identity(), version())
    pk = c.vertices[("org_a", "mcp-x")]
    statuses = [s for k, v, s, *_ in c.calls if k == "add_vertex_data" and v == pk]
    assert statuses == ["draft", "published"]


@pytest.mark.asyncio
async def test_reregistering_identical_content_appends_nothing():
    """Rule 8.1 — deployment tooling retries, and a retry is not a new version.

    This is the bug that grew the table by the size of the default catalogue on
    every pod restart, invisibly, because the read path deduplicated by tool_id.
    """
    c = FakeClient()
    await register_tool_version(c, identity(), version())
    before = len([1 for k, *_ in c.calls if k == "add_vertex_data"])
    await register_tool_version(c, identity(), version())
    after = len([1 for k, *_ in c.calls if k == "add_vertex_data"])
    assert before == after == 2
    assert sum(1 for k, *_ in c.calls if k == "add_vertex") == 1


@pytest.mark.asyncio
async def test_seeding_five_tools_twice_creates_five_vertices():
    c = FakeClient()
    for n in range(5):
        ident = identity(tool_id=f"mcp-t{n}")
        await register_tool_version(c, ident, version(tool_id=f"mcp-t{n}"))
    for n in range(5):
        ident = identity(tool_id=f"mcp-t{n}")
        await register_tool_version(c, ident, version(tool_id=f"mcp-t{n}"))
    assert sum(1 for k, *_ in c.calls if k == "add_vertex") == 5


@pytest.mark.asyncio
async def test_editing_a_published_version_is_rejected_by_the_writer():
    c = FakeClient()
    await register_tool_version(c, identity(), version())
    with pytest.raises(RegistrationError, match="Rule 3.3"):
        await register_tool_version(c, identity(),
                                    version(endpoint_url="http://other.svc.cluster.local/x"))


@pytest.mark.asyncio
async def test_a_new_version_appends_to_history():
    c = FakeClient()
    await register_tool_version(c, identity(), version())
    await register_tool_version(c, identity(),
                                version(version="1.1.0",
                                        endpoint_url="http://x.svc.cluster.local/v2"))
    pk = c.vertices[("org_a", "mcp-x")]
    versions = await latest_versions(c, "org_a", pk)
    assert set(versions) == {"1.0.0", "1.1.0"}
    assert all(v["status"] == PUBLISHED for v in versions.values())


# ---------------------------------------------------------------- retrieval

@pytest.mark.asyncio
async def test_get_tool_returns_current_version_by_default():
    c = FakeClient()
    await register_tool_version(c, identity(), version())
    await register_tool_version(c, identity(),
                                version(version="2.0.0",
                                        endpoint_url="http://x.svc.cluster.local/v2"))
    found = await get_tool(c, "org_a", "mcp-x")
    assert found and found[1]["version"] == "2.0.0"


@pytest.mark.asyncio
async def test_get_tool_can_resolve_an_older_pin():
    """The only read path that may return a non-current record — pins need it."""
    c = FakeClient()
    await register_tool_version(c, identity(), version())
    await register_tool_version(c, identity(),
                                version(version="2.0.0",
                                        endpoint_url="http://x.svc.cluster.local/v2"))
    found = await get_tool(c, "org_a", "mcp-x", version="1.0.0")
    assert found and found[1]["version"] == "1.0.0"


@pytest.mark.asyncio
async def test_unknown_tool_resolves_to_nothing():
    c = FakeClient()
    assert await resolve_vertex(c, "org_a", "ghost") is None
    assert await get_tool(c, "org_a", "ghost") is None


# ----------------------------------------------------------------- lifecycle

@pytest.mark.asyncio
async def test_delete_is_dormancy_and_is_persisted():
    """Rule 9.2 — a cache-only delete reappears on restart with no error."""
    c = FakeClient()
    await register_tool_version(c, identity(), version())
    await set_lifecycle(c, "org_a", "mcp-x", DORMANT)
    pk = c.vertices[("org_a", "mcp-x")]
    assert c.payloads[pk]["lifecycle"] == DORMANT
    assert ("upsert_vertex", TOOLS, "mcp-x") in c.calls


@pytest.mark.asyncio
async def test_dormant_tools_are_excluded_from_listing():
    c = FakeClient()
    await register_tool_version(c, identity(), version())
    await set_lifecycle(c, "org_a", "mcp-x", DORMANT)
    assert await list_tools(c, "org_a") == []
    assert len(await list_tools(c, "org_a", include_inactive=True)) == 1


@pytest.mark.asyncio
async def test_dormancy_is_reversible():
    c = FakeClient()
    await register_tool_version(c, identity(), version())
    await set_lifecycle(c, "org_a", "mcp-x", DORMANT)
    await set_lifecycle(c, "org_a", "mcp-x", ACTIVE)
    assert len(await list_tools(c, "org_a")) == 1


@pytest.mark.asyncio
async def test_revoking_without_a_replacement_is_rejected():
    """Rule 4.5 — silent revocation leaves agents reporting success."""
    c = FakeClient()
    await register_tool_version(c, identity(), version())
    with pytest.raises(RegistrationError, match="Rule 4.5"):
        await set_version_status(c, "org_a", "mcp-x", "1.0.0", "revoked")


@pytest.mark.asyncio
async def test_revoking_with_a_replacement_is_recorded_as_history():
    c = FakeClient()
    await register_tool_version(c, identity(), version())
    await set_version_status(c, "org_a", "mcp-x", "1.0.0", "revoked",
                             replacement_version_id="tlv_mcp-x_2.0.0")
    pk = c.vertices[("org_a", "mcp-x")]
    versions = await latest_versions(c, "org_a", pk)
    assert versions["1.0.0"]["status"] == "revoked"
    assert versions["1.0.0"]["replacement_version_id"] == "tlv_mcp-x_2.0.0"
    # Appended, not edited: the record of what agents pinned is still there.
    assert len(c.data[pk]) == 3


@pytest.mark.asyncio
async def test_deprecation_needs_no_replacement():
    c = FakeClient()
    await register_tool_version(c, identity(), version())
    await set_version_status(c, "org_a", "mcp-x", "1.0.0", "deprecated")


# -------------------------------------------------------------------- tenancy

@pytest.mark.asyncio
async def test_listing_is_scoped_to_one_realm():
    """Rule 2.1 — a listing without a realm is a cross-tenant leak."""
    c = FakeClient()
    await register_tool_version(c, identity(org_id="org_a"), version())
    await register_tool_version(c, identity(org_id="org_b"), version())
    assert len(await list_tools(c, "org_a")) == 1
    assert len(await list_tools(c, "org_b")) == 1


@pytest.mark.asyncio
async def test_project_scoped_tools_are_filtered_by_project():
    c = FakeClient()
    await register_tool_version(
        c, identity(tool_id="mcp-p", scope_type="project", project_id="proj_a"),
        version(tool_id="mcp-p"))
    await register_tool_version(c, identity(tool_id="mcp-org"), version(tool_id="mcp-org"))
    ids = {e["identity"].tool_id for e in await list_tools(c, "org_a", "proj_a")}
    assert ids == {"mcp-p", "mcp-org"}
    ids = {e["identity"].tool_id for e in await list_tools(c, "org_a", "proj_b")}
    assert ids == {"mcp-org"}


# ---------------------------------------------------------------------- cache

def test_cache_is_partitioned_by_realm():
    """Rule 10.2 — one flat dict makes Rule 2.1 unenforceable at the hot path."""
    cache = ToolCache()
    cache.put("org_a", "mcp-x", "1.0.0", {"tool_id": "mcp-x"}, {"version": "1.0.0"})
    assert cache.get_version("org_b", "mcp-x", "1.0.0") is None
    assert cache.get_identity("org_b", "mcp-x") is None
    assert cache.get_version("org_a", "mcp-x", "1.0.0") is not None


def test_dropping_a_tool_forgets_all_its_versions():
    cache = ToolCache()
    cache.put("org_a", "mcp-x", "1.0.0", {}, {"version": "1.0.0"})
    cache.put("org_a", "mcp-x", "2.0.0", {}, {"version": "2.0.0"})
    cache.drop("org_a", "mcp-x")
    assert cache.get_version("org_a", "mcp-x", "1.0.0") is None
    assert cache.get_version("org_a", "mcp-x", "2.0.0") is None


def test_cache_counts_per_realm():
    cache = ToolCache()
    cache.put("org_a", "mcp-x", "1.0.0", {}, {})
    cache.put("org_b", "mcp-y", "1.0.0", {}, {})
    assert cache.count("org_a") == 1
    assert cache.count() == 2
