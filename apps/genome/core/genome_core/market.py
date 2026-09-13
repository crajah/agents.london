"""The marketplace — genome-spec §4.5. One board per world; listings are
escrowed bid/ask pairs, filling is binding and atomic, proceeds wait for
collection in person, the flood takes the board.

Storage: `market_listings` vertex table in the world's realm.
Listing payload: {key, lister, lister_user, give, want, proceeds,
status: open|filled|collected|withdrawn, listed_at, filled_by, filled_at}
"""
from __future__ import annotations

import time
import uuid as uuidlib
from typing import Any

from . import notify

TABLE = "market_listings"
MARKET_REACH = 0.035


async def board(client: Any, realm: str) -> list[dict]:
    """Only rows that still matter travel: open listings plus filled ones
    awaiting collection -- history stays in the database."""
    out = []
    for status in ("open", "filled"):
        try:
            rows = await client.find_vertices(TABLE, realm=realm,
                                              filters={"status": status},
                                              limit=200)
        except Exception:
            continue
        out.extend(v.payload for v in rows)
    return out


async def recent_deals(client: Any, realm: str, limit: int = 12) -> list[dict]:
    """Completed trades for the ticker (user directive 2026-09-13): the board
    shows live bid/ask, this shows deals DONE. Collected listings, newest
    first -- what changed hands and between whom."""
    try:
        rows = await client.find_vertices(TABLE, realm=realm,
                                          filters={"status": "collected"},
                                          limit=200)
    except Exception:
        return []
    deals = sorted((v.payload for v in rows),
                   key=lambda l: l.get("filled_at", 0.0), reverse=True)
    return deals[:limit]


def open_listings(listings: list[dict]) -> list[dict]:
    return [l for l in listings if l.get("status") == "open"]


def fillable(listings: list[dict], cargo: dict[str, float],
             me: str) -> list[dict]:
    """Listings whose ask this hold can pay -- one's own excluded."""
    out = []
    for l in open_listings(listings):
        if l.get("lister") == me:
            continue
        if all(cargo.get(k, 0.0) + 1e-9 >= u
               for k, u in l.get("want", {}).items()):
            out.append(l)
    return out


def summary(listings: list[dict], me: str) -> list[dict]:
    """What deliberation sees: the open board plus my uncollected proceeds."""
    out = []
    for l in listings:
        if l.get("status") == "open":
            out.append({"key": l["key"], "give": l["give"],
                        "want": l["want"],
                        "mine": l.get("lister") == me})
        elif l.get("status") == "filled" and l.get("lister") == me:
            out.append({"key": l["key"], "proceeds": l.get("proceeds", {}),
                        "mine": True, "awaiting_collection": True})
    return out


async def _row(client: Any, realm: str, key: str):
    rows = await client.find_vertices(TABLE, realm=realm,
                                      filters={"key": key}, limit=1)
    return rows[0] if rows else None


async def post(client: Any, realm: str, lister: str, lister_user: str,
               give: dict[str, float], want: dict[str, float],
               cargo: dict[str, float]) -> dict:
    """Escrow at the moment of listing (Rule 4.20): no goods, no listing."""
    give = {str(k): float(u) for k, u in (give or {}).items() if float(u) > 0}
    want = {str(k): float(u) for k, u in (want or {}).items() if float(u) > 0}
    if not give or not want:
        return {"error": "a listing is a bid AND an ask"}
    for k, u in give.items():
        if cargo.get(k, 0.0) + 1e-9 < u:
            return {"error": f"you hold {cargo.get(k, 0.0):.1f} of kind {k}, "
                    f"not {u:.1f} -- no goods, no listing"}
    key = f"lst-{uuidlib.uuid4().hex[:10]}"
    await client.add_vertex(TABLE, realm=realm, payload={
        "key": key, "lister": lister, "lister_user": lister_user,
        "give": give, "want": want, "proceeds": {},
        "status": "open", "listed_at": time.time()})
    escrowed = dict(cargo)
    for k, u in give.items():
        escrowed[k] -= u
        if escrowed[k] <= 1e-9:
            del escrowed[k]
    return {"ok": True, "key": key, "cargo_after": escrowed}


async def fill(client: Any, realm: str, key: str, filler: str,
               cargo: dict[str, float],
               lister_present: bool = True,
               lister_cargo: dict[str, float] | None = None) -> dict:
    """Binding, atomic, HAND-TO-HAND (Rule 4.22 revised): both parties at
    the stall, the ask paid into the lister's hands, the escrow taken, one
    act. A fill without the lister present waits -- the board summons."""
    row = await _row(client, realm, key)
    if row is None or row.payload.get("status") != "open":
        return {"error": "that listing is gone"}
    l = row.payload
    if l.get("lister") == filler:
        return {"error": "you cannot fill your own listing"}
    if not lister_present:
        if l.get("lister_user"):
            notify.emit_bg(client, l["lister_user"], "agents",
                           "buyer_waiting",
                           "A buyer stands at the market wanting your "
                           "listing -- your agent must attend to close it.")
        return {"error": "the lister is not at the stall; the trade waits"}
    for k, u in l["want"].items():
        if cargo.get(k, 0.0) + 1e-9 < u:
            return {"error": "you cannot pay the ask"}
    await client.upsert_vertex(TABLE, realm=realm, vertex_id=int(row.id),
                               space="default",
                               payload={**l, "status": "collected",
                                        "proceeds": {},
                                        "filled_by": filler,
                                        "filled_at": time.time()})
    after = dict(cargo)
    for k, u in l["want"].items():
        after[k] -= u
        if after[k] <= 1e-9:
            del after[k]
    for k, u in l["give"].items():
        after[k] = after.get(k, 0.0) + u
    lister_after = dict(lister_cargo or {})
    for k, u in l["want"].items():
        lister_after[k] = lister_after.get(k, 0.0) + u
    if l.get("lister_user"):
        notify.emit_bg(client, l["lister_user"], "agents", "listing_filled",
                       f"Hands shook at the stall: your agent's listing "
                       f"cleared for {l['want']}.")
    return {"ok": True, "cargo_after": after,
            "lister_cargo_after": lister_after,
            "received": dict(l["give"])}


async def reserve(client: Any, realm: str, key: str, filler: str,
                  filler_user: str, filler_cargo: dict[str, float]) -> dict:
    """Accept ANYWHERE (user directive 2026-09-14): agreeing to a listing is a
    world-public act -- it needs no co-location. It reserves the listing (open ->
    agreed) for this filler; the two then rendezvous and the swap SETTLES only
    when they meet (see settle). The lister's `give` is already escrowed at post;
    the filler's `want` is checked here and taken at settle, so it can't be spent
    away meanwhile without failing the settle."""
    row = await _row(client, realm, key)
    if row is None or row.payload.get("status") != "open":
        return {"error": "that listing is gone"}
    l = row.payload
    if l.get("lister") == filler:
        return {"error": "you cannot fill your own listing"}
    for k, u in l["want"].items():
        if filler_cargo.get(k, 0.0) + 1e-9 < u:
            return {"error": "you cannot pay the ask"}
    await client.upsert_vertex(TABLE, realm=realm, vertex_id=int(row.id),
                               space="default",
                               payload={**l, "status": "agreed",
                                        "filled_by": filler,
                                        "filler_user": filler_user,
                                        "agreed_at": time.time()})
    return {"ok": True, "lister": l["lister"], "lister_user": l.get("lister_user"),
            "give": dict(l["give"]), "want": dict(l["want"])}


async def settle(client: Any, realm: str, key: str, filler: str,
                 filler_cargo: dict[str, float],
                 lister_cargo: dict[str, float]) -> dict:
    """Execute an AGREED trade once the two have met (proximity checked by the
    caller). Atomic swap: the filler pays `want` and receives the escrowed
    `give`; the lister receives `want`. open->agreed->collected."""
    row = await _row(client, realm, key)
    if row is None or row.payload.get("status") != "agreed" \
            or row.payload.get("filled_by") != filler:
        return {"error": "the agreed trade is gone"}
    l = row.payload
    for k, u in l["want"].items():
        if filler_cargo.get(k, 0.0) + 1e-9 < u:
            return {"error": "the filler can no longer pay the ask"}
    await client.upsert_vertex(TABLE, realm=realm, vertex_id=int(row.id),
                               space="default",
                               payload={**l, "status": "collected",
                                        "proceeds": {}, "filled_at": time.time()})
    after = dict(filler_cargo)
    for k, u in l["want"].items():
        after[k] = after.get(k, 0.0) - u
        if after[k] <= 1e-9:
            del after[k]
    for k, u in l["give"].items():
        after[k] = after.get(k, 0.0) + u
    lister_after = dict(lister_cargo)
    for k, u in l["want"].items():
        lister_after[k] = lister_after.get(k, 0.0) + u
    if l.get("lister_user"):
        notify.emit_bg(client, l["lister_user"], "agents", "listing_filled",
                       f"Hands met away from any stall: your listing cleared "
                       f"for {l['want']}.")
    return {"ok": True, "cargo_after": after,
            "lister_cargo_after": lister_after, "received": dict(l["give"])}


async def release(client: Any, realm: str, key: str) -> dict:
    """Rendezvous failed (a party strayed, died, or the wait expired): re-open
    the agreed listing so others can accept it. Escrow was never touched."""
    row = await _row(client, realm, key)
    if row is None or row.payload.get("status") != "agreed":
        return {"error": "nothing to release"}
    l = dict(row.payload)
    l.pop("filled_by", None)
    l.pop("filler_user", None)
    l.pop("agreed_at", None)
    await client.upsert_vertex(TABLE, realm=realm, vertex_id=int(row.id),
                               space="default",
                               payload={**l, "status": "open"})
    return {"ok": True}


async def record_barter(client: Any, realm: str, a: str, a_user: str,
                        b: str, b_user: str, a_gives: dict[str, float],
                        b_gives: dict[str, float], now: float) -> dict:
    """Document an encounter-negotiated barter in the market ledger (user
    directive 2026-09-14: ALL trades are tracked in the marketplace). This is not
    an escrowed listing -- the goods already changed hands in the negotiation --
    but a COLLECTED record so the exchange shows in the deals ticker/history
    alongside board trades. `give` = what `a` handed over, `want` = what `a`
    received (i.e. what `b` gave)."""
    key = f"barter-{uuidlib.uuid4().hex[:10]}"
    await client.add_vertex(TABLE, realm=realm, payload={
        "key": key, "lister": a, "lister_user": a_user,
        "give": {str(k): float(u) for k, u in (a_gives or {}).items()},
        "want": {str(k): float(u) for k, u in (b_gives or {}).items()},
        "proceeds": {}, "status": "collected",
        "filled_by": b, "filler_user": b_user,
        "listed_at": now, "filled_at": now, "source": "barter"})
    return {"ok": True, "key": key}


async def collect(client: Any, realm: str, key: str, lister: str,
                  cargo: dict[str, float]) -> dict:
    row = await _row(client, realm, key)
    if row is None or row.payload.get("status") != "filled" \
            or row.payload.get("lister") != lister:
        return {"error": "nothing of yours to collect there"}
    l = row.payload
    await client.upsert_vertex(TABLE, realm=realm, vertex_id=int(row.id),
                               space="default",
                               payload={**l, "status": "collected"})
    after = dict(cargo)
    for k, u in l.get("proceeds", {}).items():
        after[k] = after.get(k, 0.0) + u
    return {"ok": True, "cargo_after": after,
            "collected": dict(l.get("proceeds", {}))}


async def withdraw(client: Any, realm: str, key: str, lister: str,
                   cargo: dict[str, float]) -> dict:
    row = await _row(client, realm, key)
    if row is None or row.payload.get("status") != "open" \
            or row.payload.get("lister") != lister:
        return {"error": "not yours to withdraw"}
    l = row.payload
    await client.upsert_vertex(TABLE, realm=realm, vertex_id=int(row.id),
                               space="default",
                               payload={**l, "status": "withdrawn"})
    after = dict(cargo)
    for k, u in l["give"].items():
        after[k] = after.get(k, 0.0) + u
    return {"ok": True, "cargo_after": after}


async def flood_wipe(client: Any, realm: str) -> int:
    """Rule 4.23: the water takes the board -- escrow and proceeds drown."""
    n = 0
    try:
        rows = await client.get_vertices(TABLE, realm=realm)
    except Exception:
        return 0
    for v in rows:
        if v.payload.get("status") in ("open", "filled"):
            await client.upsert_vertex(TABLE, realm=realm,
                                       vertex_id=int(v.id), space="default",
                                       payload={**v.payload,
                                                "status": "drowned"})
            n += 1
    return n
