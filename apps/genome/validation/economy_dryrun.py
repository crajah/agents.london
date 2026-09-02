"""Economy dry-run (BUILD consequent task, the last ⚠): spreadsheet-level
simulation of mining -> cargo -> trade -> materialisation -> construction
under the LIVE calibration, answering the one falsifiable question the spec
keeps asking: IS AN ARK REACHABLE INSIDE A FLOOD CYCLE?

Deliberately arithmetic, not agentic: steady-state throughputs and journey
counts, best-case coordination (perfect cooperation, no combat, no illness,
no LLM dithering). If the answer is NO even here, the constants are wrong;
if it is YES only near the edge, the game has teeth. Run:

    python validation/economy_dryrun.py
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "core"))

from genome_core import construction as C
from genome_core.engine import (CARGO_CEILING, MINE_RATE_UNITS_PER_SEC,
                                MINE_STINT_UNITS)

H = 3600.0

# --- per-agent primitives (calibration, engine constants) -------------------
MINE_RATE = MINE_RATE_UNITS_PER_SEC * H          # 360 u/h at the face
STINT = MINE_STINT_UNITS                          # 5 u then decide again
DECIDE_OVERHEAD = 120.0                           # s between stints (dwell,
                                                  # walk, the queue)
CROSSING = 1.0 * H                                # world crossing (cal 1.2)
PILE_REGEN = 1.25 / H * H                         # ~1.25 u/h/pile mid-draw
PILES_PER_KIND = 8                                # mid of 6-10
REGEN_PER_KIND = PILE_REGEN * PILES_PER_KIND      # ~10 u/h/kind sustainable

def mine_rate_per_agent() -> float:
    """Units/hour one agent actually banks: stint + overhead cycles, capped
    by what the piles regrow when several agents share a world."""
    stint_s = STINT / MINE_RATE_UNITS_PER_SEC     # 50 s at the face
    cycle = stint_s + DECIDE_OVERHEAD
    return STINT / cycle * H                      # ~106 u/h uncapped


def world_output_per_hour(agents: int) -> float:
    """A world of two kinds sustains at most its regeneration; below that,
    agents are the bottleneck."""
    return min(agents * mine_rate_per_agent(), 2 * REGEN_PER_KIND)


def import_rate_per_courier() -> float:
    """Foreign kinds arrive 15 units at a time through two crossings (out
    through the commons, trade, home). Two hours per round trip, best case,
    plus the trade itself."""
    round_trip = 2 * CROSSING + 0.5 * H
    return CARGO_CEILING / (round_trip / H)       # 6 u/h per courier


# --- the bill ---------------------------------------------------------------
def tree_bill() -> dict:
    """Total units by 'local vs foreign' for one world raising the FULL
    canonical tree, its own two kinds counted local, everything else
    imported. Uses the live resolve_cost, so a calibration edit moves this
    number the day it lands."""
    local_kinds = [16, 3]                          # an earth+life world
    local = foreign = 0.0
    for name in C.TREE:
        for k, u in C.resolve_cost(name, local_kinds).items():
            if int(k) in local_kinds:
                local += u
            else:
                foreign += u
    return {"local": local, "foreign": foreign}


def days_to_ark(users: int, agents_per_user: int) -> float | None:
    """Best-case days for USERS cooperating worlds to raise one Ark: local
    units mined in parallel worlds, foreign units couriered, the tree's
    build clocks added serially at the end. None = impossible (contributor
    counts unreachable)."""
    if users < 8:
        return None                                # Rule 3.3: the Ark needs 8
    bill = tree_bill()
    agents = users * agents_per_user
    # local production runs in every world at once; the HOST world's two
    # kinds cover `local`, the other worlds' kinds arrive as imports, so:
    # host mines `local`, and (foreign) units must cross at courier rate.
    host_hours = bill["local"] / world_output_per_hour(agents_per_user)
    couriers = max(1, agents - agents_per_user)
    import_hours = bill["foreign"] / (couriers * import_rate_per_courier())
    gather_hours = max(host_hours, import_hours)   # they overlap
    build_hours = sum(C.BUILD_MINUTES[t] for t in
                      (1, 2, 3, 4, 5, 6)) / 60.0 * 3   # ~3 chains serial-ish
    return (gather_hours + build_hours) / 24.0


def main() -> None:
    bill = tree_bill()
    print("=== economy dry-run (best-case arithmetic) ===")
    print(f"one agent banks       ~{mine_rate_per_agent():6.0f} u/h at a face")
    print(f"a 2-kind world sustains {2 * REGEN_PER_KIND:6.0f} u/h regrowth")
    print(f"a courier imports     ~{import_rate_per_courier():6.0f} u/h")
    print(f"full tree bill: {bill['local']:.0f} local + "
          f"{bill['foreign']:.0f} foreign units "
          f"(resolve_cost, live constants)")
    print()
    print("days to one Ark (flood draws 15-30 days, countdown 2):")
    print(f"{'users':>6} {'agents/user':>12} {'days':>8}  verdict")
    for users in (8, 10, 12):
        for apu in (1, 2, 3):
            d = days_to_ark(users, apu)
            verdict = ("impossible" if d is None else
                       "comfortable" if d < 15 else
                       "a real race" if d < 30 else "out of reach")
            print(f"{users:>6} {apu:>12} "
                  f"{('-' if d is None else f'{d:8.1f}')}  {verdict}")
    print()
    print("under 8 users: impossible by construction (Rule 3.3) --")
    print("the Ark is a COALITION artifact and no calibration changes that.")


if __name__ == "__main__":
    main()
