// The world canvas, v2 — interface-spec §6, rebuilt after the treacle audit.
//
// Performance contract: display objects are PERSISTENT. Geometry is
// (re)tessellated only when the underlying data changes or on a slow cadence
// (piles 1Hz for fill-lightness); per-frame work is transform updates only.
// Nothing allocates in the ticker path; swapped-out objects are destroyed,
// not orphaned (Pixi removeChildren() does not destroy — the old code leaked
// GPU geometry sixty times a second and the tab drowned in GC).
import { Application, Container, Graphics } from "pixi.js";
import { Viewport } from "pixi-viewport";
import { routePosition, routeHeading, pileQuantity, isoProject, isoUnproject }
  from "./forms.js";

const WORLD_PX = 1000;

function lerpColour(hex, t) {
  const c = parseInt(hex.slice(1), 16);
  const r = 255 + ((c >> 16 & 255) - 255) * t;
  const g = 255 + ((c >> 8 & 255) - 255) * t;
  const b = 255 + ((c & 255) - 255) * t;
  return (r << 16) + (g << 8) | b;
}
const P = ([x, y]) => isoProject([x * WORLD_PX, y * WORLD_PX]);

// deterministic sub-contact display spread for agents parked on one point —
// visual only, never in data; radius stays inside the contact radius
function spread(uuid) {
  let h = 0;
  for (const ch of uuid) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  const a = (h % 628) / 100;
  return [Math.cos(a) * 0.006, Math.sin(a) * 0.006];
}

export async function createWorldCanvas(el, opts = {}) {
  const app = new Application();
  await app.init({ background: 0x101418, resizeTo: el, antialias: true });
  el.appendChild(app.canvas);

  const viewport = new Viewport({ events: app.renderer.events,
    worldWidth: WORLD_PX * 2, worldHeight: WORLD_PX * 1.5 });
  viewport.drag().pinch().wheel().decelerate();
  app.stage.addChild(viewport);
  viewport.moveCenter(0, WORLD_PX / 2);

  const layers = {};
  for (const name of ["terrain", "constructions", "muster", "routes",
                      "piles", "portals", "agents", "pulses"]) {
    layers[name] = new Container();
    viewport.addChild(layers[name]);
  }

  let snapshot = null;
  const ELECTRIC_BLUE = 0x2ee6ff;
  const PORTAL_PERIOD = 1.8;                 // seconds per collapse
  const portalCores = [];
  let followUuid = null;
  const agents = new Map();   // uuid -> {a, body, tri, ring, route, pulse, pos}
  const piles = new Map();    // uuid -> {p, g, lastFill}
  let lastPileTick = 0;

  function clearLayer(l) { l.removeChildren().forEach(c => c.destroy(true)); }

  function buildAgent(a) {
    const body = new Graphics();
    const c1 = a.colour_pair?.[0] ?? "#cccccc";
    const c2 = a.colour_pair?.[1] ?? "#888888";
    if (opts.ownAgents?.has(a.agent_uuid))
      body.ellipse(0, 0, 15, 8).stroke({ width: 2, color: 0xffffff });
    body.ellipse(0, 0, 10, 5.5).fill({ color: c1 });
    if (a.infected)
      for (let k = 0; k < 6; k++)
        body.arc(0, 0, 12, k * Math.PI / 3, k * Math.PI / 3 + Math.PI / 5)
            .stroke({ width: 2, color: c1 });
    const tri = new Graphics();
    tri.poly([14, 0, -6, 6, -6, -6]).fill({ color: c2 });
    tri.scale.y = 0.5;                       // iso squash for the pointer
    layers.agents.addChild(body); layers.agents.addChild(tri);
    const route = new Graphics(); layers.routes.addChild(route);
    const pulse = new Graphics(); layers.pulses.addChild(pulse);
    pulse.ellipse(0, 0, 14, 7).stroke({ width: 1.5,
      color: a.colour_pair?.[0] ?? "#cccccc", alpha: 0.6 });
    return { a, body, tri, route, pulse, pos: [0.5, 0.5] };
  }

  function drawRouteOnce(e) {
    e.route.clear();
    const m = e.a.movement;
    if (!m || m.waypoints.length < 2) return;
    const pts = m.waypoints.map(P);
    e.route.moveTo(pts[0][0], pts[0][1]);
    for (let k = 1; k < pts.length; k++)
      e.route.lineTo(pts[k][0], pts[k][1]);
    e.route.stroke({ width: 2,
      color: e.a.colour_pair?.[1] ?? "#888888", alpha: 0.35 });
  }

  function setSnapshot(s) {
    snapshot = s;
    clearLayer(layers.terrain);
    for (const o of s.terrain ?? []) {
      const g = new Graphics();
      const [cx, cy] = P([o.x, o.y]);
      g.ellipse(cx, cy, o.r * WORLD_PX, o.r * WORLD_PX * 0.5)
        .fill({ color: 0x3a3f45 });
      layers.terrain.addChild(g);
    }
    // the marketplace stall — a two-tone canopy over the listing board
    if (s.market) {
      const g = new Graphics();
      const [cx, cy] = P([s.market.x, s.market.y]);
      g.ellipse(cx, cy, 20, 10).fill({ color: 0x000000, alpha: 0.25 });
      g.poly([cx - 16, cy - 2, cx + 16, cy - 2, cx + 20, cy - 14,
              cx - 20, cy - 14]).fill({ color: mcap1 ?? 0xd8c090 });
      g.poly([cx - 20, cy - 14, cx + 20, cy - 14, cx + 14, cy - 24,
              cx - 14, cy - 24]).fill({ color: 0xd85c3c });
      g.poly([cx - 14, cy - 24, cx, cy - 30, cx + 14, cy - 24])
        .fill({ color: 0xf0e0b0 });
      g.moveTo(cx - 16, cy - 2).lineTo(cx - 16, cy + 6)
        .stroke({ width: 2, color: 0x8a6f4d });
      g.moveTo(cx + 16, cy - 2).lineTo(cx + 16, cy + 6)
        .stroke({ width: 2, color: 0x8a6f4d });
      const n = (s.market_open ?? []).length;
      if (n > 0)
        for (let k = 0; k < Math.min(n, 5); k++)
          g.rect(cx - 12 + k * 6, cy - 12, 4, 6)
            .fill({ color: 0xffffff, alpha: 0.85 });
      layers.muster.addChild(g);
    }
    // muster flags — five per world, striped in the world's colour pair;
    // the drop points where agents deliver their load
    clearLayer(layers.muster);
    const mc1 = s.colours?.[0] ?? "#cccccc", mc2 = s.colours?.[1] ?? "#888888";
    const mcap1 = 0xd8c090;
    for (const m of s.muster_points ?? []) {
      const g = new Graphics();
      const [cx, cy] = P([m.x, m.y]);
      g.ellipse(cx, cy, 14, 7).fill({ color: 0x000000, alpha: 0.25 });
      g.moveTo(cx, cy).lineTo(cx, cy - 34)
        .stroke({ width: 2.5, color: 0xd8d0c0 });
      // three-striped pennant, alternating world colours
      const fw = 22, fh = 12, fy = cy - 34;
      for (let k = 0; k < 3; k++)
        g.poly([cx, fy + k * fh / 3,
                cx + fw * (1 - k * 0.12), fy + k * fh / 3 + fh / 6,
                cx + fw * (1 - (k + 1) * 0.12), fy + (k + 1) * fh / 3 + fh / 6,
                cx, fy + (k + 1) * fh / 3])
         .fill({ color: k % 2 === 0 ? mc1 : mc2 });
      layers.muster.addChild(g);
    }
    // constructions — Phase 10's surface arrives ahead of its mechanics:
    // interim stages read as scaffolded towers filling bottom-up; the Ark
    // reads as a ribbed hull growing rib by rib. progress is 0..1.
    clearLayer(layers.constructions);
    for (const c of s.constructions ?? []) {
      const g = new Graphics();
      const [cx, cy] = P([c.x, c.y]);
      const col = c.colour ?? mc1;
      const prog = Math.max(0, Math.min(1, c.progress ?? 0));
      if (c.name === "cache") {
        const holdings = Object.values(c.holdings ?? {})
          .reduce((a, b) => a + b, 0);
        const W = 16 + Math.min(10, holdings);
        const cc1 = c.colours?.[0] ?? col, cc2 = c.colours?.[1] ?? col;
        g.ellipse(cx, cy, W, W * 0.5).fill({ color: 0x000000, alpha: 0.25 });
        g.poly([cx - W, cy, cx, cy - W * 0.5, cx + W, cy, cx, cy + W * 0.5])
          .fill({ color: cc1 });
        g.poly([cx - W, cy, cx, cy - W * 0.5, cx, cy - W * 0.5 - 8,
                cx - W, cy - 8]).fill({ color: cc2 });
        g.poly([cx + W, cy, cx, cy - W * 0.5, cx, cy - W * 0.5 - 8,
                cx + W, cy - 8]).fill({ color: cc2, alpha: 0.7 });
        layers.constructions.addChild(g);
        continue;
      }
      if (c.kind === "ark" && c.wreck) {
        // a broken hull, listing: keel snapped in two, half the ribs gone,
        // the rest leaning -- until the next flood takes it
        const W = 90, H = 40;
        g.ellipse(cx, cy, W * 0.7, 10).fill({ color: 0x000000, alpha: 0.2 });
        g.moveTo(cx - W / 2, cy - H * 0.5)
          .quadraticCurveTo(cx - W * 0.3, cy + 2, cx - W * 0.08, cy + 4)
          .stroke({ width: 2, color: col, alpha: 0.35 });
        g.moveTo(cx + W * 0.12, cy + 2)
          .quadraticCurveTo(cx + W * 0.4, cy - 4, cx + W / 2, cy - H * 0.7)
          .stroke({ width: 2, color: col, alpha: 0.35 });
        const ribs = [[-0.38, 0.55, -0.25], [-0.26, 0.7, -0.15],
                      [-0.12, 0.4, 0.1], [0.2, 0.5, 0.3], [0.34, 0.65, 0.2]];
        for (const [fx, len, lean] of ribs) {
          const bx = cx + fx * W;
          g.moveTo(bx, cy - H * 0.1)
            .lineTo(bx + lean * 20, cy - H * 0.1 - H * len)
            .stroke({ width: 3, color: col, alpha: 0.4 });
        }
        g.moveTo(cx - W * 0.05, cy - 2).lineTo(cx + W * 0.09, cy + 6)
          .stroke({ width: 2, color: col, alpha: 0.25 });   // the snap
        layers.constructions.addChild(g);
        continue;
      }
      if (c.kind === "ark") {
        const W = 90, H = 40;
        g.ellipse(cx, cy, W * 0.7, 10).fill({ color: 0x000000, alpha: 0.25 });
        // keel + deck outline, ghosted until built
        g.moveTo(cx - W / 2, cy - H)
          .quadraticCurveTo(cx - W * 0.45, cy, cx, cy + 4)
          .quadraticCurveTo(cx + W * 0.45, cy, cx + W / 2, cy - H)
          .stroke({ width: 2, color: col, alpha: 0.25 });
        g.moveTo(cx - W / 2, cy - H).lineTo(cx + W / 2, cy - H)
          .stroke({ width: 2, color: col, alpha: 0.25 });
        // ribs rise with progress, stern to bow
        const ribs = 9, done = Math.round(prog * ribs);
        for (let k = 0; k < ribs; k++) {
          const fx = cx - W / 2 + (k + 0.5) * (W / ribs);
          const depth = H * (0.35 + 0.65 * Math.sin(Math.PI * (k + 0.5) / ribs));
          g.moveTo(fx, cy - H).lineTo(fx, cy - H + depth)
            .stroke({ width: 3, color: col, alpha: k < done ? 0.95 : 0.15 });
        }
        if (prog >= 0.7)                       // mast goes up late
          g.moveTo(cx, cy - H).lineTo(cx, cy - H - 26)
            .stroke({ width: 2.5, color: col });
      } else {
        // interim stage: scaffolded tower, taller by tier, filled by progress
        const W = 34, H = 24 + (c.tier ?? 1) * 8;
        g.ellipse(cx, cy, W * 0.8, 8).fill({ color: 0x000000, alpha: 0.25 });
        const filled = H * prog;
        g.rect(cx - W / 2, cy - filled, W, filled)
          .fill({ color: col, alpha: 0.8 });
        g.rect(cx - W / 2, cy - H, W, H)
          .stroke({ width: 1.5, color: col, alpha: 0.45 });
        for (let yy = cy; yy > cy - H + 6; yy -= 8)   // cross-braces read
          g.moveTo(cx - W / 2, yy).lineTo(cx + W / 2, yy - 6)   // as scaffold
            .stroke({ width: 1, color: 0xd8d0c0, alpha: 0.3 });
      }
      layers.constructions.addChild(g);
    }
    clearLayer(layers.portals);
    portalCores.length = 0;
    for (const pt of s.portals ?? []) {
      const g = new Graphics();
      const [cx, cy] = P([pt.x, pt.y]);
      const R = 26;
      g.arc(cx, cy, R, -Math.PI / 2, Math.PI / 2)
        .stroke({ width: 6, color: pt.dest_colours?.[0] ?? "#ffffff" });
      g.arc(cx, cy, R, Math.PI / 2, 3 * Math.PI / 2)
        .stroke({ width: 6, color: pt.dest_colours?.[1] ?? "#ffffff" });
      layers.portals.addChild(g);
      // the throat: an electric-blue disc collapsing endlessly inward
      const core = new Graphics();
      core.ellipse(0, 0, R - 8, (R - 8) * 0.5)
        .fill({ color: ELECTRIC_BLUE, alpha: 0.9 });
      core.ellipse(0, 0, R - 8, (R - 8) * 0.5)
        .stroke({ width: 1.5, color: 0xffffff, alpha: 0.5 });
      core.position.set(cx, cy);
      layers.portals.addChild(core);
      const glow = new Graphics();
      glow.ellipse(0, 0, R - 4, (R - 4) * 0.5)
        .fill({ color: ELECTRIC_BLUE, alpha: 0.18 });
      glow.position.set(cx, cy);
      layers.portals.addChild(glow);
      portalCores.push({ core, glow, phase: (cx * 7919) % PORTAL_PERIOD });
    }
    // piles: persist, rebuild only membership
    const seenP = new Set();
    for (const p of s.piles ?? []) {
      seenP.add(p.pile_uuid);
      if (!piles.has(p.pile_uuid)) {
        const g = new Graphics();
        layers.piles.addChild(g);
        piles.set(p.pile_uuid, { p, g, lastFill: -1 });
      } else piles.get(p.pile_uuid).p = p;
    }
    for (const [id, e] of piles)
      if (!seenP.has(id)) { e.g.destroy(true); piles.delete(id); }
    // agents: persist bodies, rebuild only membership / changed looks
    const seenA = new Set();
    for (const a of s.agents ?? []) {
      seenA.add(a.agent_uuid);
      const cur = agents.get(a.agent_uuid);
      if (!cur) {
        agents.set(a.agent_uuid, buildAgent(a));
        drawRouteOnce(agents.get(a.agent_uuid));
      } else {
        const lookChanged = cur.a.infected !== a.infected;
        const routeChanged =
          JSON.stringify(cur.a.movement) !== JSON.stringify(a.movement);
        cur.a = a;
        if (lookChanged) {
          for (const k of ["body", "tri", "pulse"]) cur[k].destroy(true);
          cur.route.destroy(true);
          agents.set(a.agent_uuid, buildAgent(a));
          drawRouteOnce(agents.get(a.agent_uuid));
        } else if (routeChanged) drawRouteOnce(cur);
      }
    }
    for (const [id, e] of agents)
      if (!seenA.has(id)) {
        for (const k of ["body", "tri", "route", "pulse"]) e[k].destroy(true);
        agents.delete(id);
      }
    forceDraw(Date.now() / 1000);
  }

  function forceDraw(now) { lastPileTick = 0; tick(now); }

  function tick(now) {
    if (!snapshot) return;
    // piles at 1Hz — fill lightness changes over minutes
    if (now - lastPileTick > 1.0) {
      lastPileTick = now;
      const kindColour = {};
      (snapshot.kinds ?? []).forEach((k, i) =>
        kindColour[k] = snapshot.colours?.[i] ?? "#888888");
      for (const e of piles.values()) {
        const fill = e.p.cap > 0 ? pileQuantity(e.p, now) / e.p.cap : 0;
        if (Math.abs(fill - e.lastFill) < 0.01) continue;
        e.lastFill = fill;
        const R = 12 + (e.p.cap / 50) * 26;
        const [cx, cy] = P([e.p.x, e.p.y]);
        e.g.clear();
        for (const [dx, dy, s] of [[-0.5, -0.2, 0.8], [0.5, -0.15, 0.75],
                                   [0, 0, 1], [-0.2, 0.25, 0.7],
                                   [0.3, 0.3, 0.65]])
          e.g.ellipse(cx + dx * R, cy + dy * R * 0.5, R * s, R * s * 0.55)
            .fill({ color: lerpColour(kindColour[e.p.kind] ?? "#888888",
                                      fill), alpha: 0.85 });
      }
    }
    // portal throats every frame — transforms only: the disc shrinks to
    // the centre and is reborn at the rim, matter forever falling in
    for (const p of portalCores) {
      const f = 1 - (((now + p.phase) % PORTAL_PERIOD) / PORTAL_PERIOD);
      p.core.scale.set(f);
      p.core.alpha = 0.25 + 0.75 * f;
      const g = 1 - f;
      p.glow.scale.set(0.6 + 0.4 * g);
      p.glow.alpha = 0.10 + 0.20 * g;
    }
    // agents every frame — transforms only, zero allocation
    for (const e of agents.values()) {
      const m = e.a.movement;
      let pos = [0.5, 0.5], head = 0, moving = false;
      if (m) {
        pos = routePosition(m.waypoints, m.departed_at, now, m.arrives_at);
        head = routeHeading(m.waypoints, m.departed_at, now, m.arrives_at);
        moving = now < m.arrives_at;
      }
      if (!moving) {
        const [sx, sy] = spread(e.a.agent_uuid);
        pos = [pos[0] + sx, pos[1] + sy];
      }
      e.pos = pos;
      const [cx, cy] = P(pos);
      e.body.position.set(cx, cy);
      e.tri.position.set(cx, cy);
      // heading in world space -> screen: project a unit heading vector
      const [hx, hy] = P([pos[0] + Math.cos(head) * 0.01,
                          pos[1] + Math.sin(head) * 0.01]);
      e.tri.rotation = Math.atan2(hy - cy, hx - cx);
      e.route.visible = moving;
      e.pulse.visible = moving;
      if (moving) {
        e.pulse.position.set(cx, cy);
        const s = 1 + 0.25 * Math.sin(now * 3);
        e.pulse.scale.set(s, s);
      }
    }
    if (followUuid && agents.has(followUuid)) {
      const [cx, cy] = P(agents.get(followUuid).pos);
      viewport.moveCenter(cx, cy);
    }
  }

  // ---- hit-testing: nearest entity of any kind via the iso inverse ----
  function entityAt(worldPt) {
    const [wx, wy] = isoUnproject([worldPt.x, worldPt.y]);
    const q = [wx / WORLD_PX, wy / WORLD_PX];
    let best = null, bestD = 0.035;
    for (const e of agents.values()) {
      const d = Math.hypot(e.pos[0] - q[0], e.pos[1] - q[1]);
      if (d < bestD) { bestD = d; best = { type: "agent", data: e.a }; }
    }
    for (const e of piles.values()) {
      const d = Math.hypot(e.p.x - q[0], e.p.y - q[1]);
      if (d < bestD) { bestD = d; best = { type: "pile", data: e.p }; }
    }
    for (const pt of snapshot?.portals ?? []) {
      const d = Math.hypot(pt.x - q[0], pt.y - q[1]);
      if (d < bestD) { bestD = d; best = { type: "portal", data: pt }; }
    }
    if (snapshot?.market) {
      const d = Math.hypot(snapshot.market.x - q[0],
                           snapshot.market.y - q[1]);
      if (d < bestD) { bestD = d;
        best = { type: "market",
                 data: { ...snapshot.market,
                         listings: snapshot.market_open ?? [] } }; }
    }
    (snapshot?.muster_points ?? []).forEach((m, i) => {
      const d = Math.hypot(m.x - q[0], m.y - q[1]);
      if (d < bestD) { bestD = d; best = { type: "muster", data: { ...m, idx: i } }; }
    });
    for (const c of snapshot?.constructions ?? []) {
      const d = Math.hypot(c.x - q[0], c.y - q[1]);
      if (d < bestD) { bestD = d; best = { type: "construction", data: c }; }
    }
    return best;
  }

  viewport.on("clicked", (e) => {
    const hit = entityAt(e.world);
    if (hit) opts.onEntityMenu?.(hit, e.event.global);
  });
  app.canvas.addEventListener("contextmenu", (ev) => {
    ev.preventDefault();
    const world = viewport.toWorld(ev.offsetX, ev.offsetY);
    const hit = entityAt(world);
    if (hit) opts.onEntityMenu?.(hit, { x: ev.offsetX, y: ev.offsetY });
  });

  app.ticker.add(() => tick(opts.clock ? opts.clock() : Date.now() / 1000));
  return {
    setSnapshot,
    follow: (uuid) => { followUuid = uuid; },
    destroy: () => app.destroy(true, { children: true, texture: true }),
  };
}
