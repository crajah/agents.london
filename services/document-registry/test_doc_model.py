"""Tests for the namespace, identity and extraction rules.

Run: python3 -m pytest services/document-registry -q

These import doc_model / doc_extract directly rather than app.py, which raises
at import without OPENAI_API_KEY (Rule 10.2) and needs post-graph-rag >= 1.5.2.
"""
import pytest

from doc_extract import extract
from doc_model import (
    ACTIVE, FAILED, INDEXED, CreateSpaceRequest, DocumentError, ExtractionResult,
    IndexOutcome, RAGQueryRequest, SpaceKey, UploadTextRequest, catalogue_entry,
    content_hash, document_id, normalise_document_space, now,
)


# ----------------------------------------------------------------- namespace

def test_the_three_tiers_are_distinct():
    """realm=org_id, space=project_id, document_space below both (Rule 2.1)."""
    key = SpaceKey(org_id="org_a", project_id="proj_a", document_space="legal_contracts")
    assert key.org_id == "org_a"
    assert key.project_id == "proj_a"
    assert key.document_space == "legal_contracts"
    assert key.key == "proj_a:legal_contracts"


def test_document_space_defaults_but_project_does_not():
    key = SpaceKey(project_id="proj_a")
    assert key.document_space == "default"
    assert key.org_id == "org_default"
    with pytest.raises(Exception):
        SpaceKey(org_id="org_a")


def test_document_space_must_be_a_slug():
    """Rule 3.1 — it appears in URL paths and in RAG metadata filters."""
    for bad in ("Engineering Docs", "docs/legal", "UPPER", "a b"):
        with pytest.raises(DocumentError, match="Rule 3.1"):
            normalise_document_space(bad)


def test_reasonable_document_space_names_are_accepted():
    for good in ("default", "engineering_docs", "q3-reports", "a", "x1"):
        assert normalise_document_space(good) == good


# --------------------------------------------------------- request aliasing

def test_space_name_and_document_space_are_the_same_field():
    """The backend sends space_name; document_space is canonical."""
    a = CreateSpaceRequest(project_id="p", space_name="engineering_docs")
    b = CreateSpaceRequest(project_id="p", document_space="engineering_docs")
    assert a.document_space == b.document_space == "engineering_docs"
    assert a.space_name == b.space_name == "engineering_docs"


def test_create_space_requires_a_name():
    with pytest.raises(Exception):
        CreateSpaceRequest(project_id="p")


def test_upload_defaults_to_the_default_document_space():
    req = UploadTextRequest(project_id="p", document_name="d", content="c")
    assert req.document_space == "default"


def test_an_unscoped_query_stays_project_wide():
    """Rule 2.3 — absent must not become 'default', which would silently
    narrow every unscoped query to one folder."""
    req = RAGQueryRequest(project_id="p", query="q")
    assert req.document_space is None
    assert req.space_name is None


def test_a_scoped_query_keeps_its_scope():
    req = RAGQueryRequest(project_id="p", query="q", space_name="legal_contracts")
    assert req.document_space == "legal_contracts"


# ------------------------------------------------------------------ identity

def test_document_identity_is_project_space_and_filename():
    """Rule 7.1 — the org is the schema, so it is not repeated in the id."""
    one = document_id("proj_a", "docs", "rfc-42.pdf")
    assert one == "doc_proj_a_docs_rfc-42.pdf"
    assert document_id("proj_a", "docs", "rfc-42.pdf") == one
    assert document_id("proj_b", "docs", "rfc-42.pdf") != one
    assert document_id("proj_a", "other", "rfc-42.pdf") != one


def test_awkward_filenames_are_flattened_into_a_vertex_id():
    assert "/" not in document_id("p", "s", "a/b c.pdf")
    assert " " not in document_id("p", "s", "a/b c.pdf")


def test_content_hash_is_of_the_bytes_not_the_text():
    """Rule 5.3 — the question is 'have I ingested this exact artefact'."""
    assert content_hash(b"abc") == content_hash(b"abc")
    assert content_hash(b"abc") != content_hash(b"abd")
    assert content_hash(b"abc").startswith("sha256:")


def test_timestamps_are_iso_not_monotonic_floats():
    """Rule 3.4 — a monotonic float means nothing across a restart."""
    stamp = now()
    assert isinstance(stamp, str)
    assert stamp.startswith("20") and "T" in stamp


# ------------------------------------------------------------------ outcomes

def test_index_success_and_failure_are_different_states():
    ok = IndexOutcome.succeeded({"chunks": 3, "entities": 7})
    bad = IndexOutcome.failed("boom")
    assert ok.status == INDEXED and ok.chunks == 3 and ok.error is None
    assert bad.status == FAILED and bad.error == "boom"


def test_catalogue_entry_carries_both_names_and_the_index_state():
    key = SpaceKey(org_id="org_a", project_id="proj_a", document_space="docs")
    entry = catalogue_entry(
        key=key, filename="a.pdf", digest="sha256:x", size=10,
        extraction=ExtractionResult(method="docling", text="hello world!!", characters=13),
        index=IndexOutcome.failed("embedding down"))
    assert entry["document_space"] == entry["space_name"] == "docs"
    assert entry["index"]["status"] == FAILED
    assert entry["lifecycle"] == ACTIVE
    assert entry["revision"] == 1
    # Fields the frontend reads.
    assert entry["content_length"] == 13
    assert entry["extraction_method"] == "docling"


# ---------------------------------------------------------------- extraction

def test_plain_text_is_extracted_by_the_first_parser_that_can():
    """The ladder is ordered, and Docling is first (§5.1).

    Which rung wins depends on what is installed, and that is the point of a
    ladder — so this asserts the text came out and the method was recorded,
    not which parser happened to claim it.
    """
    result = extract(b"This is a real document with content.", "notes.txt")
    assert "real document" in result.text
    assert result.method in {"docling", "utf8_text_reader"}
    assert result.characters == len(result.text)


def test_the_utf8_reader_catches_what_the_structured_parsers_decline():
    """The last rung is reached, rather than the ladder falling through to a
    failure, when the parsers above it cannot read the file."""
    result = extract(b'{"note": "a json document the structured parsers skip"}',
                     "data.json")
    assert result.method == "utf8_text_reader"
    assert "json document" in result.text


def test_binary_that_no_parser_reads_is_rejected():
    """Rule 5.3 — no placeholder, no repr of the bytes, no catalogue entry."""
    with pytest.raises(DocumentError, match="Rule 5.3"):
        extract(b"\x00\x01\x02\xff\xfe binary junk \x00", "mystery.bin")


def test_rejection_names_the_file_and_says_nothing_was_stored():
    with pytest.raises(DocumentError) as excinfo:
        extract(b"\xff\xfe\x00\x01", "broken.dat")
    message = str(excinfo.value)
    assert "broken.dat" in message
    assert "not been catalogued" in message


def test_a_near_empty_extraction_is_not_a_success():
    """Rule 5.1 — whitespace or a few characters is not a document."""
    with pytest.raises(DocumentError):
        extract(b"  \n  ", "empty.txt")


def test_invalid_utf8_is_not_silently_mangled():
    """Rule 5.2 — errors='ignore' turned any binary file into indexable mojibake."""
    latin = "café".encode("latin-1") + b"\xff\xfe\x00"
    with pytest.raises(DocumentError):
        extract(latin, "mixed.bin")


# ------------------------------------------- reading the engine's own reply

def test_index_outcome_reads_post_graph_rags_real_field_names():
    """`index_document` returns counts under its own names, and `entities` as
    a list of names — reading the wrong one turned a success into a failure."""
    from doc_model import IndexOutcome as IO
    raw = {"document_id": 41, "entities_extracted": 3, "triples_extracted": 5,
           "relations_added": 4, "mentions_added": 3,
           "entities": ["Northwind", "Barclays", "March"]}
    outcome = IO.succeeded(raw)
    assert outcome.status == "indexed"
    assert outcome.chunks == 1            # one call indexes one chunk
    assert outcome.entities == 3
    assert outcome.relationships == 4


def test_index_outcome_survives_a_list_where_a_count_was_expected():
    from doc_model import IndexOutcome as IO
    outcome = IO.succeeded({"entities": ["a", "b"], "relationships": ["x"]})
    assert outcome.entities == 2
    assert outcome.relationships == 1


def test_index_outcome_survives_an_empty_reply():
    from doc_model import IndexOutcome as IO
    outcome = IO.succeeded({})
    assert outcome.status == "indexed"
    assert outcome.chunks == 0
