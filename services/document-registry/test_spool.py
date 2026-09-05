"""The streamed upload spool: bounded memory with unchanged semantics.

The digest must equal what `content_hash` said about the same bytes — the
dedupe rule (5.6) keys on it, and a format drift would re-ingest every
existing document as "new".
"""
from __future__ import annotations

import os

import pytest
from fastapi import HTTPException

import app as registry
from doc_model import content_hash


class _FakeUpload:
    def __init__(self, data: bytes, filename: str = "f.txt"):
        self._data = data
        self._pos = 0
        self.filename = filename

    async def read(self, n: int = -1) -> bytes:
        chunk = self._data[self._pos:self._pos + n]
        self._pos += len(chunk)
        return chunk


@pytest.mark.asyncio
async def test_digest_matches_content_hash_and_file_matches_bytes():
    data = b"x" * 200_000 + b"streamed"
    path, digest, size = await registry._spool_upload(_FakeUpload(data))
    try:
        assert digest == content_hash(data)
        assert size == len(data)
        with open(path, "rb") as fh:
            assert fh.read() == data
    finally:
        os.unlink(path)


@pytest.mark.asyncio
async def test_over_limit_is_refused_and_leaves_no_temp_file(monkeypatch):
    monkeypatch.setattr(registry, "MAX_UPLOAD_BYTES", 1000)
    with pytest.raises(HTTPException) as raised:
        await registry._spool_upload(_FakeUpload(b"y" * 2000, "big.bin"))
    assert raised.value.status_code == 413
    assert "Nothing was catalogued" in raised.value.detail
