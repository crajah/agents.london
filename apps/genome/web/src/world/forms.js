// Client-side closed forms — MUST match genome_core/forms.py exactly
// (interface-spec Rule 6.13: same forms both sides; the arrival event is
// authoritative and any divergence is a bug in one of them).
export const CROSSING_SECONDS = 6 * 3600;
export const SPEED = 1 / CROSSING_SECONDS;

const dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);

export function legTimes(waypoints, departedAt) {
  let t = departedAt;
  const out = [t];
  for (let k = 0; k < waypoints.length - 1; k++) {
    t += dist(waypoints[k], waypoints[k + 1]) / SPEED;
    out.push(t);
  }
  return out;
}

export function routePosition(waypoints, departedAt, now) {
  const times = legTimes(waypoints, departedAt);
  if (now <= times[0]) return waypoints[0];
  if (now >= times[times.length - 1]) return waypoints[waypoints.length - 1];
  for (let k = 0; k < times.length - 1; k++) {
    if (now <= times[k + 1]) {
      const f = (now - times[k]) / (times[k + 1] - times[k]);
      const [ax, ay] = waypoints[k];
      const [bx, by] = waypoints[k + 1];
      return [ax + (bx - ax) * f, ay + (by - ay) * f];
    }
  }
  return waypoints[waypoints.length - 1];
}

export function routeHeading(waypoints, departedAt, now) {
  // cargo updates write single-point movement records: position without a
  // journey. No second point, no heading -- face east rather than crash.
  if (!waypoints || waypoints.length < 2) return 0;
  const times = legTimes(waypoints, departedAt);
  for (let k = 0; k < times.length - 1; k++) {
    if (now <= times[k + 1]) {
      const [ax, ay] = waypoints[k];
      const [bx, by] = waypoints[k + 1];
      return Math.atan2(by - ay, bx - ax);
    }
  }
  const [ax, ay] = waypoints[waypoints.length - 2];
  const [bx, by] = waypoints[waypoints.length - 1];
  return Math.atan2(by - ay, bx - ax);
}

export function pileQuantity(p, now) {
  const dt = Math.max(0, now - p.measured_at);
  return Math.min(p.cap, p.qty_at + p.rate * dt);
}

// Isometric projection — a render-time transform ONLY (interface-spec 6.4/6.5):
// world coords stay Cartesian everywhere else; hit-testing is the inverse.
export const ISO = { sx: 1, sy: 0.5 };
export function isoProject([x, y]) {
  return [(x - y) * ISO.sx, (x + y) * ISO.sy];
}
export function isoUnproject([px, py]) {
  const x = (px / ISO.sx + py / ISO.sy) / 2;
  const y = (py / ISO.sy - px / ISO.sx) / 2;
  return [x, y];
}
