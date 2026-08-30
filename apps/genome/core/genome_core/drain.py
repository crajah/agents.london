"""The store-backed drain: one due event in, effects persisted, next event
scheduled. This is the tick worker's inner loop and the in-cluster smoke's
engine — the same code path, so the smoke proves the worker.

system-spec Rule 8.4: nothing here calls a model. A decision that needs one is
resolved by the injected decider — the stub in Phase 1, a queue handoff to the
kagent casts in Phase 2.
"""
from __future__ import annotations

import json
import uuid as uuidlib

from . import engine, forms
from .store import GenomeStore


def _iso(t: float) -> str:
    # virtual-clock ISO: fixed-width seconds since epoch sorts lexically,
    # matching due_events' string comparison
    return f"{t:020.3f}"


def from_iso(s: str) -> float:
    return float(s)


async def load_agent(store: GenomeStore, world_realm: str, agent_uuid: str,
                     home_realm: str, now: float) -> tuple[engine.AgentView, dict]:
    """View + the agent's stored payload (genotype, knowledge). Position is
    derived from the latest movement intent and the clock — never stored
    (execution-spec Rule 2.2)."""
    rows = await store._c.find_vertices("agents", realm="genome_agents",
                                        filters={"key": agent_uuid}, limit=1)
    payload = rows[0].payload if rows else {}
    latest = await store.latest_movement(agent_uuid)
    cargo: dict[str, float] = {}
    x, y = engine.HOME_XY
    if latest is not None:
        pl = latest.payload
        cargo = pl.get("cargo", {})
        if "waypoints" in pl:
            r = forms.Route(tuple(tuple(q) for q in pl["waypoints"]),
                            pl["departed_at"])
            x, y = forms.route_position(r, now)
    view = engine.AgentView(
        agent_uuid, home_realm, world_realm, x, y, cargo,
        frozenset(payload.get("known_piles", [])),
        frozenset(tuple(c) for c in payload.get("explored", [])))
    return view, payload


async def persist_effects(store: GenomeStore, world_realm: str,
                          agent: engine.AgentView, eff: engine.Effects,
                          piles_meta: dict, now: float) -> None:
    if eff.movement:
        await store.set_movement(agent.agent_uuid,
                                 {**eff.movement, "cargo": agent.cargo})
    if eff.mine_pile:
        pile_uuid, want = eff.mine_pile
        m = piles_meta[pile_uuid]
        p = forms.PileState(m["qty_at"], m.get("measured_at", 0.0), m["rate"], m["cap"])
        p2, _taken = forms.mine(p, now, want)
        await store.put_pile(world_realm, pile_uuid,
                             {**m, "qty_at": p2.qty_at, "measured_at": now})
    if eff.cargo_delta:
        cargo = dict(agent.cargo)
        for kind, d in eff.cargo_delta.items():
            cargo[kind] = cargo.get(kind, 0.0) + d
            if cargo[kind] <= 1e-9:
                del cargo[kind]
        # cargo rides on the movement history record (append-only)
        await store.set_movement(agent.agent_uuid,
                                 {"waypoints": [[agent.x, agent.y]],
                                  "departed_at": now, "arrives_at": now,
                                  "cargo": cargo})
    if eff.deposit:
        await _bump_stock(store, world_realm, eff.deposit)   # stock on world_meta
    if eff.schedule:
        kind, due, subject, payload = eff.schedule
        await store.schedule(world_realm, f"ev-{uuidlib.uuid4().hex[:10]}",
                             _iso(due), kind, subject, payload)


async def _bump_stock(store: GenomeStore, world_realm: str,
                      accepted: dict[str, float]) -> None:
    rows = await store._c.find_vertices("world_meta", realm=world_realm,
                                        filters={"key": world_realm}, limit=1)
    payload = rows[0].payload if rows else {"key": world_realm}
    stock = payload.get("stock", {})
    for kind, units in accepted.items():
        stock[kind] = stock.get(kind, 0.0) + units
    await store.put_world(world_realm, {**payload, "stock": stock})


async def get_stock(store: GenomeStore, world_realm: str) -> dict:
    rows = await store._c.find_vertices("world_meta", realm=world_realm,
                                        filters={"key": world_realm}, limit=1)
    return (rows[0].payload.get("stock", {}) if rows else {})


async def drain_one(store: GenomeStore, world_realm: str, home_realm: str,
                    ev, decider, seed: int) -> str:
    """Process one due event vertex. Returns the choice or event kind."""
    pl = ev.payload
    now = from_iso(pl["due_at"])
    agent_uuid = pl["subject"]
    agent, agent_payload = await load_agent(store, world_realm, agent_uuid,
                                            home_realm, now)
    pile_rows = await store.piles_in(world_realm)
    piles_meta = {v.payload["key"]: v.payload for v in pile_rows}
    pile_views = [engine.PileView(
        k, m["kind"], m["x"], m["y"],
        forms.pile_quantity(forms.PileState(m["qty_at"], m.get("measured_at", 0.0),
                                            m["rate"], m["cap"]), now))
        for k, m in piles_meta.items()]
    terrain = (await _world_payload(store, world_realm)).get("terrain", [])
    stock = await get_stock(store, world_realm)

    if pl["kind"] == "deposit_arrival":
        eff = engine.on_deposit_arrival(agent, stock, now)
        outcome = "deposit"
    else:
        res = engine.on_event(pl["kind"], agent, pile_views, now,
                              pl.get("payload", {}), stock)
        if isinstance(res, engine.DecisionRequest):
            decided = decider(res, agent_payload, seed)
            # a decider may return (Choice, model_name) or a bare Choice
            choice, model = decided if isinstance(decided, tuple) \
                else (decided, "stub")
            await store.record_decision(agent_uuid, {
                "at": pl["due_at"], "situation": res.situation,
                "options": list(res.options), "choice": choice.option,
                "model": model, "tier": "economy" if model != "stub" else "stub"})
            eff = engine.apply_choice(choice, agent, pile_views, now,
                                      pl.get("payload", {}), terrain)
            outcome = choice.option
        else:
            eff = res
            outcome = pl["kind"]
    await persist_effects(store, world_realm, agent, eff, piles_meta, now)
    if eff.reveal or eff.mark_explored:      # knowledge grows on the agent
        kp = sorted(set(agent_payload.get("known_piles", [])) | set(eff.reveal))
        ex = sorted({tuple(c) for c in agent_payload.get("explored", [])}
                    | set(eff.mark_explored))
        await store.put_agent(agent.agent_uuid,
                              {**agent_payload, "known_piles": kp,
                               "explored": [list(c) for c in ex]})
    await store.complete_event(world_realm, ev.payload["key"], _iso(now))
    return outcome


async def _world_payload(store: GenomeStore, world_realm: str) -> dict:
    rows = await store._c.find_vertices("world_meta", realm=world_realm,
                                        filters={"key": world_realm}, limit=1)
    return rows[0].payload if rows else {}
