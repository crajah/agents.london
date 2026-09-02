"""The outbox sender — system-spec §10's other half. Rows are durable the
moment they are written (notify.outbox); this drains them.

Without GENOME_SMTP_HOST the sender is a NO-OP and rows simply wait --
today's behaviour, now explicit. With it, mail leaves via STARTTLS and each
row is marked sent_at; a row that fails five times is marked failed_at and
stops being retried (the address is wrong, not the weather)."""
from __future__ import annotations

import logging
import os
import smtplib
import time
from email.message import EmailMessage
from typing import Any

logger = logging.getLogger("genome.mailer")

MAX_ATTEMPTS = 5


def _configured() -> bool:
    return bool(os.getenv("GENOME_SMTP_HOST"))


def _send_one(to: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"] = os.getenv("GENOME_SMTP_FROM", "genome@agents.london")
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    host = os.environ["GENOME_SMTP_HOST"]
    port = int(os.getenv("GENOME_SMTP_PORT", "587"))
    with smtplib.SMTP(host, port, timeout=20) as s:
        if os.getenv("GENOME_SMTP_TLS", "1") != "0":
            s.starttls()
        user = os.getenv("GENOME_SMTP_USER")
        if user:
            s.login(user, os.environ["GENOME_SMTP_PASS"])
        s.send_message(msg)


async def send_pending(client: Any, limit: int = 20) -> int:
    """Drain up to `limit` unsent rows. Returns how many actually left."""
    if not _configured():
        return 0
    rows = await client.find_vertices("outbox", realm="genome_agents",
                                      where=[("sent_at", "is_null", None),
                                             ("failed_at", "is_null", None)],
                                      limit=limit)
    sent = 0
    for v in rows:
        pl = dict(v.payload)
        attempts = int(pl.get("attempts", 0)) + 1
        try:
            _send_one(pl["to"], pl.get("subject", "genome"),
                      pl.get("body", ""))
            pl["sent_at"] = time.time()
            sent += 1
        except Exception as e:
            logger.warning("mail to %s failed (%d/%d): %s", pl.get("to"),
                           attempts, MAX_ATTEMPTS, e)
            pl["attempts"] = attempts
            if attempts >= MAX_ATTEMPTS:
                pl["failed_at"] = time.time()
        await client.upsert_vertex("outbox", realm="genome_agents",
                                   vertex_id=int(v.id), space="default",
                                   payload=pl)
    return sent
