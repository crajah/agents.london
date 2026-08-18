"""Finding configuration from wherever the service is running.

The container could not start: `parents[2]` on `/app/app.py` raised IndexError
before any of the service loaded. These hold that shut — the container layout
is a case here, not an assumption.
"""
from __future__ import annotations

import os
from pathlib import Path

from env_file import find_env_file, load_env_file


def test_the_container_layout_does_not_raise(tmp_path):
    """`/app/app.py` is two levels shallower than a checkout.

    This is the exact failure: the image copies
    `services/document-registry/app.py` to `/app/app.py`, so there is no
    grandparent to index and the old code raised IndexError at import.
    """
    flat = tmp_path / "app"
    flat.mkdir()
    module = flat / "app.py"
    module.write_text("# the service, as the image lays it out\n")

    assert find_env_file(module) is None       # no raise, and nothing found


def test_a_checkout_two_levels_down_is_found(tmp_path):
    root = tmp_path / "repo"
    service = root / "services" / "document-registry"
    service.mkdir(parents=True)
    env = root / ".env"
    env.write_text("PROBE=from-the-repo-root\n")

    assert find_env_file(service / "app.py") == env


def test_the_nearest_env_wins(tmp_path):
    """A service-local .env overrides one further up, which is the useful order."""
    root = tmp_path / "repo"
    service = root / "services" / "document-registry"
    service.mkdir(parents=True)
    (root / ".env").write_text("PROBE=root\n")
    near = service / ".env"
    near.write_text("PROBE=service\n")

    assert find_env_file(service / "app.py") == near


def test_loading_reports_what_it_read(tmp_path, monkeypatch):
    service = tmp_path / "repo" / "services" / "document-registry"
    service.mkdir(parents=True)
    env = tmp_path / "repo" / ".env"
    env.write_text("DOC_REGISTRY_PROBE=loaded\n")
    monkeypatch.delenv("DOC_REGISTRY_PROBE", raising=False)

    assert load_env_file(service / "app.py") == env
    assert os.getenv("DOC_REGISTRY_PROBE") == "loaded"


def test_a_missing_env_is_not_an_error(tmp_path):
    """A container is configured through its environment.

    Refusing to start over an absent convenience file would take down a
    correctly configured deployment — which is the failure this replaced.
    """
    flat = tmp_path / "app"
    flat.mkdir()
    assert load_env_file(flat / "app.py") is None


def test_a_directory_is_accepted_as_a_starting_point(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    env = root / ".env"
    env.write_text("PROBE=1\n")
    assert find_env_file(root) == env
