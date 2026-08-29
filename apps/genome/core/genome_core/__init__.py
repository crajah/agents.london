"""genome_core — the deterministic simulation core.

Everything here is arithmetic: closed forms, schema, and realm-scoped storage.
No inference, no I/O in the closed forms. Where code and a rule disagree, the
rule wins (spec/ over design/ over BUILD.md).
"""
__version__ = "0.0.1"
