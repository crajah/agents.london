"""Writer tests against a fake post-graph client that records every call.

A fake rather than a mock: the ordering guarantee in registry_store's docstring
is the whole atomicity argument, and only a recorder can show that the publish
marker really is written last.
"""
import pytest

from registry_model import ExecutionPolicy, PipelineVersionSpec, RegistrationError, StepBinding, StepDependency
from registry_store import (
    AGENTS, COMPOSES, PIPELINES, STEP_DEPENDENCY, register_agent_version,
    register_pipeline_version, _split_version_id,
)
from test_registry_model import OBJ, agent


class FakeClient:
    """Records calls in order and serves vertex history back.

    Models post-graph's id semantics rather than papering over them: vertices
    get integer primary keys from a counter, and business ids such as
    `agt_writer` live in the payload. An earlier version of this fake accepted
    string ids happily, which let a refactor pass 30 tests while being broken
    against a real database.
    """

    # Business-key column per vertex table, matching registry_store.
    KEYS = {"agents": "agent_id", "pipelines": "pipeline_id",
            "prompts": "prompt_id", "pipeline_runs": "run_id"}

    def __init__(self):
        self.calls = []
        self.data = {}          # pk -> [payload, …] in write order
        self.vertices = {}      # (table, business_id) -> pk
        self.payloads = {}      # pk -> identity payload
        self.spaces = {}        # pk -> space
        self.tables = {}        # pk -> table
        self.edges = []         # (table, realm, from_id, to_id, relation, payload)
        self._next_pk = 1

    def _get_table_ref(self, table, realm):
        return f'"{realm}"."{table}"'

    @staticmethod
    def _table_of(query):
        return query.split('"."')[1].split('"')[0]

    async def _fetch(self, query, *args):
        """Dispatches on query shape, the way the real table would.

        A fake that answers every query identically lets a wrong query pass, so
        each shape registry_store issues is answered on its own terms.
        """
        table = self._table_of(query)

        # Edge read: which pipelines point at this agent (pipelines_pinning).
        if "from_id, payload FROM" in query:
            realm, to_id = args[0], args[1]
            return [{"from_id": f, "payload": p}
                    for t, r, f, to, _rel, p in self.edges
                    if t == table and r == realm and to == to_id]

        # Edge read: what this vertex points at (progeny_of over spawns).
        if "SELECT to_id FROM" in query:
            realm, from_id = args[0], args[1]
            return [{"to_id": to}
                    for t, r, f, to, _rel, _p in self.edges
                    if t == table and r == realm and f == from_id]

        # Edge read: full dependency rows, filtered by owning pipeline version.
        if "from_id, to_id, relation_type, payload FROM" in query:
            realm, version_id = args[0], args[1]
            return [{"from_id": f, "to_id": to, "relation_type": rel, "payload": p}
                    for t, r, f, to, rel, p in self.edges
                    if t == table and r == realm
                    and p.get("pipeline_version_id") == version_id]

        # Identity payload by primary key.
        if "SELECT payload FROM" in query and "id = $2" in query:
            pk = args[1]
            return [{"payload": self.payloads[pk]}] if pk in self.payloads else []

        # A single projected column by primary key (current_version, pipeline_id…).
        if "AS pid" in query or "AS v" in query or "AS aid" in query:
            pk = args[1]
            payload = self.payloads.get(pk, {})
            if "AS pid" in query:
                return [{"pid": payload.get("pipeline_id")}]
            if "AS aid" in query:
                return [{"aid": payload.get("agent_id")}]
            return [{"v": payload.get("current_version")}]

        # Slug ownership within (realm, space).
        if "payload->>'slug'" in query:
            realm, space, slug = args[0], args[1], args[2]
            key = self.KEYS.get(table, "agent_id")
            for pk, payload in self.payloads.items():
                if self.tables.get(pk) == table and self.spaces.get(pk) == space \
                        and payload.get("slug") == slug:
                    return [{"owner": payload.get(key)}]
            return []

        # Prompt identity lookup (no space filter).
        if "payload->>'prompt_id'" in query:
            prompt_id = args[1]
            pk = self.vertices.get((table, prompt_id))
            return [{"id": pk}] if pk else []

        # Listing every vertex in a realm, optionally one space.
        if "SELECT id, payload FROM" in query:
            space = args[1] if len(args) > 1 else None
            return [{"id": pk, "payload": self.payloads[pk]}
                    for pk in sorted(self.payloads)
                    if self.tables.get(pk) == table
                    and (space is None or self.spaces.get(pk) == space)]

        # Default: resolve a business id to a pk, optionally within a space.
        business_id = args[1]
        space = args[2] if len(args) > 2 else None
        pk = self.vertices.get((table, business_id))
        if pk is None:
            return []
        if space is not None and self.spaces.get(pk) != space:
            return []
        return [{"id": pk}]

    async def upsert_vertex(self, table, realm=None, vertex_id=None, space=None,
                            payload=None, embedding=None):
        self.calls.append(("upsert_vertex", table, vertex_id))
        self.payloads[vertex_id] = payload
        self.tables[vertex_id] = table
        if space is not None:
            self.spaces[vertex_id] = space

    async def create_vertex_table(self, table, realm=None, vector_dim=None):
        self.calls.append(("create_vertex_table", table))

    async def create_edge_table(self, table, from_vertex_table=None, to_vertex_table=None, realm=None):
        self.calls.append(("create_edge_table", table))

    async def add_vertex(self, table, realm=None, space=None, vertex_id=None, payload=None, embedding=None):
        pk = self._next_pk
        self._next_pk += 1
        key = payload.get(self.KEYS.get(table, "agent_id"))
        self.vertices[(table, key)] = pk
        self.payloads[pk] = payload
        self.tables[pk] = table
        self.spaces[pk] = space
        self.calls.append(("add_vertex", table, key))
        return type("V", (), {"id": pk})()

    async def add_vertex_data(self, table_name=None, realm=None, vertex_id=None, payload=None):
        self.calls.append(("add_vertex_data", vertex_id, payload.get("status"), payload.get("version")))
        self.data.setdefault(vertex_id, []).append(payload)

    async def get_vertex_data(self, table_name=None, realm=None, vertex_id=None):
        # post-graph returns newest first; registry_store relies on that to pick
        # the current record for a version.
        return [{"payload": p} for p in reversed(self.data.get(vertex_id, []))]

    async def add_edge(self, table, realm=None, from_id=None, to_id=None,
                       relation_type=None, space=None, payload=None, check_cycle=None):
        assert relation_type, "Rule 5.1: relation_type is required on every edge"
        self.edges.append((table, realm, from_id, to_id, relation_type, payload or {}))
        self.calls.append(("add_edge", table, from_id, to_id, relation_type,
                           (payload or {}).get("is_back_edge")))


IDENTITY = {"name": "A", "slug": "a", "telos": "t", "description": "d"}


async def _seed_agents(c, names, version="1.0.0"):
    for n in names:
        await register_agent_version(c, "org", "proj", {**IDENTITY, "slug": n},
                                     agent(name=n, version=version))


def _pipeline(steps, deps, entry, **kw):
    return PipelineVersionSpec(
        pipeline_id="pln_p", version="1.0.0",
        steps={s: StepBinding(version_id=f"agv_{s}_1.0.0") for s in steps},
        dependencies=[StepDependency(from_step=a, to_step=b, **d) for a, b, d in deps],
        entry_steps=entry, input_schema=OBJ, output_schema=OBJ, **kw)


# ------------------------------------------------------------------ agents

@pytest.mark.asyncio
async def test_agent_version_is_written_as_history_not_a_vertex():
    c = FakeClient()
    await _seed_agents(c, ["a"])
    assert ("add_vertex", AGENTS, "a") in c.calls
    pk = c.vertices[(AGENTS, "a")]
    # The version is history against the vertex's integer pk, not a vertex.
    assert any(k == "add_vertex_data" and v == pk for k, v, *_ in c.calls)
    assert not any(t == "agent_versions" for k, t, *_ in c.calls if k == "add_vertex")


@pytest.mark.asyncio
async def test_republishing_identical_content_is_allowed():
    """Same version, same hash: an idempotent retry must not be an error."""
    c = FakeClient()
    await _seed_agents(c, ["a"])
    await _seed_agents(c, ["a"])


@pytest.mark.asyncio
async def test_editing_a_published_version_is_rejected():
    c = FakeClient()
    await register_agent_version(c, "org", "proj", IDENTITY, agent(name="a"))
    changed = agent(name="a", prompt="different behaviour entirely")
    with pytest.raises(RegistrationError, match="Rule 3.3"):
        await register_agent_version(c, "org", "proj", IDENTITY, changed)


@pytest.mark.asyncio
async def test_duplicate_content_under_a_new_version_is_rejected():
    c = FakeClient()
    await register_agent_version(c, "org", "proj", IDENTITY, agent(name="a", version="1.0.0"))
    with pytest.raises(RegistrationError, match="Rule 4.2"):
        await register_agent_version(c, "org", "proj", IDENTITY, agent(name="a", version="1.0.1"))


@pytest.mark.asyncio
async def test_spawn_edge_records_provenance():
    c = FakeClient()
    # The parent must already be registered: an edge endpoint is a pk, so an
    # unregistered parent has no id to point at and is rejected rather than
    # silently skipped. Distinct slugs, because one slug identifies one thing
    # (§9 rejection 9).
    await register_agent_version(c, "org", "proj", {**IDENTITY, "slug": "parent"},
                                 agent(name="agt_parent"))
    await register_agent_version(c, "org", "proj", {**IDENTITY, "slug": "child"},
                                 agent(name="child"), spawned_by="agt_parent")
    parent_pk = c.vertices[(AGENTS, "agt_parent")]
    child_pk = c.vertices[(AGENTS, "child")]
    assert ("add_edge", "spawns", parent_pk, child_pk, "spawned", None) in c.calls


@pytest.mark.asyncio
async def test_spawned_by_an_unknown_agent_is_rejected():
    """Provenance that points nowhere is worse than no provenance."""
    c = FakeClient()
    with pytest.raises(RegistrationError, match="unknown agent"):
        await register_agent_version(c, "org", "proj", IDENTITY, agent(name="child"),
                                     spawned_by="agt_ghost")


# ---------------------------------------------------------------- pipelines

@pytest.mark.asyncio
async def test_publish_marker_is_written_last():
    """The atomicity argument: edges must all precede the published record."""
    c = FakeClient()
    await _seed_agents(c, ["a", "b"])
    await register_pipeline_version(c, "org", "proj", IDENTITY,
                                    _pipeline(["a", "b"], [("a", "b", {})], ["a"]))
    kinds = [k for k, *_ in c.calls]
    pipeline_pk = c.vertices[(PIPELINES, "pln_p")]
    statuses = [(i, s) for i, (k, _v, s, *_) in enumerate(c.calls)
                if k == "add_vertex_data" and _v == pipeline_pk]
    draft_i = next(i for i, s in statuses if s == "draft")
    published_i = next(i for i, s in statuses if s == "published")
    last_edge_i = max(i for i, k in enumerate(kinds) if k == "add_edge")
    assert draft_i < last_edge_i < published_i


@pytest.mark.asyncio
async def test_pin_travels_in_the_edge_payload():
    c = FakeClient()
    await _seed_agents(c, ["a"])
    await register_pipeline_version(c, "org", "proj", IDENTITY, _pipeline(["a"], [], ["a"]))
    composes = [x for x in c.calls if x[0] == "add_edge" and x[1] == COMPOSES]
    assert composes
    assert composes[0][2] == c.vertices[(PIPELINES, "pln_p")]
    assert composes[0][3] == c.vertices[(AGENTS, "a")]


@pytest.mark.asyncio
async def test_back_edge_is_marked_on_the_dependency():
    c = FakeClient()
    await _seed_agents(c, ["a", "b"])
    spec = _pipeline(["a", "b"],
                     [("a", "b", {}), ("b", "a", {"relationship": "on_condition"})],
                     ["a"], execution=ExecutionPolicy(max_iterations=5))
    await register_pipeline_version(c, "org", "proj", IDENTITY, spec)
    deps = [x for x in c.calls if x[0] == "add_edge" and x[1] == STEP_DEPENDENCY]
    assert [d[5] for d in deps] == [False, True]


@pytest.mark.asyncio
async def test_unpublished_pin_is_rejected_before_any_write():
    """Validation precedes the identity upsert, so a bad pipeline writes nothing."""
    c = FakeClient()
    with pytest.raises(RegistrationError, match="Rule 4.3"):
        await register_pipeline_version(c, "org", "proj", IDENTITY,
                                        _pipeline(["ghost"], [], ["ghost"]))
    assert not any(k == "add_vertex" for k, *_ in c.calls)


# ------------------------------------------------------------------ parsing

def test_version_id_splits_on_the_last_underscore():
    assert _split_version_id("agv_agt_corpus_researcher_7f3a_3.1.0") == \
        ("agt_corpus_researcher_7f3a", "3.1.0")


def test_malformed_version_id_is_rejected():
    with pytest.raises(RegistrationError):
        _split_version_id("nonsense")
