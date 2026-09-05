"""Quotas: one enforcement point, refusals that name the number.

Unset limits mean unlimited -- the platform's internal surface is untouched
until limits are deliberately provisioned. A refusal is a 402 stating usage,
limit, and period; never a dressed-up server error.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import app as registry
import doc_store
from doc_model import SpaceKey

KEY = SpaceKey(org_id="org_q", project_id="proj_q", document_space="default")


class _Stub:
    def __init__(self, plan=None, used_bytes=0, used_events=0, docs=0):
        self.plan = plan
        self.used = {"bytes": used_bytes, "events": used_events}
        self.docs = docs


def _wire(monkeypatch, stub: _Stub):
    monkeypatch.setattr(registry, "_client", lambda: object())
    async def org_plan(client, org_id):
        return stub.plan
    async def usage(client, org_id, kind):
        return dict(stub.used)
    async def count(client, org_id, project_id):
        return stub.docs
    monkeypatch.setattr(doc_store, "org_plan", org_plan)
    monkeypatch.setattr(doc_store, "usage_month_to_date", usage)
    monkeypatch.setattr(doc_store, "count_documents", count)


@pytest.mark.asyncio
async def test_no_limits_means_no_refusal(monkeypatch):
    _wire(monkeypatch, _Stub(used_bytes=10**12, used_events=10**6, docs=10**6))
    monkeypatch.setattr(registry, "QUOTA_INGEST_MB", 0)
    monkeypatch.setattr(registry, "QUOTA_QUERIES", 0)
    monkeypatch.setattr(registry, "QUOTA_DOCUMENTS", 0)
    await registry._enforce_quota(KEY, adding_bytes=1, adding_query=True)


@pytest.mark.asyncio
async def test_ingest_over_quota_is_a_402_naming_the_numbers(monkeypatch):
    _wire(monkeypatch, _Stub(used_bytes=5 * 1024 * 1024))
    monkeypatch.setattr(registry, "QUOTA_INGEST_MB", 5)
    with pytest.raises(HTTPException) as raised:
        await registry._enforce_quota(KEY, adding_bytes=1024)
    assert raised.value.status_code == 402
    assert "5MB of 5MB" in raised.value.detail
    assert "Nothing was catalogued" in raised.value.detail


@pytest.mark.asyncio
async def test_org_plan_overrides_the_default_tier(monkeypatch):
    _wire(monkeypatch, _Stub(plan={"quota_ingest_mb": 100},
                             used_bytes=6 * 1024 * 1024))
    monkeypatch.setattr(registry, "QUOTA_INGEST_MB", 5)
    # default tier would refuse at 5MB; the plan raises it to 100MB
    await registry._enforce_quota(KEY, adding_bytes=1024)


@pytest.mark.asyncio
async def test_query_quota(monkeypatch):
    _wire(monkeypatch, _Stub(used_events=50))
    monkeypatch.setattr(registry, "QUOTA_QUERIES", 50)
    with pytest.raises(HTTPException) as raised:
        await registry._enforce_quota(KEY, adding_query=True)
    assert raised.value.status_code == 402
    assert "50 of 50" in raised.value.detail


@pytest.mark.asyncio
async def test_document_count_quota(monkeypatch):
    _wire(monkeypatch, _Stub(docs=3))
    monkeypatch.setattr(registry, "QUOTA_DOCUMENTS", 3)
    with pytest.raises(HTTPException) as raised:
        await registry._enforce_quota(KEY, adding_bytes=1)
    assert raised.value.status_code == 402
    assert "3 of 3" in raised.value.detail
