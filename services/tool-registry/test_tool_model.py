"""Tests for the tool registration rules.

Run: python3 -m pytest services/tool-registry -q
"""
import copy

import pytest

from tool_model import (
    PUBLISHED, RegistrationError, ToolAuth, ToolIdentity, ToolVersionSpec,
    content_hash, discovery_text, validate_arguments, validate_registration,
)

OBJ = {"type": "object",
       "properties": {"query": {"type": "string", "description": "the search text"},
                      "top_k": {"type": "integer"}},
       "required": ["query"]}
OUT = {"type": "object", "properties": {"results": {"type": "array"}}}
INTERNAL = "http://tool-registry-service.default.svc.cluster.local:8002/tools/x"


def identity(**kw):
    base = dict(tool_id="mcp-x", name="X", description="does x",
                scope_type="org", org_id="org_a", project_id=None)
    base.update(kw)
    return ToolIdentity(**base)


def version(**kw):
    base = dict(tool_id="mcp-x", version="1.0.0", endpoint_url=INTERNAL,
                input_schema=OBJ, output_schema=OUT, side_effects="read")
    base.update(kw)
    return ToolVersionSpec(**base)


# ------------------------------------------------------------- content hash

def test_hash_ignores_description_but_not_endpoint():
    """A moved endpoint is a behaviour change; a changelog edit is not."""
    a = version()
    b = version(endpoint_url=INTERNAL + "/moved")
    assert a.hash() != b.hash()
    same = copy.deepcopy(a)
    same.changelog = "reworded entirely"
    same.cost_hint = {"kind": "search_query"}
    assert same.hash() == a.hash()


def test_hash_covers_the_input_schema():
    """The schema is the contract a model is shown; changing it changes behaviour."""
    a = version()
    b = version(input_schema={"type": "object", "properties": {"other": {"type": "string"}}})
    assert a.hash() != b.hash()


def test_hash_is_order_independent():
    one = content_hash({"limits": {"a": 1, "b": 2}, "auth": {"mode": "none"}})
    two = content_hash({"auth": {"mode": "none"}, "limits": {"b": 2, "a": 1}})
    assert one == two


def test_pin_carries_version_and_hash():
    """Rule 4.3: the version says which record, the hash proves it is unaltered."""
    pin = version().pin()
    assert pin == {"tool_id": "mcp-x", "version": "1.0.0",
                   "content_hash": version().hash()}


# ------------------------------------------------------------------- schemas

def test_schemas_are_required():
    with pytest.raises(Exception):
        ToolVersionSpec(tool_id="mcp-x", version="1.0.0", endpoint_url=INTERNAL,
                        input_schema={"type": "string"}, output_schema=OUT,
                        side_effects="read")


def test_side_effects_has_no_default():
    """Rejection 6: guessing 'read' for a writing tool licenses speculative calls."""
    with pytest.raises(Exception):
        ToolVersionSpec(tool_id="mcp-x", version="1.0.0", endpoint_url=INTERNAL,
                        input_schema=OBJ, output_schema=OUT)


def test_non_semver_version_is_rejected():
    with pytest.raises(Exception):
        version(version="v1")


def test_tool_id_must_be_a_slug():
    with pytest.raises(Exception):
        version(tool_id="Not A Slug")


# --------------------------------------------------------------------- scope

def test_org_scope_must_not_carry_a_project():
    with pytest.raises(Exception, match="Rule 2.2"):
        identity(scope_type="org", project_id="proj_a")


def test_project_scope_requires_a_project():
    with pytest.raises(Exception, match="Rule 2.2"):
        identity(scope_type="project", project_id=None)


def test_org_scoped_tool_is_visible_to_every_project():
    assert identity(scope_type="org").visible_to("proj_anything")
    assert identity(scope_type="org").visible_to(None)


def test_project_scoped_tool_is_visible_only_to_its_project():
    tool = identity(scope_type="project", project_id="proj_a")
    assert tool.visible_to("proj_a")
    assert not tool.visible_to("proj_b")
    assert not tool.visible_to(None)


# -------------------------------------------------------------------- secrets

def test_literal_credential_in_auth_is_rejected():
    """Rule 6.3: a registry row is readable by every service in the realm."""
    with pytest.raises(Exception, match="Rule 6.3"):
        ToolAuth(mode="bearer", secret_ref={"token": "sk-live-abcdef"})


def test_overlong_secret_ref_value_is_rejected():
    with pytest.raises(Exception, match="Rule 6.3"):
        ToolAuth(mode="secret_ref", secret_ref={"name": "x" * 200})


def test_a_kubernetes_secret_reference_is_accepted():
    auth = ToolAuth(mode="secret_ref",
                    secret_ref={"name": "litellm-api-keys", "key": "MASTER_KEY"})
    assert auth.secret_ref["name"] == "litellm-api-keys"


def test_secret_ref_mode_requires_a_name():
    with pytest.raises(Exception):
        ToolAuth(mode="secret_ref", secret_ref={"key": "MASTER_KEY"})


# --------------------------------------------------------------- registration

def test_editing_a_published_version_is_rejected():
    existing = {"1.0.0": {"status": PUBLISHED, "content_hash": "sha256:different"}}
    with pytest.raises(RegistrationError, match="Rule 3.3"):
        validate_registration(identity(), version(), existing)


def test_duplicate_content_under_a_new_version_is_rejected():
    existing = {"1.0.0": {"status": PUBLISHED, "content_hash": version().hash()}}
    with pytest.raises(RegistrationError, match="Rule 4.2"):
        validate_registration(identity(), version(version="1.0.1"), existing)


def test_a_genuinely_new_version_is_accepted():
    existing = {"1.0.0": {"status": PUBLISHED, "content_hash": version().hash()}}
    validate_registration(identity(), version(version="1.1.0", endpoint_url=INTERNAL + "/v2"),
                          existing)


def test_identity_and_version_must_name_the_same_tool():
    with pytest.raises(RegistrationError, match="identity names tool"):
        validate_registration(identity(tool_id="mcp-x"), version(tool_id="mcp-y"), {})


def test_external_endpoint_declared_as_read_is_rejected():
    """Rejection 7: a request that leaves the cluster is observable outside it."""
    with pytest.raises(RegistrationError, match="leaves the cluster"):
        validate_registration(identity(),
                              version(endpoint_url="https://api.example.com/search"),
                              {})


def test_external_endpoint_declared_as_external_is_accepted():
    validate_registration(
        identity(),
        version(endpoint_url="https://api.example.com/search", side_effects="external"),
        {})


def test_cluster_local_endpoint_is_not_external():
    validate_registration(identity(), version(), {})


# ------------------------------------------------------------------ arguments

def test_missing_required_argument_is_caught():
    assert "query" in (validate_arguments({}, OBJ) or "")


def test_wrong_type_is_caught():
    assert "top_k" in (validate_arguments({"query": "x", "top_k": "five"}, OBJ) or "")


def test_boolean_is_not_an_integer():
    """bool subclasses int in Python; a caller passing True for a count is wrong."""
    assert validate_arguments({"query": "x", "top_k": True}, OBJ) is not None


def test_valid_arguments_pass():
    assert validate_arguments({"query": "x", "top_k": 5}, OBJ) is None


def test_unexpected_argument_only_fails_when_the_schema_forbids_it():
    assert validate_arguments({"query": "x", "extra": 1}, OBJ) is None
    strict = {**OBJ, "additionalProperties": False}
    assert "extra" in (validate_arguments({"query": "x", "extra": 1}, strict) or "")


# ------------------------------------------------------------------ discovery

def test_discovery_text_includes_schema_descriptions():
    """'the search text' retrieves for a natural question; 'query' does not."""
    text = discovery_text(identity(), version())
    assert "the search text" in text
    assert "does x" in text


def test_idempotency_is_required_for_side_effecting_tools():
    assert version(side_effects="write").requires_idempotency_key()
    assert version(side_effects="external").requires_idempotency_key()
    assert not version(side_effects="read").requires_idempotency_key()
