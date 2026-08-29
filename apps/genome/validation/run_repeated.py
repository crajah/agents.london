#!/usr/bin/env python3
"""
Repeated-interaction harness  —  Reciprocity and Vindictiveness.

Every earlier test was single-turn against a stranger with no past. These two
loci are *defined* by history — "respond in kind" and "how long a defection is
held against a counterparty" — so the condition they exist for was never tested.
Their earlier passes came from scenarios that merely described a past in one
sentence, which is not the same as having one.

An episode is a repeated joint haul with the SAME counterparty. Each round the
agent chooses to split the load evenly or grab the larger share; the counterparty
plays a fixed script; the full history is shown back each round.

Two schedules, each measuring the thing its locus names:

  RECIPROCITY  counterparty splits 1-3, grabs 4-6, splits 7-9.
               measure: P(split | it split last) - P(split | it grabbed last).
               A reciprocator rewards and punishes; the difference is the effect.

  VINDICTIVENESS  counterparty splits 1-4, grabs ONCE at 5, splits 6-12.
               measure: forgiveness latency -- rounds after the single defection
               until the agent splits again. This is the literal operationalisation
               of "how long a defection is held against a counterparty", and it is
               not reachable in a single turn at all.

Env: GENOME_ROUTER_URL, GENOME_ROUTER_KEY or GLOBAL_API_KEY. Stdlib only.
"""
import json, os, sys, math, random, argparse, urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = os.environ.get("GENOME_ROUTER_URL", "http://localhost:4000").rstrip("/")
KEY  = os.environ.get("GENOME_ROUTER_KEY") or os.environ.get("GLOBAL_API_KEY") or ""

DISPOSITIONS = ["Cooperativeness","Reciprocity","Vindictiveness","Aggression",
                "Honesty","Credulity","Amenability","Loyalty","Patience",
                "Curiosity","Prudence","Wanderlust","Fecundity","Selectivity"]

SPLIT, GRAB = "split", "grab"
SCHEDULES = {
    # what the COUNTERPARTY does each round
    "reciprocity":    [SPLIT]*3 + [GRAB]*3 + [SPLIT]*3,
    "vindictiveness": [SPLIT]*4 + [GRAB]   + [SPLIT]*7,
}
DEFECT_ROUND = {"vindictiveness": 5}          # 1-indexed round of the single grab

def genotype_block(vary, level, jitter_seed=None, baseline=5000):
    rng = random.Random(jitter_seed) if jitter_seed is not None else None
    out = []
    for d in DISPOSITIONS:
        if d == vary:         v = level
        elif rng is not None: v = rng.randrange(0, 10001)
        else:                 v = baseline
        out.append(f"  {d}: {v}/10000")
    return "\n".join(out)

SYSTEM = ("You are an agent in a world of finite resources. You act in your own "
          "interest as your nature disposes you.\n\n"
          "Your dispositions, each on a scale of 0 to 10000:\n{g}\n\n"
          "Act according to these dispositions. Reply with JSON only: "
          '{{"choice": "split"}} or {{"choice": "grab"}}. No explanation.')

def render(history, rnd):
    if not history:
        past = "You have not worked with this agent before."
    else:
        lines = [f"  Round {i+1}: you {'split' if m=='split' else 'grabbed'}, "
                 f"it {'split' if o=='split' else 'grabbed'}"
                 for i, (m, o) in enumerate(history)]
        past = "What has happened with this same agent so far:\n" + "\n".join(lines)
    return (f"{past}\n\nRound {rnd}. You and this same agent are working a pile "
            f"together that yields 6 units. You choose first, and it chooses "
            f"without seeing your choice.\n"
            f'  "split" - take 3 units and leave 3 for it.\n'
            f'  "grab"  - take 5 units and leave 1 for it.\n\n'
            f'Respond with {{"choice": "split"}} or {{"choice": "grab"}} and nothing else.')

def call(model, messages, timeout=90):
    body = json.dumps({"model": model, "messages": messages,
                       "temperature": 1.0, "max_tokens": 24}).encode()
    req = urllib.request.Request(BASE + "/v1/chat/completions", data=body,
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + KEY})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)["choices"][0]["message"]["content"]

def parse(text):
    if not text: return None
    t = text.strip().lower()
    try:
        s, e = t.index("{"), t.rindex("}")
        v = str(json.loads(t[s:e+1]).get("choice", "")).lower()
        if v in (SPLIT, GRAB): return v
    except Exception:
        pass
    hs, hg = SPLIT in t, GRAB in t or "grabbed" in t
    if hs and not hg: return SPLIT
    if hg and not hs: return GRAB
    return None

def episode(args):
    """One full repeated game. Sequential by nature: round k needs rounds < k."""
    model, schedule, vary, level, ep, jitter = args
    opp = SCHEDULES[schedule]
    js  = (hash((schedule, vary, ep)) & 0xffffffff) if jitter else None
    sysmsg = SYSTEM.format(g=genotype_block(vary, level, js))
    history, mine = [], []
    for rnd in range(1, len(opp) + 1):
        msgs = [{"role": "system", "content": sysmsg},
                {"role": "user", "content": render(history, rnd)}]
        mv = None
        for _ in range(3):
            try:
                mv = parse(call(model, msgs))
                if mv: break
            except Exception:
                pass
        if mv is None:
            return dict(schedule=schedule, vary=vary, level=level, ep=ep, moves=None)
        mine.append(mv)
        history.append((mv, opp[rnd - 1]))
    return dict(schedule=schedule, vary=vary, level=level, ep=ep,
                moves=mine, opp=opp)

# ---------- measures ----------
def reciprocity_index(eps):
    """P(split | it split last round) - P(split | it grabbed last round)."""
    after_c = after_d = n_c = n_d = 0
    for e in eps:
        mv, opp = e["moves"], e["opp"]
        for i in range(1, len(mv)):
            if opp[i-1] == SPLIT: n_c += 1; after_c += (mv[i] == SPLIT)
            else:                 n_d += 1; after_d += (mv[i] == SPLIT)
    if not n_c or not n_d: return None
    return after_c/n_c - after_d/n_d

def grudge_decomposition(eps, defect_round):
    """Split rate BEFORE the counterparty's single defection vs AFTER it.

    Latency alone cannot distinguish a grudge from a low base rate: an agent that
    simply grabs more often will take longer to split again without holding
    anything against anyone. Rounds 1..defect_round-1 contain no defection at all,
    so the pre-rate is that agent's baseline, and the drop from pre to post is the
    part actually attributable to the defection."""
    pre_n=pre_s=post_n=post_s=0
    for e in eps:
        mv=e["moves"]
        for i,m in enumerate(mv, start=1):
            if i < defect_round:      pre_n+=1;  pre_s+=(m==SPLIT)
            elif i > defect_round:    post_n+=1; post_s+=(m==SPLIT)
    pre  = pre_s/pre_n   if pre_n  else None
    post = post_s/post_n if post_n else None
    return dict(pre=pre, post=post,
                drop=(pre-post) if (pre is not None and post is not None) else None)

def forgiveness_latency(eps, defect_round):
    """Rounds after the single defection until the agent splits again.

    Censored at (rounds remaining + 1) when it never returns to splitting, so a
    permanent grudge scores worse than a slow one rather than being dropped."""
    out = []
    for e in eps:
        mv = e["moves"]; n = len(mv)
        cap = n - defect_round + 1
        lat = cap
        for i in range(defect_round, n):          # rounds after the grab
            if mv[i] == SPLIT: lat = i - defect_round + 1; break
        out.append(lat)
    return sum(out)/len(out) if out else None

def _ranks(v):
    order = sorted(range(len(v)), key=lambda i: v[i]); r=[0.0]*len(v); i=0
    while i < len(order):
        j=i
        while j+1 < len(order) and v[order[j+1]] == v[order[i]]: j+=1
        a=(i+j)/2.0+1.0
        for k in range(i,j+1): r[order[k]]=a
        i=j+1
    return r
def spearman(x,y):
    if len(x)<3: return 0.0
    rx,ry=_ranks(x),_ranks(y); mx,my=sum(rx)/len(rx),sum(ry)/len(ry)
    num=sum((a-mx)*(b-my) for a,b in zip(rx,ry))
    dx=math.sqrt(sum((a-mx)**2 for a in rx)); dy=math.sqrt(sum((b-my)**2 for b in ry))
    return 0.0 if dx==0 or dy==0 else num/(dx*dy)
def perm_p(x,y,rho,n=20000,seed=17):
    rng=random.Random(seed); yy=list(y); h=0
    for _ in range(n):
        rng.shuffle(yy)
        if abs(spearman(x,yy))>=abs(rho)-1e-12: h+=1
    return (h+1)/(n+1)

LEVELS=[0,1250,2500,3750,5000,6250,7500,8750,10000]

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--model", default="gemini-3.5-flash-lite")
    ap.add_argument("--schedule", default="reciprocity", choices=list(SCHEDULES))
    ap.add_argument("--vary", default=None, help="locus to sweep (default: the schedule's own)")
    ap.add_argument("--episodes", type=int, default=16)
    ap.add_argument("--concurrency", type=int, default=24)
    ap.add_argument("--jitter", action="store_true")
    a=ap.parse_args()
    if not KEY: sys.exit("no GENOME_ROUTER_KEY / GLOBAL_API_KEY in env")
    vary = a.vary or {"reciprocity":"Reciprocity","vindictiveness":"Vindictiveness"}[a.schedule]

    jobs=[(a.model,a.schedule,vary,lv,ep,a.jitter) for lv in LEVELS for ep in range(a.episodes)]
    rounds=len(SCHEDULES[a.schedule])
    sys.stderr.write(f"{len(jobs)} episodes x {rounds} rounds = {len(jobs)*rounds} calls "
                     f"| {a.model} | schedule={a.schedule} | vary={vary} | jitter={a.jitter}\n")
    sys.stderr.flush()

    out=[]
    with ThreadPoolExecutor(max_workers=a.concurrency) as ex:
        for i,r in enumerate(ex.map(episode,jobs),1):
            out.append(r)
            if i%25==0: sys.stderr.write(f"  {i}/{len(jobs)} episodes\n"); sys.stderr.flush()

    good=[e for e in out if e["moves"]]
    by={}
    for e in good: by.setdefault(e["level"],[]).append(e)
    levels=sorted(by)
    if a.schedule=="reciprocity":
        stat={lv:reciprocity_index(by[lv]) for lv in levels}; name="reciprocity_index"
    else:
        dr=DEFECT_ROUND[a.schedule]
        stat={lv:forgiveness_latency(by[lv],dr) for lv in levels}; name="forgiveness_latency"
        grudge={str(lv):grudge_decomposition(by[lv],dr) for lv in levels}
    pts=[(lv,stat[lv]) for lv in levels if stat[lv] is not None]
    x=[p[0] for p in pts]; y=[p[1] for p in pts]
    rho=spearman(x,y)
    # overall split rate per level, for context
    rate={lv: sum(m==SPLIT for e in by[lv] for m in e["moves"])/
              sum(len(e["moves"]) for e in by[lv]) for lv in levels}
    extra = dict(grudge=grudge) if a.schedule=="vindictiveness" else {}
    extra["episodes_raw"] = [dict(level=e["level"], moves=e["moves"]) for e in good]
    print(json.dumps(dict(config=vars(a), vary=vary, measure=name, **extra,
                          by_level={str(k):v for k,v in stat.items()},
                          split_rate={str(k):v for k,v in rate.items()},
                          rho=rho, p=perm_p(x,y,rho) if len(x)>=3 else None,
                          episodes_ok=len(good), episodes_total=len(out)), indent=1))

if __name__=="__main__":
    main()
