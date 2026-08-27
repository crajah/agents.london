"""External search and data providers: Tavily, Serper, and RapidAPI services.

These are `kind: "builtin"` tools in the sense of spec §7.2 — catalogued like
any other tool, but implemented here because the credential belongs to the
platform rather than to an agent.

Two rules from the spec shape every function below.

**Rule 7.2** — a failed call raises. Nothing here returns a plausible-looking
result it did not obtain. The search endpoint already had one incident of
answering `status: success` with invented results whose snippets described
themselves as empirically retrieved; an agent cannot tell fabricated evidence
from real evidence, so the failure has to reach it as a failure.

**Rule 7.3** — a provider with no credential is not seeded and its endpoint
answers 503 naming the variable that is missing. It does not degrade to a
weaker provider, because an agent told it searched the web has no way to learn
that it actually did something else.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

# How long a key that reported a quota failure is left out of rotation. Quota
# resets on the provider's clock, not ours, so this is a courtesy interval that
# stops one exhausted key soaking up every request; it is not a guarantee the
# key has recovered.
QUOTA_COOLDOWN_SECS = float(os.getenv("TAVILY_QUOTA_COOLDOWN_SECS", "900"))

EXTERNAL_TIMEOUT = float(os.getenv("EXTERNAL_TOOL_TIMEOUT", "30"))


class ProviderError(RuntimeError):
    """An external provider failed. Carries the status to map onto a response."""

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


class NotConfigured(ProviderError):
    """No usable credential. Rule 7.3: 503, and the message names the variable."""

    def __init__(self, message: str):
        super().__init__(message, status_code=503)


# ------------------------------------------------------------ Tavily key ring

def _collect_tavily_keys() -> List[Tuple[str, str]]:
    """Every configured Tavily key, as (env_var_name, value).

    Reads TAVILY_API_KEY plus TAVILY_API_KEY_<n> for n = 1.. until a gap of
    more than a few, so adding a fifth key is a deployment change and not a
    code change. Names are kept alongside values because every log line and
    error message below refers to a key by its variable name — printing the
    key itself would put a live credential in the log.
    """
    found: List[Tuple[str, str]] = []
    base = (os.getenv("TAVILY_API_KEY") or "").strip()
    if base:
        found.append(("TAVILY_API_KEY", base))
    missing_run = 0
    n = 1
    while missing_run < 3 and n < 64:
        name = f"TAVILY_API_KEY_{n}"
        value = (os.getenv(name) or "").strip()
        if value:
            found.append((name, value))
            missing_run = 0
        else:
            missing_run += 1
        n += 1
    # De-duplicate by value, keeping the first name. The same key exported
    # under two names is one key's quota, and rotating between the two aliases
    # would look like spreading load while actually hammering one bucket.
    seen: Dict[str, str] = {}
    unique: List[Tuple[str, str]] = []
    for name, value in found:
        if value in seen:
            logger.warning("%s duplicates %s; ignoring the alias", name, seen[value])
            continue
        seen[value] = name
        unique.append((name, value))
    return unique


@dataclass
class _KeyState:
    name: str
    value: str
    quarantined_reason: Optional[str] = None   # permanent: bad/revoked key
    cooldown_until: float = 0.0                # temporary: quota exhausted
    successes: int = 0
    failures: int = 0

    def available(self, now: float) -> bool:
        return self.quarantined_reason is None and now >= self.cooldown_until


class TavilyKeyRing:
    """Round-robin over the configured Tavily keys, with automatic failover.

    Rotation is two things, and conflating them is why a single "retry" is not
    enough:

    1. **Spreading load.** Each call starts at the next key, so N keys carry
       roughly 1/N of the traffic instead of the first key carrying all of it
       until it is exhausted.
    2. **Failing over.** Within one call, a key that reports an auth or quota
       problem is stepped over and the next is tried, up to the number of keys.
       The caller sees one search, not a key management problem.

    The two failure classes are handled differently on purpose. A revoked key
    (401) will fail identically forever, so it is quarantined and leaves the
    rotation — retrying it every Nth call would turn a dead key into a fixed
    fraction of failed searches. An exhausted key (429/432) recovers on the
    provider's clock, so it is only benched for `QUOTA_COOLDOWN_SECS`.
    """

    def __init__(self, keys: Optional[List[Tuple[str, str]]] = None):
        pairs = keys if keys is not None else _collect_tavily_keys()
        self._keys = [_KeyState(name=n, value=v) for n, v in pairs]
        self._cursor = 0
        self._lock = threading.Lock()

    def __len__(self) -> int:
        return len(self._keys)

    @property
    def configured(self) -> bool:
        return bool(self._keys)

    def order_for_call(self) -> List[_KeyState]:
        """The keys to try, in order, for one call.

        Advances the shared cursor by one so the next call starts one key
        further along. Quarantined and cooling keys are dropped here rather
        than skipped by the caller, so the caller's retry budget is the number
        of keys that could actually work.
        """
        now = time.time()
        with self._lock:
            if not self._keys:
                return []
            start = self._cursor % len(self._keys)
            self._cursor = (self._cursor + 1) % len(self._keys)
        ordered = self._keys[start:] + self._keys[:start]
        return [k for k in ordered if k.available(now)]

    def quarantine(self, key: _KeyState, reason: str) -> None:
        with self._lock:
            if key.quarantined_reason is None:
                key.quarantined_reason = reason
                logger.error("Tavily key %s removed from rotation: %s", key.name, reason)
        key.failures += 1

    def bench(self, key: _KeyState, seconds: float, reason: str) -> None:
        with self._lock:
            key.cooldown_until = time.time() + seconds
        key.failures += 1
        logger.warning("Tavily key %s benched for %.0fs: %s", key.name, seconds, reason)

    def succeeded(self, key: _KeyState) -> None:
        key.successes += 1

    def status(self) -> List[Dict[str, Any]]:
        """Per-key health, by variable name. Never includes a key's value."""
        now = time.time()
        return [{
            "name": k.name,
            "state": ("quarantined" if k.quarantined_reason
                      else "cooling" if now < k.cooldown_until else "available"),
            "reason": k.quarantined_reason,
            "cooldown_secs_remaining": max(0, round(k.cooldown_until - now)),
            "successes": k.successes,
            "failures": k.failures,
        } for k in self._keys]


TAVILY_URL = os.getenv("TAVILY_URL", "https://api.tavily.com/search")


async def tavily_search(ring: TavilyKeyRing, query: str, max_results: int = 5,
                        search_depth: str = "basic",
                        include_answer: bool = True) -> Dict[str, Any]:
    """Search via Tavily, rotating keys and failing over on key-specific errors.

    Raises rather than returning a degraded result. If every key is exhausted
    or revoked the caller gets an error naming that, because "no results" and
    "we could not ask" mean different things to an agent deciding what to do
    next.
    """
    if not ring.configured:
        raise NotConfigured(
            "Tavily is not configured: set TAVILY_API_KEY or TAVILY_API_KEY_1.")

    candidates = ring.order_for_call()
    if not candidates:
        raise ProviderError(
            "Every Tavily key is unavailable (revoked or over quota); "
            "see /tools/tavily-search/keys for per-key state.", status_code=503)

    body = {
        "query": query,
        "max_results": max(1, min(int(max_results), 20)),
        "search_depth": search_depth if search_depth in ("basic", "advanced") else "basic",
        "include_answer": bool(include_answer),
    }

    last_error = "no attempt was made"
    async with httpx.AsyncClient(timeout=EXTERNAL_TIMEOUT) as http:
        for key in candidates:
            try:
                res = await http.post(
                    TAVILY_URL, json=body,
                    headers={"Authorization": f"Bearer {key.value}",
                             "Content-Type": "application/json"})
            except httpx.HTTPError as e:
                # A transport failure is not the key's fault, so the key is not
                # penalised; the next key is tried in case it is an endpoint or
                # DNS problem local to this attempt.
                last_error = f"transport error via {key.name}: {e}"
                logger.warning("Tavily %s", last_error)
                continue

            if res.status_code == 200:
                ring.succeeded(key)
                payload = res.json()
                results = payload.get("results") or []
                return {
                    "query": query,
                    "answer": payload.get("answer") or "",
                    "results": [{
                        "title": r.get("title") or "",
                        "snippet": (r.get("content") or "").strip(),
                        "link": r.get("url") or "",
                        "score": r.get("score"),
                    } for r in results],
                    "count": len(results),
                    "provider": "tavily",
                    "key_used": key.name,     # the variable name, never the key
                }

            detail = res.text[:200]
            if res.status_code in (401, 403):
                ring.quarantine(key, f"HTTP {res.status_code}: {detail[:120]}")
                last_error = f"{key.name} rejected: HTTP {res.status_code}"
                continue
            if res.status_code in (429, 432):
                # 432 is Tavily's plan-limit status; 429 is ordinary rate
                # limiting. Both recover with time, so bench rather than
                # quarantine.
                ring.bench(key, QUOTA_COOLDOWN_SECS, f"HTTP {res.status_code}")
                last_error = f"{key.name} over quota: HTTP {res.status_code}"
                continue

            # Anything else is the provider misbehaving rather than this key
            # being wrong; another key would fail the same way.
            raise ProviderError(
                f"Tavily returned {res.status_code}: {detail}", status_code=502)

    raise ProviderError(
        f"Tavily search failed on every available key ({len(candidates)} tried). "
        f"Last error: {last_error}", status_code=502)


# ------------------------------------------------------------------- Serper

SERPER_URL = os.getenv("SERPER_URL", "https://google.serper.dev/search")


def serper_key() -> str:
    """SERPER_API_KEY, or SERPER_KEY which is what the console hands you."""
    return (os.getenv("SERPER_API_KEY") or os.getenv("SERPER_KEY") or "").strip()


async def serper_search(query: str, num_results: int = 5,
                        country: str = "us", language: str = "en") -> Dict[str, Any]:
    """Google results via Serper. One key, so no rotation — but the same rules."""
    key = serper_key()
    if not key:
        raise NotConfigured("Serper is not configured: set SERPER_API_KEY.")

    body = {"q": query, "num": max(1, min(int(num_results), 20)),
            "gl": country, "hl": language}
    try:
        async with httpx.AsyncClient(timeout=EXTERNAL_TIMEOUT) as http:
            res = await http.post(SERPER_URL, json=body,
                                  headers={"X-API-KEY": key,
                                           "Content-Type": "application/json"})
    except httpx.HTTPError as e:
        raise ProviderError(f"Serper unreachable: {e}", status_code=502) from e

    if res.status_code == 401 or res.status_code == 403:
        raise ProviderError(
            f"Serper rejected SERPER_API_KEY (HTTP {res.status_code}).",
            status_code=502)
    if res.status_code != 200:
        raise ProviderError(
            f"Serper returned {res.status_code}: {res.text[:200]}", status_code=502)

    payload = res.json()
    organic = payload.get("organic") or []
    answer_box = payload.get("answerBox") or {}
    return {
        "query": query,
        "answer": (answer_box.get("answer") or answer_box.get("snippet") or ""),
        "results": [{
            "title": r.get("title") or "",
            "snippet": r.get("snippet") or "",
            "link": r.get("link") or "",
            "position": r.get("position"),
        } for r in organic],
        "count": len(organic),
        "provider": "serper",
        "credits_used": payload.get("credits"),
    }


# ----------------------------------------------------------------- RapidAPI

@dataclass(frozen=True)
class RapidApiService:
    """One RapidAPI-hosted API, catalogued as its own tool.

    Each service becomes a separate `tool_id` rather than one generic
    "call RapidAPI" tool. A single tool taking a host and a path would push the
    choice of endpoint onto the model, which is exactly the guessing that
    Rule 3.2 exists to prevent: the input schema is what the model is shown, so
    it has to describe one API's arguments, not the shape of HTTP.
    """
    slug: str
    host: str
    name: str
    description: str
    path: str
    capabilities: Tuple[str, ...]
    # tool input name -> RapidAPI query parameter name
    params: Dict[str, str] = field(default_factory=dict)
    required: Tuple[str, ...] = ()
    # Fixed query parameters the caller does not choose.
    fixed: Dict[str, str] = field(default_factory=dict)
    schema_properties: Dict[str, Any] = field(default_factory=dict)

    @property
    def tool_id(self) -> str:
        return f"mcp-rapidapi-{self.slug}"


# Only services this key is actually subscribed to AND that still answer.
#
# Three others were subscribed but are dead upstreams and are deliberately not
# listed: linkedin-api8 answers HTTP 200 with
# {"success": false, "message": "This service is no longer available at this
# location"}, google-translate1 answers {"message": "API doesn't exists"}, and
# numbersapi 404s on every path. Cataloguing any of them would advertise a
# capability that fails at call time, which Rule 5.1 exists to prevent — and
# the linkedin one is the worst of the three, because a 200 with a falsy body
# is the shape most likely to be mistaken for a result.
RAPIDAPI_SERVICES: Tuple[RapidApiService, ...] = (
    RapidApiService(
        slug="deezer",
        host="deezerdevs-deezer.p.rapidapi.com",
        name="Deezer music catalogue search",
        description="Searches the Deezer catalogue for tracks, artists and "
                    "albums, returning titles, artists, durations and preview "
                    "links.",
        path="/search",
        capabilities=("music_search", "catalogue", "retrieve"),
        params={"query": "q"},
        required=("query",),
        schema_properties={
            "query": {"type": "string",
                      "description": "Track, artist or album to search for"},
        },
    ),
    RapidApiService(
        slug="yahoo-finance",
        host="yahoo-finance15.p.rapidapi.com",
        name="Yahoo Finance market quotes",
        description="Returns a current market quote for a ticker symbol: price, "
                    "change, volume and related market data.",
        path="/api/v1/markets/quote",
        capabilities=("market_data", "finance", "quote", "retrieve"),
        params={"ticker": "ticker"},
        required=("ticker",),
        fixed={"type": "STOCKS"},
        schema_properties={
            "ticker": {"type": "string",
                       "description": "Ticker symbol, for example AAPL or MSFT"},
        },
    ),
)

RAPIDAPI_BY_SLUG: Dict[str, RapidApiService] = {s.slug: s for s in RAPIDAPI_SERVICES}


def rapidapi_key() -> str:
    return (os.getenv("RAPIDAPI_KEY") or "").strip()


async def rapidapi_call(service: RapidApiService,
                        arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Call one RapidAPI service and return what it said, or raise.

    RapidAPI's gateway is the reason this cannot simply trust a 2xx. An
    unsubscribed *or entirely invalid* key both return HTTP 403 "You are not
    subscribed to this API", so a 403 says nothing about which of the two went
    wrong and the message has to say so rather than guess. Worse, a retired
    upstream can answer 200 with `{"success": false}`, so a success status is
    checked for that shape before it is passed on as a result.
    """
    key = rapidapi_key()
    if not key:
        raise NotConfigured("RapidAPI is not configured: set RAPIDAPI_KEY.")

    query: Dict[str, str] = dict(service.fixed)
    for tool_arg, api_param in service.params.items():
        if tool_arg in arguments and arguments[tool_arg] is not None:
            query[api_param] = str(arguments[tool_arg])
    for name in service.required:
        if not query.get(service.params.get(name, name)):
            raise ProviderError(f"Missing required argument '{name}'.", status_code=400)

    url = f"https://{service.host}{service.path}"
    try:
        async with httpx.AsyncClient(timeout=EXTERNAL_TIMEOUT) as http:
            res = await http.get(url, params=query,
                                 headers={"X-RapidAPI-Key": key,
                                          "X-RapidAPI-Host": service.host})
    except httpx.HTTPError as e:
        raise ProviderError(f"{service.name} unreachable: {e}", status_code=502) from e

    if res.status_code == 403:
        raise ProviderError(
            f"RapidAPI refused the call to {service.host}: either RAPIDAPI_KEY is "
            f"invalid or this account is not subscribed to that API. RapidAPI "
            f"returns the same 403 for both, so this cannot be narrowed here.",
            status_code=502)
    if res.status_code == 429:
        raise ProviderError(f"{service.name} rate limit reached (HTTP 429).",
                            status_code=429)
    if res.status_code != 200:
        raise ProviderError(
            f"{service.name} returned {res.status_code}: {res.text[:200]}",
            status_code=502)

    try:
        payload = res.json()
    except ValueError as e:
        raise ProviderError(
            f"{service.name} returned a non-JSON body: {res.text[:150]}",
            status_code=502) from e

    # A retired API answering 200 with a falsy body is not a result.
    if isinstance(payload, dict) and payload.get("success") is False:
        raise ProviderError(
            f"{service.name} reported failure: "
            f"{payload.get('message') or payload}", status_code=502)

    return {"service": service.slug, "host": service.host,
            "arguments": query, "data": payload}
