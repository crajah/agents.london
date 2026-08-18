#!/usr/bin/env python3
"""Re-embed stored vectors after the embedding model changes.

Changing `RAG_EMBEDDING_MODEL` does not fail. text-embedding-3-small and
gemini-embedding-001 are both 1536 dimensions, so every stored vector still
loads, every query still runs, and every distance is meaningless — the old
vectors and the new query vector are points in two unrelated geometries.
Retrieval degrades to something close to random and reports nothing wrong. This
is the tool that closes that window.

It re-embeds in place. It does not delete anything, and it does not re-extract:
entities, relations and the graph between them are the expensive part and they
do not depend on the embedding model. Only the vectors are recomputed, from
text that is already stored.

The text each row is embedded from is reconstructed with the same formulas
post-graph-rag 1.5.2 uses at index time, because a vector built from different
text than the library builds at query time is as wrong as a vector from the
wrong model:

    documents   text
    entities    "{name} ({type}): {description}" [+ " Also known as: …"]
    relations   "{subject} {predicate} {object}. {description}"

Dry run by default. `--apply` is required to write anything.

    python3 scripts/reindex_embeddings.py --dsn "$POSTGRES_URI"
    python3 scripts/reindex_embeddings.py --dsn "$POSTGRES_URI" --apply
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

import asyncpg
import httpx

ROUTER = os.getenv("OPENAI_API_BASE", os.getenv("LITELLM_URL", "http://localhost:4000/v1"))
ROUTER_KEY = os.getenv("OPENAI_API_KEY", "")
MODEL = os.getenv("RAG_EMBEDDING_MODEL", "gemini-embedding-001")
DIM = int(os.getenv("RAG_EMBEDDING_DIM", "1536"))

# The library embeds relations only when configured to. A realm that has no
# relation vectors is left alone rather than gaining ones it never had.
STATE_TABLE = "_reindex_state"


def backup_name(table: str) -> str:
    """Where a table's previous vectors are kept.

    Overwriting an embedding destroys it: there is no way to recompute a
    text-embedding-3-small vector once the model is gone from the deployment,
    and no way to tell from the row that it was ever different. Keeping the old
    one costs a copy of a float array and turns an irreversible operation into
    a reversible one.
    """
    return f"_embedding_backup_{table}"

SYSTEM_SCHEMAS = ("information_schema", "pg_catalog", "pg_toast", "public")


# ------------------------------------------------------------ embedding text

def document_text(payload: Dict[str, Any]) -> Optional[str]:
    text = payload.get("text")
    return text if isinstance(text, str) and text.strip() else None


def entity_text(payload: Dict[str, Any]) -> Optional[str]:
    name = payload.get("name")
    if not name:
        return None
    text = f"{name} ({payload.get('type', '')}): {payload.get('description', '')}"
    aliases = payload.get("aliases")
    if isinstance(aliases, str):
        # Stored as the repr of a list by an older writer. Parsed rather than
        # embedded verbatim: "['TBA', 'TBA securities']" is not what the
        # library embeds, and a vector built from it sits somewhere unrelated.
        try:
            aliases = json.loads(aliases.replace("'", '"'))
        except (ValueError, AttributeError):
            aliases = None
    if aliases:
        text += f" Also known as: {', '.join(aliases)}."
    return text


def relation_text(payload: Dict[str, Any], subject: str, predicate: str,
                  obj: str) -> Optional[str]:
    if not (subject and obj):
        return None
    return f"{subject} {predicate} {obj}. {payload.get('description') or ''}".strip()


# ------------------------------------------------------------------ embedding

async def embed_batch(http: httpx.AsyncClient, texts: Sequence[str]) -> List[List[float]]:
    """Embed a batch, or raise. Never returns a placeholder vector.

    A zero vector or a reused one would be written to the database and would
    look exactly like a real embedding for as long as anyone cared to look.
    """
    body = {"model": MODEL, "input": list(texts)}
    if DIM:
        body["dimensions"] = DIM
    res = await http.post(f"{ROUTER.rstrip('/')}/embeddings",
                          headers={"Authorization": f"Bearer {ROUTER_KEY}"},
                          json=body)
    if res.status_code != 200:
        raise RuntimeError(f"embedding call returned {res.status_code}: {res.text[:200]}")
    data = res.json()["data"]
    if len(data) != len(texts):
        raise RuntimeError(f"asked for {len(texts)} embeddings, got {len(data)}")
    return [row["embedding"] for row in sorted(data, key=lambda d: d["index"])]


# --------------------------------------------------------------------- state

async def ensure_backup(conn, schema: str, table: str) -> int:
    """Preserve the current vectors before any are overwritten.

    Idempotent: a second run adds only rows that are not already saved, so a
    resumed run never overwrites the original backup with vectors it has just
    written itself.
    """
    backup = backup_name(table)
    await conn.execute(f'''
        CREATE TABLE IF NOT EXISTS "{schema}"."{backup}" (
            id bigint PRIMARY KEY,
            embedding vector,
            saved_at timestamptz NOT NULL DEFAULT now()
        )''')
    return await conn.fetchval(f'''
        INSERT INTO "{schema}"."{backup}" (id, embedding)
        SELECT id, embedding FROM "{schema}"."{table}"
        WHERE embedding IS NOT NULL
        ON CONFLICT (id) DO NOTHING
        RETURNING 1''') or 0


async def rollback_table(conn, schema: str, table: str) -> int:
    """Put the saved vectors back."""
    backup = backup_name(table)
    exists = await conn.fetchval("""
        SELECT 1 FROM information_schema.tables
        WHERE table_schema=$1 AND table_name=$2""", schema, backup)
    if not exists:
        return 0
    result = await conn.execute(f'''
        UPDATE "{schema}"."{table}" t SET embedding = b.embedding
        FROM "{schema}"."{backup}" b WHERE b.id = t.id''')
    await conn.execute(
        f'DELETE FROM "{schema}"."{STATE_TABLE}" WHERE table_name=$1', table)
    return int(result.split()[-1])


async def ensure_state(conn, schema: str) -> None:
    await conn.execute(f'''
        CREATE TABLE IF NOT EXISTS "{schema}"."{STATE_TABLE}" (
            table_name text PRIMARY KEY,
            model      text NOT NULL,
            last_id    bigint NOT NULL DEFAULT 0,
            done       bigint NOT NULL DEFAULT 0,
            updated_at timestamptz NOT NULL DEFAULT now()
        )''')


async def resume_from(conn, schema: str, table: str) -> int:
    row = await conn.fetchrow(
        f'SELECT last_id, model FROM "{schema}"."{STATE_TABLE}" WHERE table_name=$1', table)
    if row is None or row["model"] != MODEL:
        # A different model means the previous run's progress does not apply.
        return 0
    return int(row["last_id"])


async def record(conn, schema: str, table: str, last_id: int, done: int) -> None:
    await conn.execute(f'''
        INSERT INTO "{schema}"."{STATE_TABLE}" (table_name, model, last_id, done)
        VALUES ($1,$2,$3,$4)
        ON CONFLICT (table_name) DO UPDATE
        SET model=$2, last_id=$3, done="{STATE_TABLE}".done+$4, updated_at=now()
    ''', table, MODEL, last_id, done)


# ------------------------------------------------------------------ discovery

async def embedded_tables(conn, schemas: Optional[Sequence[str]]) -> List[Tuple[str, str]]:
    rows = await conn.fetch("""
        SELECT c.table_schema, c.table_name
        FROM information_schema.columns c
        JOIN information_schema.tables t
          ON t.table_schema=c.table_schema AND t.table_name=c.table_name
        WHERE c.column_name='embedding' AND c.udt_name='vector'
          AND t.table_type='BASE TABLE'
          AND c.table_schema <> ALL($1::text[])
          AND c.table_name NOT LIKE '%\\_audit'
        ORDER BY 1,2""", list(SYSTEM_SCHEMAS))
    found = [(r["table_schema"], r["table_name"]) for r in rows]
    if schemas:
        wanted = set(schemas)
        found = [f for f in found if f[0] in wanted]
    return found


async def relation_endpoints(conn, schema: str, table: str) -> Dict[int, Tuple[str, str, str]]:
    """subject, predicate, object for each relation edge, from its endpoints."""
    try:
        rows = await conn.fetch(f'''
            SELECT r.id,
                   s.payload->>'name' AS subject,
                   r.relation_type    AS predicate,
                   o.payload->>'name' AS object
            FROM "{schema}"."{table}" r
            LEFT JOIN "{schema}"."entities" s ON s.id = r.from_id
            LEFT JOIN "{schema}"."entities" o ON o.id = r.to_id''')
    except asyncpg.PostgresError as e:
        print(f"    ! cannot resolve endpoints ({e}); skipping {schema}.{table}")
        return {}
    return {r["id"]: (r["subject"] or "", r["predicate"] or "", r["object"] or "")
            for r in rows}


# ------------------------------------------------------------------- the work

async def reindex_table(conn, http, schema: str, table: str, *, apply: bool,
                        batch: int, backup: bool = True) -> Dict[str, int]:
    total = await conn.fetchval(
        f'SELECT count(*) FROM "{schema}"."{table}" WHERE embedding IS NOT NULL')
    if not total:
        return {"total": 0, "updated": 0, "skipped": 0}

    if apply and backup:
        saved = await ensure_backup(conn, schema, table)
        if saved:
            print(f"    {schema}.{table}: {total} previous vectors saved to "
                  f"{backup_name(table)}")

    endpoints = (await relation_endpoints(conn, schema, table)
                 if table == "relations" else {})
    start = await resume_from(conn, schema, table) if apply else 0
    updated = skipped = 0
    last_id = start

    while True:
        rows = await conn.fetch(
            f'''SELECT id, payload FROM "{schema}"."{table}"
                WHERE embedding IS NOT NULL AND id > $1
                ORDER BY id LIMIT $2''', last_id, batch)
        if not rows:
            break

        pending: List[Tuple[int, str]] = []
        for row in rows:
            payload = row["payload"]
            if isinstance(payload, str):
                payload = json.loads(payload)
            if table == "documents":
                text = document_text(payload)
            elif table == "entities":
                text = entity_text(payload)
            elif table == "relations":
                subject, predicate, obj = endpoints.get(row["id"], ("", "", ""))
                text = relation_text(payload, subject, predicate, obj)
            else:
                text = document_text(payload) or entity_text(payload)
            if text:
                pending.append((row["id"], text))
            else:
                # Left exactly as it was. A row whose source text cannot be
                # reconstructed keeps its old vector rather than gaining a
                # wrong one, and is reported so the gap is known.
                skipped += 1

        last_id = rows[-1]["id"]

        if pending and apply:
            vectors = await embed_batch(http, [t for _, t in pending])
            async with conn.transaction():
                await conn.executemany(
                    f'UPDATE "{schema}"."{table}" SET embedding=$2::vector WHERE id=$1',
                    [(rid, str(vec)) for (rid, _), vec in zip(pending, vectors)])
                await record(conn, schema, table, last_id, len(pending))
            updated += len(pending)
        elif pending:
            updated += len(pending)          # what a dry run would have done

        if sys.stdout.isatty():
            print(f"    {schema}.{table}: {updated}/{total}"
                  + (f" ({skipped} unreconstructable)" if skipped else ""), end="\r")

    print(f"    {schema}.{table}: {updated}/{total} "
          + (f"({skipped} unreconstructable)" if skipped else "") + " " * 20)
    return {"total": total, "updated": updated, "skipped": skipped}


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dsn", default=os.getenv("POSTGRES_URI"),
                        help="PostgreSQL connection string")
    parser.add_argument("--schema", action="append",
                        help="limit to this realm schema (repeatable)")
    parser.add_argument("--apply", action="store_true",
                        help="write the new vectors; without this it reports only")
    parser.add_argument("--batch", type=int, default=64)
    parser.add_argument("--no-backup", action="store_true",
                        help="do not preserve the vectors being overwritten")
    parser.add_argument("--rollback", action="store_true",
                        help="restore the vectors saved by an earlier --apply")
    args = parser.parse_args()

    if not args.dsn:
        print("no --dsn and no POSTGRES_URI", file=sys.stderr)
        return 2

    print(f"model  {MODEL} ({DIM} dimensions)")
    print(f"router {ROUTER}")
    print(f"mode   {'APPLY — vectors will be rewritten' if args.apply else 'dry run'}\n")

    conn = await asyncpg.connect(args.dsn)
    try:
        tables = await embedded_tables(conn, args.schema)
        if not tables:
            print("nothing with a vector column")
            return 0

        by_schema: Dict[str, List[str]] = {}
        for schema, table in tables:
            by_schema.setdefault(schema, []).append(table)

        if args.rollback:
            restored = 0
            for schema, names in by_schema.items():
                for table in names:
                    n = await rollback_table(conn, schema, table)
                    if n:
                        print(f"  {schema}.{table}: {n} vectors restored")
                    restored += n
            print(f"\nrestored {restored} vectors from backup")
            return 0

        totals = {"total": 0, "updated": 0, "skipped": 0}
        async with httpx.AsyncClient(timeout=300.0) as http:
            for schema, names in by_schema.items():
                print(f"  {schema}")
                if args.apply:
                    await ensure_state(conn, schema)
                for table in names:
                    got = await reindex_table(conn, http, schema, table,
                                              apply=args.apply, batch=args.batch,
                                              backup=not args.no_backup)
                    for k in totals:
                        totals[k] += got[k]

        print(f"\n{'rewrote' if args.apply else 'would rewrite'} "
              f"{totals['updated']} of {totals['total']} vectors"
              + (f", {totals['skipped']} left as they were"
                 if totals["skipped"] else ""))
        if not args.apply:
            print("dry run — nothing was written. Re-run with --apply.")
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
