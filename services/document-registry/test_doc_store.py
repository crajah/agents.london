"""Catalogue tests against a fake post-graph client.

The claims under test are all about *which realm and space a write lands in*
and *how many writes happen*, so the fake records both.
"""
import pytest

import doc_store
from doc_model import (
    ACTIVE, WITHDRAWN, DocumentError, ExtractionResult, IndexOutcome, SpaceKey,
    catalogue_entry,
)


class FakeClient:
    def __init__(self):
        self.calls = []
        self.rows = {}      # pk -> (table, realm, space, payload)
        self.data = {}      # (table, pk) -> [payload, …]
        self._next_pk = 1

    def _get_table_ref(self, table, realm):
        return f'"{realm}"."{table}"'

    def _table_of(self, query):
        return query.split('"."')[1].split('"')[0]

    async def _fetch(self, query, *args):
        table = self._table_of(query)
        if "document_space" in query and "payload->>'document_space'" in query:
            realm, space, name = args
            return [{"id": pk, "payload": p}
                    for pk, (t, r, s, p) in sorted(self.rows.items())
                    if t == table and r == realm and s == space
                    and p.get("document_space") == name]
        if "NOT IN ('withdrawn', 'erased')" in query or "LIMIT $" in query \
                or "OFFSET $" in query:
            # the paged listing: realm, space, [document_space], [limit], [offset]
            realm, space = args[0], args[1]
            rest = list(args[2:])
            wanted_space = rest.pop(0) if "payload->>'document_space' = $" in query else None
            limit = rest.pop(0) if "LIMIT $" in query else None
            offset = rest.pop(0) if "OFFSET $" in query else 0
            rows = [{"id": pk, "payload": p}
                    for pk, (t, r, sp, p) in sorted(self.rows.items())
                    if t == table and r == realm and sp == space]
            if wanted_space is not None:
                rows = [x for x in rows
                        if x["payload"].get("document_space") == wanted_space]
            if "NOT IN ('withdrawn', 'erased')" in query:
                rows = [x for x in rows
                        if x["payload"].get("lifecycle", "active")
                        not in ("withdrawn", "erased")]
            rows = rows[offset:]
            return rows[:limit] if limit is not None else rows
        if "payload->>'content_hash'" in query:
            realm, space, digest = args
            return [{"id": pk, "payload": p}
                    for pk, (t, r, s, p) in sorted(self.rows.items())
                    if t == table and r == realm and s == space
                    and p.get("content_hash") == digest]
        if "payload->>'document_id'" in query:
            realm, space, doc_id = args
            return [{"id": pk, "payload": p}
                    for pk, (t, r, s, p) in sorted(self.rows.items())
                    if t == table and r == realm and s == space
                    and p.get("document_id") == doc_id]
        realm, space = args[0], args[1]
        return [{"id": pk, "payload": p}
                for pk, (t, r, s, p) in sorted(self.rows.items())
                if t == table and r == realm and s == space]

    async def create_vertex_table(self, table, realm=None, vector_dim=None):
        self.calls.append(("create_vertex_table", table, realm))

    async def add_vertex(self, table, realm=None, space=None, vertex_id=None,
                         payload=None, embedding=None):
        pk = self._next_pk
        self._next_pk += 1
        self.rows[pk] = (table, realm, space, dict(payload))
        self.calls.append(("add_vertex", table, realm, space))
        return type("V", (), {"id": pk})()

    async def upsert_vertex(self, table, realm=None, vertex_id=None, space=None,
                            payload=None, embedding=None):
        self.rows[vertex_id] = (table, realm, space, dict(payload))
        self.calls.append(("upsert_vertex", table, realm, space))

    async def delete_vertex(self, table, realm=None, vertex_id=None,
                            user_id=None):
        pk = int(vertex_id)
        self.rows.pop(pk, None)
        # cascade, as the real store does: data keys are (table, vertex_id)
        self.data = {k: v for k, v in getattr(self, "data", {}).items()
                     if k[1] != pk}
        return True

    async def add_vertex_data(self, table_name=None, realm=None, vertex_id=None,
                              payload=None):
        self.data.setdefault((table_name, vertex_id), []).append(dict(payload))
        self.calls.append(("add_vertex_data", table_name, realm))

    async def get_vertex_data(self, table_name=None, realm=None, vertex_id=None):
        return [{"payload": p} for p in self.data.get((table_name, vertex_id), [])]


KEY = SpaceKey(org_id="org_a", project_id="proj_a", document_space="engineering_docs")


def entry(filename="rfc-42.pdf", digest="sha256:aaa", index=None, chars=100):
    return catalogue_entry(
        key=KEY, filename=filename, digest=digest, size=2048,
        extraction=ExtractionResult(method="docling", text="x" * chars, characters=chars),
        index=index or IndexOutcome.succeeded({"chunks": 4}))


# ------------------------------------------------------------------ tenancy

@pytest.mark.asyncio
async def test_writes_land_in_realm_org_and_space_project():
    """Rule 2.1 — the document space is a payload field, never a post-graph space."""
    c = FakeClient()
    await doc_store.create_space(c, KEY, "d")
    writes = [x for x in c.calls if x[0] == "add_vertex"]
    assert writes == [("add_vertex", doc_store.SPACES, "org_a", "proj_a")]
    # And never the document space in the space slot.
    assert not any(x[3] == "engineering_docs" for x in c.calls if len(x) > 3)


@pytest.mark.asyncio
async def test_documents_are_scoped_to_their_project():
    c = FakeClient()
    await doc_store.save_document(c, KEY, entry())
    other = SpaceKey(org_id="org_a", project_id="proj_b", document_space="engineering_docs")
    await doc_store.save_document(c, other, entry())
    assert len(await doc_store.list_documents(c, "org_a", "proj_a")) == 1
    assert len(await doc_store.list_documents(c, "org_a", "proj_b")) == 1


# ------------------------------------------------------------------- spaces

@pytest.mark.asyncio
async def test_creating_a_space_twice_creates_one_space():
    """Rule 3.2 — a duplicate space silently splits a corpus in half."""
    c = FakeClient()
    a = await doc_store.create_space(c, KEY, "first")
    b = await doc_store.create_space(c, KEY, "second")
    assert a["space_key"] == b["space_key"]
    assert sum(1 for x in c.calls if x[0] == "add_vertex") == 1
    # The first description stands: creation is idempotent, not last-write-wins.
    assert b["description"] == "first"


@pytest.mark.asyncio
async def test_document_count_is_derived_not_stored():
    """Rule 3.3 — a stored counter drifts, and users see the drift."""
    c = FakeClient()
    await doc_store.create_space(c, KEY, "d")
    await doc_store.save_document(c, KEY, entry("a.pdf", "sha256:a"))
    await doc_store.save_document(c, KEY, entry("b.pdf", "sha256:b"))
    spaces = await doc_store.list_spaces(c, "org_a", "proj_a")
    assert spaces[0]["document_count"] == 2

    await doc_store.set_lifecycle(c, "org_a", "proj_a",
                                  entry("a.pdf")["document_id"], WITHDRAWN)
    spaces = await doc_store.list_spaces(c, "org_a", "proj_a")
    assert spaces[0]["document_count"] == 1


@pytest.mark.asyncio
async def test_a_space_created_only_by_upload_still_lists():
    c = FakeClient()
    await doc_store.save_document(c, KEY, entry())
    spaces = await doc_store.list_spaces(c, "org_a", "proj_a")
    assert [s["document_space"] for s in spaces] == ["engineering_docs"]
    assert spaces[0]["document_count"] == 1


@pytest.mark.asyncio
async def test_spaces_expose_both_names():
    c = FakeClient()
    await doc_store.create_space(c, KEY, "d")
    space = (await doc_store.list_spaces(c, "org_a", "proj_a"))[0]
    assert space["document_space"] == space["space_name"] == "engineering_docs"


# ---------------------------------------------------------------- revisions

@pytest.mark.asyncio
async def test_reuploading_a_filename_is_a_revision_not_a_second_document():
    """Rule 7.1 — identity is (org, project, document_space, filename)."""
    c = FakeClient()
    await doc_store.save_document(c, KEY, entry(digest="sha256:v1"))
    saved = await doc_store.save_document(c, KEY, entry(digest="sha256:v2"))
    assert saved["revision"] == 2
    assert len(await doc_store.list_documents(c, "org_a", "proj_a")) == 1


@pytest.mark.asyncio
async def test_every_revision_is_kept_in_the_data_table():
    """§3.3 — the record of what was indexed under that name last month survives."""
    c = FakeClient()
    first = await doc_store.save_document(c, KEY, entry(digest="sha256:v1"))
    await doc_store.save_document(c, KEY, entry(digest="sha256:v2"))
    revisions = await doc_store.revisions_of(c, "org_a", first["_pk"])
    assert [r["content_hash"] for r in revisions] == ["sha256:v1", "sha256:v2"]


@pytest.mark.asyncio
async def test_the_same_filename_in_another_document_space_is_another_document():
    c = FakeClient()
    await doc_store.save_document(c, KEY, entry())
    other = SpaceKey(org_id="org_a", project_id="proj_a", document_space="legal_docs")
    await doc_store.save_document(
        c, other,
        catalogue_entry(key=other, filename="rfc-42.pdf", digest="sha256:z", size=1,
                        extraction=ExtractionResult(method="docling", text="x", characters=1),
                        index=IndexOutcome.succeeded({})))
    assert len(await doc_store.list_documents(c, "org_a", "proj_a")) == 2


# ------------------------------------------------------------------- dedupe

@pytest.mark.asyncio
async def test_identical_bytes_are_found_by_hash():
    """Rule 5.6 — duplicate chunks compete in retrieval and degrade every answer."""
    c = FakeClient()
    await doc_store.save_document(c, KEY, entry(digest="sha256:same"))
    found = await doc_store.find_by_hash(c, "org_a", "proj_a", "engineering_docs",
                                         "sha256:same")
    assert found and found["content_hash"] == "sha256:same"
    assert await doc_store.find_by_hash(c, "org_a", "proj_a", "engineering_docs",
                                        "sha256:other") is None


# ---------------------------------------------------------------- lifecycle

@pytest.mark.asyncio
async def test_withdrawal_retains_the_record():
    """Rule 7.3 — the record explains why last month's run cited this document."""
    c = FakeClient()
    saved = await doc_store.save_document(c, KEY, entry())
    await doc_store.set_lifecycle(c, "org_a", "proj_a", saved["document_id"], WITHDRAWN)
    assert await doc_store.list_documents(c, "org_a", "proj_a") == []
    retained = await doc_store.list_documents(c, "org_a", "proj_a",
                                              include_withdrawn=True)
    assert len(retained) == 1
    assert retained[0]["lifecycle"] == WITHDRAWN


@pytest.mark.asyncio
async def test_withdrawing_an_unknown_document_is_an_error():
    c = FakeClient()
    with pytest.raises(DocumentError, match="unknown document"):
        await doc_store.set_lifecycle(c, "org_a", "proj_a", "doc_ghost", WITHDRAWN)


@pytest.mark.asyncio
async def test_index_outcome_can_be_updated_after_a_reindex():
    c = FakeClient()
    saved = await doc_store.save_document(
        c, KEY, entry(index=IndexOutcome.failed("embedding down")))
    assert saved["index"]["status"] == "failed"
    updated = await doc_store.update_index_outcome(
        c, "org_a", "proj_a", saved["document_id"],
        IndexOutcome.succeeded({"chunks": 9}).model_dump(mode="json"))
    assert updated["index"]["status"] == "indexed"
    assert updated["index"]["chunks"] == 9


@pytest.mark.asyncio
async def test_a_failed_index_is_still_catalogued():
    """Rule 4.1 + Rule 6.2 — extracted means catalogued; indexed is separate."""
    c = FakeClient()
    saved = await doc_store.save_document(
        c, KEY, entry(index=IndexOutcome.failed("boom")))
    listed = await doc_store.list_documents(c, "org_a", "proj_a")
    assert len(listed) == 1
    assert listed[0]["index"]["status"] == "failed"
    assert listed[0]["index"]["error"] == "boom"
    assert saved["lifecycle"] == ACTIVE


# ------------------------------------------------------- row unwrapping

class Record:
    """Stands in for `asyncpg.Record`: indexable by column, and not a dict.

    This is the shape the real database returns. A guard of
    `isinstance(row, dict)` is False for it, which is how `_payload` came to
    return `{}` for every real row while every test using dict rows passed —
    and `create_space` appended a duplicate space on every call as a result.
    """

    def __init__(self, columns):
        self._columns = dict(columns)

    def __getitem__(self, key):
        return self._columns[key]

    def keys(self):
        return self._columns.keys()


def test_payload_unwraps_an_asyncpg_record():
    row = Record({"id": 1, "payload": {"document_space": "eng"}})
    assert doc_store._payload(row) == {"document_space": "eng"}


def test_payload_unwraps_a_json_string_column():
    row = Record({"id": 1, "payload": '{"document_space": "eng"}'})
    assert doc_store._payload(row) == {"document_space": "eng"}


def test_payload_unwraps_a_plain_dict_row():
    assert doc_store._payload({"payload": {"a": 1}}) == {"a": 1}


def test_payload_accepts_a_bare_payload_dict():
    assert doc_store._payload({"document_space": "eng"}) == {"document_space": "eng"}


@pytest.mark.asyncio
async def test_creating_a_space_twice_against_record_rows_creates_one():
    """The integration regression, reproduced at unit speed."""
    class RecordClient(FakeClient):
        async def _fetch(self, query, *args):
            rows = await super()._fetch(query, *args)
            return [Record(r) for r in rows]

    c = RecordClient()
    a = await doc_store.create_space(c, KEY, "first")
    b = await doc_store.create_space(c, KEY, "second")
    assert a["space_key"] == b["space_key"]
    assert b["description"] == "first"
    assert sum(1 for x in c.calls if x[0] == "add_vertex") == 1


async def test_erasure_leaves_a_content_free_tombstone():
    c = FakeClient()
    saved = await doc_store.save_document(c, KEY, entry())
    doc_id = saved["document_id"]
    tomb = await doc_store.erase_document(c, "org_a", "proj_a", doc_id)
    assert tomb["lifecycle"] == "erased"
    assert tomb["revisions_erased"] >= 1
    assert "_text" not in tomb and "filename" not in tomb
    # erased documents leave the default listing
    docs = await doc_store.list_documents(c, "org_a", "proj_a")
    assert all(d.get("document_id") != doc_id or
               d.get("lifecycle") == "erased" for d in docs)
    listed = [d for d in docs if d.get("lifecycle") != "erased"]
    assert doc_id not in [d.get("document_id") for d in listed]


async def test_listing_pages():
    c = FakeClient()
    for i in range(5):
        await doc_store.save_document(c, KEY, entry(filename=f"f{i}.txt"))
    page = await doc_store.list_documents(c, "org_a", "proj_a", limit=2, offset=2)
    assert len(page) == 2
