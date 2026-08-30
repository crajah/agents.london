// The client against a REAL captured snapshot shape (in-cluster fixture):
// every agent's position derivable, every pile's quantity finite and clamped.
import { describe, it, expect } from "vitest";
import { routePosition, pileQuantity } from "./forms.js";
import snap from "./fixture-snapshot.json";

describe("client renders a live snapshot", () => {
  it("derives a finite position for every agent, now and later", () => {
    for (const a of snap.agents) {
      for (const t of [0, a.movement.departed_at + 100,
                       a.movement.arrives_at + 100]) {
        const [x, y] = routePosition(a.movement.waypoints,
                                     a.movement.departed_at, t);
        expect(Number.isFinite(x) && Number.isFinite(y)).toBe(true);
        expect(x).toBeGreaterThanOrEqual(0); expect(x).toBeLessThanOrEqual(1);
      }
    }
  });
  it("arrival lands exactly on the final waypoint (authoritative, 6.13)", () => {
    const a = snap.agents[0];
    const p = routePosition(a.movement.waypoints, a.movement.departed_at,
                            a.movement.arrives_at);
    const last = a.movement.waypoints[a.movement.waypoints.length - 1];
    expect(Math.abs(p[0] - last[0])).toBeLessThan(1e-9);
  });
  it("pile quantities clamp to cap and never go negative", () => {
    for (const p of snap.piles) {
      const q = pileQuantity(p, p.measured_at + 86400 * 30);
      expect(q).toBeLessThanOrEqual(p.cap + 1e-9);
      expect(pileQuantity(p, p.measured_at)).toBeGreaterThanOrEqual(0);
    }
  });
  it("snapshot carries the full visual grammar's inputs", () => {
    expect(snap.colours.length).toBe(2);
    expect(snap.terrain.length).toBeGreaterThan(0);
    expect(snap.agents[0].colour_pair.length).toBe(2);
  });
});
