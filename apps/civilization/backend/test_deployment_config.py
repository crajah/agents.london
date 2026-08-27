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

def _repo_root(start: pathlib.Path) -> pathlib.Path:
    """The nearest ancestor holding deploy/k8s, else holding .git.

    Not `parent.parent`: that encoded "this file sits one level below the
    repository root", which stopped being true when the app moved under
    apps/civilization/ and turned every manifest assertion into a
    FileNotFoundError pointing at a path that had never existed.
    """
    for directory in (start, *start.parents):
        if (directory / "deploy" / "k8s").is_dir():
            return directory
    for directory in (start, *start.parents):
        if (directory / ".git").is_dir():
            return directory
    return start


ROOT = _repo_root(pathlib.Path(__file__).resolve().parent)
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


def code_directories():
    """Every directory whose modules may read settings by name.

    Enumerated rather than hard-coded as ROOT/"backend": that path stopped
    existing when the app moved to apps/civilization/, and the test did not
    fail loudly — it reported CIVILIZATION_ENGINE_TYPE and
    DOCUMENT_REGISTRY_URL as "set in the cluster and read by nothing", which
    reads like a deployment bug rather than a stale glob. Any new app under
    apps/ is picked up without editing this.
    """
    directories = [ROOT / "shared"]
    for app in sorted((ROOT / "apps").glob("*")):
        if app.is_dir():
            directories.extend(sorted(d for d in app.glob("*") if d.is_dir()))
    directories.extend(sorted((ROOT / "services").glob("*")))
    return [d for d in directories if d.is_dir()]


def env_names_read_by_code() -> set:
    """Every environment variable the backend and services look up by name."""
    names = set()
    pattern = re.compile(r'(?:getenv|optional_env|require_env)\(\s*"([A-Z][A-Z0-9_]*)"')
    for directory in code_directories():
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


# ------------------------------------------------------------ manifest shape

MANIFESTS = sorted((ROOT / "deploy" / "k8s").glob("*.yaml")) if (
    ROOT / "deploy" / "k8s").is_dir() else []


def load_manifests():
    import yaml
    for path in MANIFESTS:
        for doc in yaml.safe_load_all(path.read_text()):
            if doc:
                yield path.name, doc


def test_a_read_write_once_volume_is_never_rolling_updated():
    """The deadlock that stopped a deploy:

        Multi-Attach error for volume "pvc-…": Volume is already used by
        pod(s) document-registry-64c55478bd-9d99z

    A ReadWriteOnce volume attaches to one node at a time. A Deployment's
    default strategy starts the replacement before stopping the original, so
    the new pod waits forever for a volume the old pod will not release until
    the new one is ready. It cannot resolve itself.

    Either the workload does not need the volume, or the strategy must be
    Recreate — never a rolling update over an RWO claim.
    """
    if not MANIFESTS:
        pytest.skip("no manifests in this checkout")

    rwo_claims = {doc["metadata"]["name"]
                  for _, doc in load_manifests()
                  if doc.get("kind") == "PersistentVolumeClaim"
                  and "ReadWriteOnce" in (doc.get("spec", {}).get("accessModes") or [])}

    offenders = []
    for name, doc in load_manifests():
        if doc.get("kind") != "Deployment":
            continue
        spec = doc.get("spec", {})
        strategy = (spec.get("strategy") or {}).get("type", "RollingUpdate")
        claims = {v["persistentVolumeClaim"]["claimName"]
                  for v in (spec.get("template", {}).get("spec", {}).get("volumes") or [])
                  if "persistentVolumeClaim" in v}
        clashing = claims & rwo_claims
        if clashing and strategy != "Recreate":
            offenders.append(f"{name}: {doc['metadata']['name']} rolling-updates "
                             f"over {sorted(clashing)}")

    assert not offenders, "\n".join(offenders)


def test_no_workload_mounts_a_volume_nothing_writes_to():
    """The document registry carried a 5Gi claim it never opened a file on.

    It persists through post-graph, into PostgreSQL. The volume bought nothing
    and cost a deploy: it is the claim that deadlocked the rollout.
    """
    if not MANIFESTS:
        pytest.skip("no manifests in this checkout")

    sources = " ".join(
        path.read_text()
        for directory in (ROOT / "apps", ROOT / "services", ROOT / "shared")
        if directory.is_dir()
        for path in directory.rglob("*.py"))

    unused = []
    for name, doc in load_manifests():
        if doc.get("kind") != "Deployment":
            continue
        for container in doc["spec"]["template"]["spec"].get("containers", []):
            # A mount earns its place if the code writes there, or if the
            # container is configured to — a cache directory is named by an
            # environment variable, not by a line of Python.
            configured = " ".join(str(e.get("value", ""))
                                  for e in container.get("env") or [])
            for mount in container.get("volumeMounts") or []:
                path = mount["mountPath"]
                if path not in sources and path not in configured:
                    unused.append(f"{name}: {container['name']} mounts {path}, "
                                  f"which nothing reads, writes or points at")
    assert not unused, "\n".join(unused)


def test_a_container_that_writes_to_disk_declares_ephemeral_storage():
    """Space the pod needs, asked for rather than assumed.

    The document registry downloads docling's models to the container
    filesystem and writes each upload to a temp file. Neither wants
    persistence, so neither wants a volume — but both want room. Undeclared,
    the scheduler grants a small default and evicts the pod when the models
    exceed it, mid-extraction, after the upload has been accepted.
    """
    if not MANIFESTS:
        pytest.skip("no manifests in this checkout")

    writes_to_disk = {"document-registry"}
    missing = []
    for name, doc in load_manifests():
        if doc.get("kind") != "Deployment":
            continue
        for container in doc["spec"]["template"]["spec"].get("containers", []):
            if container["name"] not in writes_to_disk:
                continue
            for bound in ("requests", "limits"):
                declared = (container.get("resources") or {}).get(bound) or {}
                if "ephemeral-storage" not in declared:
                    missing.append(f"{name}: {container['name']} declares no "
                                   f"ephemeral-storage {bound}")
    assert not missing, "\n".join(missing)
