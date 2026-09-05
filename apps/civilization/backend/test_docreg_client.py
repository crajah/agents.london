"""The doc-registry client helper must produce a real client.

A refactor once rewrote the `httpx.AsyncClient(` call *inside* the helper
into a call to the helper itself — infinite recursion, so every document
upload died in RecursionError and the UI reported the registry unreachable.
These tests hold the two properties that matter: it returns an actual
httpx client, and the internal token rides along exactly when provisioned.
"""
from __future__ import annotations

import httpx

import main


def test_returns_a_real_httpx_client(monkeypatch):
    monkeypatch.delenv("DOCREG_INTERNAL_TOKEN", raising=False)
    client = main._docreg_client(timeout=1.0)
    assert isinstance(client, httpx.AsyncClient)


def test_token_rides_as_header_when_provisioned(monkeypatch):
    monkeypatch.setenv("DOCREG_INTERNAL_TOKEN", "sekrit")
    client = main._docreg_client(timeout=1.0)
    assert isinstance(client, httpx.AsyncClient)
    assert client.headers.get("x-internal-token") == "sekrit"


def test_no_header_when_unset(monkeypatch):
    monkeypatch.delenv("DOCREG_INTERNAL_TOKEN", raising=False)
    client = main._docreg_client(timeout=1.0)
    assert "x-internal-token" not in client.headers


def test_upload_text_query_route_reaches_the_real_handler():
    """A stray @app.post on the UploadTextBody *class* once shadowed this
    route: the model's __init__ became the endpoint and every UI upload
    422'd. Reaching the real handler means either a 200 (registry up) or
    the honest 502 from its except block -- never a validation error when
    the query params are present."""
    from fastapi.testclient import TestClient
    client = TestClient(main.app)
    r = client.post(
        "/api/projects/p1/spaces/default/documents/upload-text",
        params={"document_name": "t.txt", "content": "hello"})
    assert r.status_code != 422
