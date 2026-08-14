"""Test-only path setup.

In the image, metering.py is copied alongside these modules, so it imports as a
sibling. In the checkout it lives in backend/, and this bridges that difference
for tests without a sys.path hack inside application code — which would be
load-bearing in production and invisible.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "backend"))
