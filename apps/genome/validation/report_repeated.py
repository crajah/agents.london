#!/usr/bin/env python3
"""Render run_repeated.py output. Usage: report_repeated.py f.json [...]"""
import json, sys

LV = [0,1250,2500,3750,5000,6250,7500,8750,10000]

def main(paths):
    runs = [json.load(open(p)) for p in paths]
    print(f"{'schedule':<16}{'locus swept':<16}{'measure':<22}{'rho':>7}{'p':>9}  matched?")
    print("-"*84)
    for r in runs:
        sched = r["config"]["schedule"]
        matched = r["vary"].lower().startswith(sched[:6])
        print(f"{sched:<16}{r['vary']:<16}{r['measure']:<22}{r['rho']:>7.2f}"
              f"{(r['p'] if r['p'] is not None else float('nan')):>9.4f}"
              f"  {'MATCHED' if matched else 'cross-control'}")
    for r in runs:
        print(f"\n--- {r['config']['schedule']} schedule, sweeping {r['vary']} "
              f"({'matched' if r['vary'].lower().startswith(r['config']['schedule'][:6]) else 'CROSS-CONTROL'}) ---")
        b, s = r["by_level"], r["split_rate"]
        print(f"  {'locus':<10}"+"".join(f"{x:>8}" for x in LV))
        print(f"  {r['measure']:<10}"+"".join(
              f"{b[str(x)]:>8.2f}" if b.get(str(x)) is not None else f"{'-':>8}" for x in LV))
        print(f"  {'split rate':<10}"+"".join(f"{s[str(x)]:>8.2f}" for x in LV))
        print(f"  episodes {r['episodes_ok']}/{r['episodes_total']}")

if __name__ == "__main__":
    main(sys.argv[1:])
