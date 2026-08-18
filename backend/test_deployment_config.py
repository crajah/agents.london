"""The deployed configuration has to name settings the code actually reads.

The cluster set `DEFAULT_MODEL` and `EMBEDDING_MODEL`. The code reads
`DEFAULT_LLM_MODEL` and `RAG_EMBEDDING_MODEL`. Neither was applied, so the
deployment ran the code's built-in defaults for the chat model while `RAG_MODEL`
— spelled correctly, and therefore applied — pinned retrieval to a different
model family. Nothing failed; the cluster just quietly ran a configuration
nobody had chosen.

A key that nothing reads is indistinguishable from a key that works, right up
until someone changes it and nothing happens.
"""
from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFIGMAP = ROOT / "deploy" / "k8s" / "00-litellm-configmap.yaml"

# Settings the deployment supplies that no Python module reads by name: URLs
# consumed by other components, and duplicates kept for compatibility.
NOT_READ_BY_PYTHON = {
    "LITELLM_PROXY_URL",     # read by the router's own configuration
    "MODEL_ROUTER_URL",      # read via OPENAI_API_BASE in code
}


def configmap_keys() -> set:
    if not CONFIGMAP.is_file():
        pytest.skip("no cluster configmap in this checkout")
    keys, in_data = set(), False
    for line in CONFIGMAP.read_text().splitlines():
        if line.startswith("data:"):
            in_data = True
            continue
        if in_data:
            match = re.match(r"^  ([A-Z][A-Z0-9_]*):", line)
            if match:
                keys.add(match.group(1))
    return keys


def env_names_read_by_code() -> set:
    """Every environment variable the backend and services look up by name."""
    names = set()
    pattern = re.compile(r'(?:getenv|optional_env|require_env)\(\s*"([A-Z][A-Z0-9_]*)"')
    for directory in (ROOT / "backend", *sorted((ROOT / "services").glob("*"))):
        if not directory.is_dir():
            continue
        for source in directory.glob("*.py"):
            names.update(pattern.findall(source.read_text()))
    return names


def test_every_deployed_setting_is_one_the_code_reads():
    supplied = configmap_keys()
    read = env_names_read_by_code() | NOT_READ_BY_PYTHON

    orphaned = sorted(supplied - read)
    assert not orphaned, (
        "these are set in the cluster and read by nothing, so changing them "
        f"does nothing: {orphaned}")


def test_the_model_settings_are_spelled_the_way_the_code_spells_them():
    """The specific pair that was wrong, named so a regression is obvious."""
    supplied = configmap_keys()
    assert "DEFAULT_LLM_MODEL" in supplied
    assert "RAG_EMBEDDING_MODEL" in supplied
    # The two that silently did nothing.
    assert "DEFAULT_MODEL" not in supplied
    assert "EMBEDDING_MODEL" not in supplied


def test_the_cluster_and_the_code_agree_on_the_defaults():
    """A deployment that disagrees with the code is a deployment nobody tested."""
    import env_config

    text = CONFIGMAP.read_text()
    for key, expected in (("DEFAULT_LLM_MODEL", env_config.DEFAULT_LLM_MODEL),
                          ("RAG_EMBEDDING_MODEL", env_config.EMBEDDING_MODEL),
                          ("RAG_EMBEDDING_DIM", str(env_config.EMBEDDING_DIM))):
        assert f'{key}: "{expected}"' in text, f"{key} disagrees with env_config"
