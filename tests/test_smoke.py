"""Harness smoke tests: the real stack is genuinely up before anything relies on it.

If these fail, every other failure in the suite is noise.
"""
import pytest

from conftest import CHAT_MODEL, EMBEDDING_MODEL, ROUTER, ROUTER_KEY, requires_stack

pytestmark = [pytest.mark.e2e, requires_stack]


async def test_the_model_router_is_the_real_one(router_url):
    """No stub: this is LiteLLM, serving the models the services default to."""
    import httpx
    async with httpx.AsyncClient(timeout=30) as http:
        res = await http.get(f"{router_url.rstrip('/')}/models",
                             headers={"Authorization": f"Bearer {ROUTER_KEY}"})
    assert res.status_code == 200
    served = {m["id"] for m in res.json()["data"]}
    assert CHAT_MODEL in served
    assert EMBEDDING_MODEL in served


async def test_real_embeddings_have_the_dimension_the_schema_declares():
    """AG §3 declares vector(1536). A mismatch surfaces as a pgvector error at
    query time, far from the config that caused it — so it is checked here.

    The width is asked for explicitly rather than accepted: several embedding
    models can return more than one, and which they default to is a provider
    decision that can change, while the column cannot.

    **Normalisation is deliberately not asserted.** `gemini-embedding-001`
    returns vectors with a norm around 0.7, where `text-embedding-3-small`
    returns unit vectors — and it does not matter, because every search here
    uses pgvector's cosine operator, which normalises as part of the distance.
    Asserting unit length would fail a perfectly good model and invite someone
    to "fix" it by normalising vectors the database is about to normalise
    again.
    """
    import math

    import httpx
    async with httpx.AsyncClient(timeout=60) as http:
        res = await http.post(
            f"{ROUTER.rstrip('/')}/embeddings",
            headers={"Authorization": f"Bearer {ROUTER_KEY}"},
            json={"model": EMBEDDING_MODEL, "dimensions": 1536,
                  "input": "summarise quarterly regulatory filings"})
    assert res.status_code == 200, res.text
    vector = res.json()["data"][0]["embedding"]
    assert len(vector) == 1536
    # Non-degenerate: a zero vector has no direction and cosine distance
    # against it is undefined.
    assert math.sqrt(sum(v * v for v in vector)) > 0.1


async def test_real_embeddings_discriminate_between_unrelated_work():
    """The premise every discovery test rests on, checked against the real model."""
    import httpx

    async def embed(text: str):
        async with httpx.AsyncClient(timeout=60) as http:
            res = await http.post(
                f"{ROUTER.rstrip('/')}/embeddings",
                headers={"Authorization": f"Bearer {ROUTER_KEY}"},
                json={"model": EMBEDDING_MODEL, "dimensions": 1536, "input": text})
            return res.json()["data"][0]["embedding"]

    def cosine(a, b):
        return sum(x * y for x, y in zip(a, b))

    filings = await embed("Summarises quarterly regulatory filings and "
                          "extracts disclosure obligations.")
    invoices = await embed("Reconciles supplier invoices against purchase "
                           "orders and flags mismatches.")
    query = await embed("I need something that can summarise a regulatory filing")

    assert cosine(query, filings) > cosine(query, invoices)


async def test_the_real_chat_model_answers_and_reports_usage():
    """The metering path bills from provider-reported usage, so it must be there."""
    import httpx
    async with httpx.AsyncClient(timeout=120) as http:
        res = await http.post(
            f"{ROUTER.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {ROUTER_KEY}"},
            json={"model": CHAT_MODEL, "max_tokens": 20, "temperature": 0,
                  "messages": [
                      {"role": "system", "content": "Reply with exactly the word READY."},
                      {"role": "user", "content": "Are you there?"}]})
    assert res.status_code == 200
    body = res.json()
    assert "READY" in body["choices"][0]["message"]["content"].upper()
    assert body["usage"]["prompt_tokens"] > 0
    assert body["usage"]["completion_tokens"] > 0


async def test_all_three_services_are_listening_on_real_ports(stack):
    import httpx
    for name, service in stack.items():
        async with httpx.AsyncClient(timeout=30) as http:
            res = await http.get(f"{service.url}/health")
        assert res.status_code == 200, name
        assert res.json()["database"] == "ok", name


async def test_the_services_report_their_real_dependencies(tools, agents, documents):
    assert (await tools.get("/health")).json()["service"] == "tool-registry"

    agent_health = (await agents.get("/health")).json()
    assert agent_health["schema_per_realm"] is True

    document_health = (await documents.get("/health")).json()
    assert document_health["docling"] == "ok"
    assert document_health["embedding_dim"] == 1536


async def test_a_realm_is_a_real_postgresql_schema(tools, db, realm):
    """AG §2 — physical isolation is a schema, not a column. Prove it."""
    from conftest import tool_body

    res = await tools.post("/tools/register", json=tool_body(
        org=realm, tool_id="mcp-probe", name="Probe",
        description="A probe tool.", endpoint="http://x.svc.cluster.local/probe"))
    assert res.status_code == 200, res.text

    tables = await db.fetch(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = $1",
        realm)
    names = {r["table_name"] for r in tables}
    assert "mcp_tools" in names
    assert "mcp_tools_data" in names          # the version history table exists
