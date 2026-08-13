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

    def __init__(self):
        self.calls = []
        self.data = {}          # pk -> [payload, …] in write order
        self.vertices = {}      # (table, business_id) -> pk
        self.payloads = {}      # pk -> identity payload
        self._next_pk = 1

    def _get_table_ref(self, table, realm):
        return f'"{realm}"."{table}"'

    async def _fetch(self, query, *args):
        """Only ever asked one question: resolve a business id to a pk."""
        realm, business_id = args[0], args[1]
        table = query.split('"."')[1].split('"')[0]
        pk = self.vertices.get((table, business_id))
        return [{"id": pk}] if pk else []

    async def upsert_vertex(self, table, realm=None, vertex_id=None, space=None,
                            payload=None, embedding=None):
        self.calls.append(("upsert_vertex", table, vertex_id))
        self.payloads[vertex_id] = payload

    async def create_vertex_table(self, table, realm=None, vector_dim=None):
        self.calls.append(("create_vertex_table", table))

    async def create_edge_table(self, table, from_vertex_table=None, to_vertex_table=None, realm=None):
        self.calls.append(("create_edge_table", table))

    async def add_vertex(self, table, realm=None, space=None, vertex_id=None, payload=None, embedding=None):
        pk = self._next_pk
        self._next_pk += 1
        key = payload.get("agent_id") or payload.get("pipeline_id")
        self.vertices[(table, key)] = pk
        self.payloads[pk] = payload
        self.calls.append(("add_vertex", table, key))
        return type("V", (), {"id": pk})()

    async def add_vertex_data(self, table_name=None, realm=None, vertex_id=None, payload=None):
        self.calls.append(("add_vertex_data", vertex_id, payload.get("status"), payload.get("version")))
        self.data.setdefault(vertex_id, []).append(payload)

    async def get_vertex_data(self, table_name=None, realm=None, vertex_id=None):
        return [{"payload": p} for p in self.data.get(vertex_id, [])]

    async def add_edge(self, table, realm=None, from_id=None, to_id=None,
                       relation_type=None, space=None, payload=None, check_cycle=None):
        assert relation_type, "Rule 5.1: relation_type is required on every edge"
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
    # silently skipped.
    await register_agent_version(c, "org", "proj", IDENTITY, agent(name="agt_parent"))
    await register_agent_version(c, "org", "proj", IDENTITY, agent(name="child"),
                                 spawned_by="agt_parent")
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
