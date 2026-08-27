"""Test-only path setup.

In the image, metering.py and pipeline_runtime.py are copied alongside these
modules, so they import as siblings. In the checkout they live in shared/,
and this bridges that difference for tests without a sys.path hack inside
application code — which would be load-bearing in production and invisible.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "shared"))
