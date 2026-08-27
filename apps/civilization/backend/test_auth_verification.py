"""A token has to prove something before a session is granted on it.

Two ways it did not.

The Microsoft path base64-decoded the middle segment of the JWT and read the
email out of it — no signature, no issuer, no expiry, no audience. A string
anyone could type by hand was accepted as proof of identity, and the address it
named decided which organisation the session landed in.

The Google path checked the signature (via Google's tokeninfo) but never
checked who the token was *for*. An attacker registers their own OAuth client,
signs in to it, and presents the resulting token here: genuinely signed,
genuinely unexpired, and issued to somebody else's application entirely.
"""
from __future__ import annotations

import base64
import json

import pytest
from fastapi import HTTPException

import main


def forged(payload: dict) -> str:
    """A JWT with no signing key behind it. This is the whole attack."""
    def seg(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")
    return f"{seg({'alg': 'RS256'})}.{seg(payload)}.not-a-signature"


# ------------------------------------------------------------------ audience

def test_a_google_token_for_another_application_is_refused():
    with pytest.raises(HTTPException) as raised:
        main._require_audience({"aud": "999-someone-elses.apps.googleusercontent.com"},
                               ["976346242948-ours.apps.googleusercontent.com"],
                               "Google")
    assert raised.value.status_code == 401
    assert "different application" in raised.value.detail


def test_a_token_for_this_application_passes():
    main._require_audience({"aud": "ours"}, ["ours"], "Google")


def test_a_migration_may_accept_more_than_one_client(monkeypatch):
    """The bundle and the backend are configured in different places.

    A GitHub Actions build argument and a Kubernetes secret can hold different
    clients — as they do here — and during a migration both are legitimate. The
    point is that the set is stated rather than unbounded.
    """
    monkeypatch.setenv("GOOGLE_ADDITIONAL_CLIENT_IDS", "second, third")
    accepted = main._accepted_client_ids("first", "GOOGLE_ADDITIONAL_CLIENT_IDS")
    assert accepted == ["first", "second", "third"]
    main._require_audience({"aud": "third"}, accepted, "Google")


def test_a_token_with_no_audience_at_all_is_refused():
    with pytest.raises(HTTPException) as raised:
        main._require_audience({"email": "someone@example.com"}, ["ours"], "Google")
    assert raised.value.status_code == 401


def test_no_configured_client_means_nothing_can_be_checked(monkeypatch):
    """Refusing beats accepting everything when there is nothing to compare to."""
    monkeypatch.delenv("GOOGLE_ADDITIONAL_CLIENT_IDS", raising=False)
    with pytest.raises(HTTPException) as raised:
        main._accepted_client_ids("", "GOOGLE_ADDITIONAL_CLIENT_IDS")
    assert raised.value.status_code == 500


# ------------------------------------------------------------------ signature

def test_a_hand_written_microsoft_token_is_refused():
    """The exact bypass: no key, no signature, and it used to be believed."""
    token = forged({"email": "attacker@example.com",
                    "aud": "ours", "iss": "https://login.microsoftonline.com/t/v2.0",
                    "exp": 9999999999})
    with pytest.raises(HTTPException) as raised:
        main._verify_microsoft_id_token(token, ["ours"])
    assert raised.value.status_code == 401
    assert "Invalid Microsoft ID Token" in raised.value.detail


def test_the_email_in_a_forged_payload_never_reaches_tenancy():
    """What made it serious: the address chooses the organisation."""
    token = forged({"email": "ceo@someone-elses-company.com", "aud": "ours"})
    with pytest.raises(HTTPException):
        main._verify_microsoft_id_token(token, ["ours"])


def test_a_token_that_is_not_a_jwt_at_all_is_refused():
    for rubbish in ("", "not.a.token", "only-one-part", "a.b"):
        with pytest.raises(HTTPException) as raised:
            main._verify_microsoft_id_token(rubbish, ["ours"])
        assert raised.value.status_code == 401
