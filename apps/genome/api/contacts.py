"""Contact import — system-spec Rules 9.2–9.5.

A second, separate consent: login never asks for contacts; importing does,
via incremental OAuth on the same clients. The address book is read ONCE,
hashed, matched against existing users, and the plaintext discarded in the
same request — a non-user's address is never stored (Rule 9.3). Matches
become PROPOSALS; only mutual confirmation links two worlds (Rule 9.4), and
a declined proposal is never re-raised by a later import (Rule 9.5).
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any

import auth
import genesis
import sys, pathlib as _pl
sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1] / "core"))
from genome_core import notify
from genome_core.store import GenomeStore

AGENTS_REALM = "genome_agents"
PROPOSALS = "link_proposals"

CONTACT_SCOPES = {
    "google": "https://www.googleapis.com/auth/contacts.readonly",
    "microsoft": "Contacts.Read",
}


def import_url(provider: str, state: str) -> str:
    """Consent URL for the CONTACTS scope alone, on the import callback."""
    p = auth.PROVIDERS[provider]
    import os
    q = {
        "client_id": os.environ[p["id_env"]],
        "redirect_uri": f"{auth.REDIRECT_BASE}/contacts/import/{provider}/callback",
        "response_type": "code",
        "scope": f"openid email {CONTACT_SCOPES[provider]}",
        "state": state,
    }
    if provider == "google":
        q["include_granted_scopes"] = "true"
        q["access_type"] = "online"
    return f"{p['auth']}?{urllib.parse.urlencode(q)}"


def _exchange(provider: str, code: str) -> str:
    import os
    p = auth.PROVIDERS[provider]
    body = urllib.parse.urlencode({
        "client_id": os.environ[p["id_env"]],
        "client_secret": os.environ[p["secret_env"]],
        "code": code, "grant_type": "authorization_code",
        "redirect_uri":
            f"{auth.REDIRECT_BASE}/contacts/import/{provider}/callback",
    }).encode()
    rq = urllib.request.Request(p["token"], data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(rq, timeout=30) as r:
        return json.load(r)["access_token"]


def _fetch_emails(provider: str, token: str) -> list[str]:
    """Every email address in the book — plaintext lives only in this frame."""
    out: list[str] = []
    hdr = {"Authorization": f"Bearer {token}"}
    if provider == "google":
        url = ("https://people.googleapis.com/v1/people/me/connections"
               "?personFields=emailAddresses&pageSize=200")
        while url:
            with urllib.request.urlopen(
                    urllib.request.Request(url, headers=hdr), timeout=30) as r:
                page = json.load(r)
            for person in page.get("connections", []):
                for e in person.get("emailAddresses", []):
                    if e.get("value"):
                        out.append(e["value"])
            tok = page.get("nextPageToken")
            url = (f"https://people.googleapis.com/v1/people/me/connections"
                   f"?personFields=emailAddresses&pageSize=200"
                   f"&pageToken={tok}") if tok else None
    else:
        url = ("https://graph.microsoft.com/v1.0/me/contacts"
               "?$select=emailAddresses&$top=100")
        while url:
            with urllib.request.urlopen(
                    urllib.request.Request(url, headers=hdr), timeout=30) as r:
                page = json.load(r)
            for c in page.get("value", []):
                for e in c.get("emailAddresses", []):
                    if e.get("address"):
                        out.append(e["address"])
            url = page.get("@odata.nextLink")
    return out


def _pair_key(a: str, b: str) -> str:
    return "prop-" + "-".join(sorted((a, b)))


async def _proposal(client: Any, key: str) -> dict | None:
    try:
        rows = await client.find_vertices(PROPOSALS, realm=AGENTS_REALM,
                                          filters={"key": key}, limit=1)
    except Exception:                      # table not yet minted by first write
        return None
    return rows[0] if rows else None


async def run_import(client: Any, me: str, provider: str, code: str) -> dict:
    """The whole flow, one request: fetch, hash, discard, propose."""
    token = _exchange(provider, code)
    emails = _fetch_emails(provider, token)
    scanned = len(emails)
    uids = {auth.user_id_from_email(e) for e in emails}
    del emails, token                      # plaintext ends here (Rule 9.3)
    result = await propose_links(client, me, uids)
    return {"scanned": scanned, **result}


async def propose_links(client: Any, me: str, uids: set[str]) -> dict:
    """Matching half, split from the fetch so it is provable without a
    consent screen: hashes in, proposals out, nothing else stored."""
    uids = set(uids)
    uids.discard(me)
    my_realm = await genesis.user_world_realm(client, me)
    matched = proposed = skipped = 0
    for uid in sorted(uids):
        their_realm = await genesis.user_world_realm(client, uid)
        if not their_realm:
            continue                       # not a user; nothing is kept
        matched += 1
        key = _pair_key(me, uid)
        prior = await _proposal(client, key)
        if prior is not None:
            skipped += 1                   # proposed, confirmed or declined:
            continue                       # an import never re-raises (9.5)
        already = any(p.get("to_world") == their_realm
                      for p in (await _world_portals(client, my_realm)))
        if already:
            skipped += 1
            continue
        await client.add_vertex(PROPOSALS, realm=AGENTS_REALM, payload={
            "key": key, "from_user": me, "to_user": uid,
            "status": "proposed"})
        await notify.emit(client, uid, "platform", "link_proposal",
                          "Someone who knows your address proposes linking "
                          "worlds. Confirm under Connections.")
        proposed += 1
    return {"matched": matched, "proposed": proposed, "skipped": skipped}


async def _world_portals(client: Any, realm: str | None) -> list[dict]:
    if not realm:
        return []
    store = GenomeStore(client)
    import sys as _s
    from genome_core import drain
    meta = await drain._world_payload(store, realm)
    return meta.get("portals", [])


async def list_proposals(client: Any, me: str) -> dict:
    try:
        rows = await client.get_vertices(PROPOSALS, realm=AGENTS_REALM)
    except Exception:
        rows = []
    mine = [v.payload for v in rows
            if v.payload.get("from_user") == me
            or v.payload.get("to_user") == me]
    return {"incoming": [p for p in mine if p["to_user"] == me
                         and p["status"] == "proposed"],
            "outgoing": [p for p in mine if p["from_user"] == me
                         and p["status"] == "proposed"]}


async def respond(client: Any, me: str, key: str, accept: bool) -> dict:
    row = await _proposal(client, key)
    if row is None or row.payload.get("to_user") != me:
        return {"error": "no such proposal for you"}
    p = row.payload
    if p["status"] != "proposed":
        return {"error": f"already {p['status']}"}
    status = "confirmed" if accept else "declined"
    await client.upsert_vertex(PROPOSALS, realm=AGENTS_REALM,
                               vertex_id=int(row.id), space="default",
                               payload={**p, "status": status})
    if not accept:
        return {"status": "declined"}      # quietly; no notification (9.5)
    realm_a = await genesis.user_world_realm(client, p["from_user"])
    realm_b = await genesis.user_world_realm(client, me)
    linked = await genesis.link_worlds(client, realm_a, realm_b) \
        if realm_a and realm_b else False
    if linked:
        for uid in (p["from_user"], me):
            await notify.emit(client, uid, "platform", "link_created",
                              "A proposed connection was confirmed: your "
                              "worlds are now linked by portal.")
    return {"status": "confirmed", "linked": bool(linked)}
