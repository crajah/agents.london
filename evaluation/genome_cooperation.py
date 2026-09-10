#!/usr/bin/env python3
"""Genome cooperation structure — observational analysis of the live society.

Addresses the genome cooperation claims (evaluation plan, G2 contribution &
free-riders; and the ark-as-supply-chain thesis) from data the platform already
records: the favour ledgers on each agent (debts/credits) and the constructions
table (contributors per build).

This is OBSERVATIONAL, not a controlled ablation — it establishes whether a real
reciprocal favour economy exists and whether the ark actually forms as a
multi-agent supply chain. The causal ablation (disable the favour ledger, does
cooperation still form?) is the planned next step.

Requires cluster access (reads Postgres via `kubectl exec` on the CNPG primary),
so unlike the public composition harness it runs ops-side. Writes
results/<date>-genome-cooperation.json.
"""
import json, os, statistics as st, subprocess
from datetime import date

OUT = os.path.join(os.path.dirname(__file__), "results",
                   f"{date.today().isoformat()}-genome-cooperation.json")

def psql(sql):
    primary = subprocess.check_output(
        ["kubectl", "get", "cluster", "postgres-ha",
         "-o", "jsonpath={.status.currentPrimary}"]).decode().strip()
    return subprocess.check_output(
        ["kubectl", "exec", primary, "--", "psql", "-U", "postgres",
         "-d", "postgres", "-Atc", sql]).decode()

def gini(xs):
    xs = sorted(xs); n = len(xs)
    if not n: return 0.0
    m = min(xs); xs = [x - m for x in xs]; s = sum(xs)
    if s == 0: return 0.0
    cum = sum(i * x for i, x in enumerate(xs, 1))
    return (2 * cum) / (n * s) - (n + 1) / n

def main():
    fav = [json.loads(l) for l in psql(
        "select json_build_object('k',payload->>'key','d',payload->'debts',"
        "'c',payload->'credits')::text from public.agents where realm='genome_agents' "
        "and (payload->'debts'<>'{}'::jsonb or payload->'credits'<>'{}'::jsonb)"
    ).splitlines() if l.strip()]
    debt_by = {r["k"]: (r.get("d") or {}) for r in fav}
    credit_by = {r["k"]: (r.get("c") or {}) for r in fav}
    owes = {k: sum(d.values()) for k, d in debt_by.items()}
    owed = {k: sum(c.values()) for k, c in credit_by.items()}
    edges = {(a, b) for a, d in debt_by.items() for b in d}
    recip = sum(1 for (a, b) in edges if (b, a) in edges)
    cm = ct = 0
    for a, d in debt_by.items():
        for b, amt in d.items():
            ct += 1
            if credit_by.get(b, {}).get(a) == amt: cm += 1
    agents = set(list(owes) + list(owed))
    bal = [owed.get(k, 0) - owes.get(k, 0) for k in agents]
    fe = {"agents_in_graph": len(agents), "directed_favour_edges": len(edges),
          "reciprocated_edges": recip,
          "reciprocity_pct": round(100 * recip / max(1, len(edges))),
          "ledger_consistency_pct": round(100 * cm / max(1, ct)),
          "pure_givers": sum(1 for k in debt_by if owes.get(k, 0) > 0 and owed.get(k, 0) == 0),
          "pure_takers": sum(1 for k in credit_by if owed.get(k, 0) > 0 and owes.get(k, 0) == 0),
          "favour_balance_gini": round(gini(bal), 3)}

    cons = [json.loads(l) for l in psql(
        "select json_build_object('name',payload->>'name','complete',payload->>'complete',"
        "'contributors',payload->'contributors')::text from public.constructions"
    ).splitlines() if l.strip()]
    nc = lambda c: len(c.get("contributors") or {})
    arks = [c for c in cons if c.get("name") == "ark"]
    cc = [nc(c) for c in cons if nc(c) > 0]
    sc = {"constructions_total": len(cons), "arks": len(arks),
          "arks_complete": sum(1 for c in arks if str(c.get("complete")).lower() == "true"),
          "arks_multi_contributor": sum(1 for c in arks if nc(c) >= 2),
          "constructions_multi_contributor": sum(1 for c in cons if nc(c) >= 2),
          "mean_contributors_per_build": round(st.mean(cc), 2) if cc else 0,
          "max_contributors": max(cc) if cc else 0}

    out = {"date": date.today().isoformat(), "favour_economy": fe, "supply_chain": sc}
    json.dump(out, open(OUT, "w"), indent=2)
    print(json.dumps(out, indent=2)); print("written:", OUT)

if __name__ == "__main__":
    main()
