# genome_core

The deterministic simulation core: closed forms, genotype arithmetic, opinion
updates, and the post-graph-backed store. **No direct DDL anywhere** — post-graph
owns every table. **No inference happens here**
(`execution-spec.md` Rule 1.2) — everything in this package is the free tier.

Run tests from anywhere: `python3 apps/genome/core/tests/test_core.py`

| Module | Implements |
| :--- | :--- |
| `forms.py` | position/heading from movement intents; pile quantity in closed form; `mine` as a pile's only write (`execution-spec.md` §2, calibration §1) |
| `genotype.py` | norm, allocation budget with Σ=B invariant, derived faculties, Maturation/Attrition life history (`genotype-spec.md` §2, §3.8, §3.10, §4) |
| `opinion.py` | EWMA, surprise-weighted event updates, decay (`genotype-spec.md` Rules 6.9–6.10b) |
| `store.py` | storage on **post-graph** — one realm `genome`, each world a **space**; missing space fails closed (`genome-spec.md` Rule 3.5) — simulation path only (`interface-spec.md` Rule 1.1). Agents' private knowledge: **post-graph-rag**, agent-keyed spaces (§8) |

