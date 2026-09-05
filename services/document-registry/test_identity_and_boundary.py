"""The fixes of 2026-09-05, pinned.

Identity: flattening a filename must never merge two documents. Boundary:
the retained text and storage key never leave the API. Caps: an oversized
text body is refused honestly, before anything is catalogued.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

import app as registry
from doc_model import document_id, legacy_document_id


def test_lossy_filenames_get_distinct_ids():
    a = document_id("p", "s", "report v1.pdf")
    b = document_id("p", "s", "report_v1.pdf")
    assert a != b
    # the already-safe name keeps the unhashed, legacy-compatible id
    assert b == legacy_document_id("p", "s", "report_v1.pdf")


def test_safe_filenames_keep_their_pre_fix_identity():
    assert document_id("p", "s", "notes.txt") == \
        legacy_document_id("p", "s", "notes.txt")


def test_two_lossy_names_that_flatten_alike_stay_distinct():
    assert document_id("p", "s", "a b.pdf") != document_id("p", "s", "a\tb.pdf")


def test_public_boundary_strips_storage_fields():
    doc = {"filename": "f.txt", "_pk": 7, "_text": "retained words",
           "index": {"status": "indexed"}}
    out = registry._public(doc)
    assert "_pk" not in out and "_text" not in out
    assert out["retained_text"] is True
    assert out["filename"] == "f.txt"


def test_oversized_text_body_is_refused_before_ingest(monkeypatch):
    monkeypatch.setattr(registry, "MAX_UPLOAD_BYTES", 100)
    client = TestClient(registry.app)
    r = client.post("/spaces/default/documents/upload-text",
                    json={"org_id": "org_t", "project_id": "p",
                          "document_name": "big.txt",
                          "content": "x" * 500})
    assert r.status_code == 413
    assert "Nothing was catalogued" in r.json()["detail"]
