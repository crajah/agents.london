#!/usr/bin/env python3
"""Render run_validation.py output as a verdict table. Usage: report.py f.json [...]"""
import json, sys

RHO_PASS, P_PASS, MONO_PASS = 0.30, 0.01, 0.75   # Rule 12.12: fixed before measurement
CONC_MAX, BAND_MIN          = 0.60, 2             # step-function guard (corrected)

def shape(s):
    """Gradient metrics from the per-level rate curve.

    step_conc  -- share of the total rise carried by the single largest adjacent
                  step. 1.0 means one jump does all the work: a step function.
    band       -- how many levels sit strictly between the extremes. This is the
                  part of the locus range that selection can actually climb.
    dead       -- levels that are behaviourally saturated (rate <=.05 or >=.95).
    """
    r  = s["rate_by_level"]; lv = sorted(r, key=int); v = [r[k] for k in lv]
    d  = [v[i+1]-v[i] for i in range(len(v)-1)]
    up = sum(x for x in d if x > 0)
    return dict(step_conc = (max(d) / up) if up > 0 else 1.0,
                band      = sum(1 for x in v if 0.10 < x < 0.90),
                dead      = sum(1 for x in v if x <= 0.05 or x >= 0.95),
                knee      = lv[max(range(len(d)), key=lambda i: d[i])] if d else None,
                curve     = v)

def verdict(s):
    if s["p"] > P_PASS or abs(s["rho"]) < RHO_PASS: return "FAIL"
    if s["rho"] < 0:                                return "INVERTED"
    sh = shape(s)
    if sh["step_conc"] > CONC_MAX or sh["band"] < BAND_MIN: return "STEP"
    if s["monotone_frac"] < MONO_PASS:              return "NOISY"
    return "PASS"

def main(paths):
    rows = []
    for f in paths:
        for k, s in json.load(open(f))["results"].items():
            model, pair = k.split("|"); rows.append((model, pair, s))

    for model in sorted({r[0] for r in rows}):
        rs = [r for r in rows if r[0] == model]
        print(f"\n=== {model} ===")
        print(f"{'locus -> scenario':<32}{'rho':>7}{'p':>8}{'mono':>6}{'conc':>6}{'band':>6}{'dead':>6}{'knee':>7}  verdict")
        print("-"*92)
        for _, pair, s in sorted(rs, key=lambda r: -abs(r[2]["rho"])):
            sh = shape(s)
            print(f"{pair:<32}{s['rho']:>7.2f}{s['p']:>8.4f}{s['monotone_frac']:>6.2f}"
                  f"{sh['step_conc']:>6.2f}{sh['band']:>6d}{sh['dead']:>6d}{str(sh['knee']):>7}  {verdict(s)}")
        v = [verdict(s) for _, _, s in rs]
        print(f"  n={len(rs)}  " + "  ".join(f"{x}={v.count(x)}" for x in
              ("PASS","STEP","NOISY","FAIL","INVERTED") if v.count(x)))

    print("\ncurve detail (rate of high-locus action by locus level)")
    for model, pair, s in sorted(rows):
        r = s["rate_by_level"]
        print(f"  {model:<22}{pair:<28}" + " ".join(f"{r[k]:.2f}" for k in sorted(r, key=int)))

if __name__ == "__main__":
    main(sys.argv[1:])
