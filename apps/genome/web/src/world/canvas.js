// The world canvas — interface-spec §6. Pixi driven imperatively (Rule 6.2):
// the scene is derived from TIME, never from React state. One texture atlas's
// worth of generated shapes, tinted per entity, so batching holds (6.12).
//
// Visual grammar (6.8-6.10): the canvas shows what agents can see. An agent IS
// its two colours — disc in the first, heading triangle in the second (6.9a-c),
// broken outline when infected (6.9i). A pile is a soft cloud: hue = kind,
// lightness = fill, size = capacity (6.9e/6.9f). A portal is a hollow ring in
// its DESTINATION's pair (6.9h). Terrain blocks everyone identically (5.5).
import { Application, Container, Graphics } from "pixi.js";
import { Viewport } from "pixi-viewport";
import { routePosition, routeHeading, pileQuantity, isoProject, isoUnproject } from "./forms.js";

const WORLD_PX = 1000;               // unit square -> pixels before projection

function lerpColour(hex, t) {        // white -> hex as fill deepens (6.9f)
  const c = parseInt(hex.slice(1), 16);
  const r = 255 + ((c >> 16 & 255) - 255) * t;
  const g = 255 + ((c >> 8 & 255) - 255) * t;
  const b = 255 + ((c & 255) - 255) * t;
  return (r << 16) + (g << 8) | b;
}

const P = ([x, y]) => {
  const [px, py] = isoProject([x * WORLD_PX, y * WORLD_PX]);
  return [px, py];
};

export async function createWorldCanvas(el, opts = {}) {
  const app = new Application();
  await app.init({ background: 0x101418, resizeTo: el, antialias: true });
  el.appendChild(app.canvas);

  const viewport = new Viewport({
    events: app.renderer.events,
    worldWidth: WORLD_PX * 2, worldHeight: WORLD_PX * 1.5,
  });
  viewport.drag().pinch().wheel().decelerate();      // Rule 6.11
  app.stage.addChild(viewport);
  viewport.moveCenter(0, WORLD_PX / 2);

  const layers = { terrain: new Container(), piles: new Container(),
                   portals: new Container(), agents: new Container() };
  for (const l of Object.values(layers)) viewport.addChild(l);

  let snapshot = null;
  const agentSprites = new Map();
  const pileSprites = new Map();

  function setSnapshot(s) {
    snapshot = s;
    layers.terrain.removeChildren();
    for (const o of s.terrain ?? []) {
      const g = new Graphics();
      const [cx, cy] = P([o.x, o.y]);
      g.ellipse(cx, cy, o.r * WORLD_PX, o.r * WORLD_PX * 0.5)
        .fill({ color: 0x3a3f45 });
      layers.terrain.addChild(g);
    }
    layers.piles.removeChildren(); pileSprites.clear();
    for (const p of s.piles ?? []) {
      const g = new Graphics();
      layers.piles.addChild(g);
      pileSprites.set(p.pile_uuid, { g, p });
    }
    layers.portals.removeChildren();
    for (const pt of s.portals ?? []) {
      const g = new Graphics();
      const [cx, cy] = P([pt.x, pt.y]);
      const R = 26;
      g.arc(cx, cy, R, -Math.PI / 2, Math.PI / 2)
        .stroke({ width: 6, color: pt.colours?.[0] ?? "#ffffff" });
      g.arc(cx, cy, R, Math.PI / 2, 3 * Math.PI / 2)
        .stroke({ width: 6, color: pt.colours?.[1] ?? "#ffffff" });
      layers.portals.addChild(g);
    }
    layers.agents.removeChildren(); agentSprites.clear();
    for (const a of s.agents ?? []) {
      const g = new Graphics();
      layers.agents.addChild(g);
      agentSprites.set(a.agent_uuid, { g, a });
    }
  }

  function draw(now) {
    if (!snapshot) return;
    const kindColour = {};
    (snapshot.kinds ?? []).forEach((k, i) =>
      kindColour[k] = snapshot.colours?.[i] ?? "#888888");
    for (const { g, p } of pileSprites.values()) {
      const q = pileQuantity(p, now);
      const fill = p.cap > 0 ? q / p.cap : 0;
      const R = 12 + (p.cap / 50) * 26;            // size = capacity (6.9e)
      const [cx, cy] = P([p.x, p.y]);
      g.clear();
      for (const [dx, dy, s] of [[-0.5, -0.2, 0.8], [0.5, -0.15, 0.75],
                                 [0, 0, 1], [-0.2, 0.25, 0.7], [0.3, 0.3, 0.65]]) {
        g.ellipse(cx + dx * R, cy + dy * R * 0.5, R * s, R * s * 0.55)
          .fill({ color: lerpColour(kindColour[p.kind] ?? "#888888", fill),
                  alpha: 0.85 });
      }
    }
    for (const { g, a } of agentSprites.values()) {
      let pos = [0.5, 0.5], head = 0;
      if (a.movement) {
        pos = routePosition(a.movement.waypoints, a.movement.departed_at, now);
        head = routeHeading(a.movement.waypoints, a.movement.departed_at, now);
      }
      const [cx, cy] = P(pos);
      const c1 = a.colour_pair?.[0] ?? "#cccccc";
      const c2 = a.colour_pair?.[1] ?? "#888888";
      g.clear();
      if (opts.ownAgents?.has(a.agent_uuid))       // ownership ring (6.9d)
        g.ellipse(cx, cy, 15, 8).stroke({ width: 2, color: 0xffffff });
      g.ellipse(cx, cy, 10, 5.5).fill({ color: c1 });
      if (a.infected)                               // broken outline (6.9i)
        for (let k = 0; k < 6; k++)
          g.arc(cx, cy, 12, k * Math.PI / 3, k * Math.PI / 3 + Math.PI / 5)
            .stroke({ width: 2, color: c1 });
      // heading triangle in world space, projected (6.9b/6.9c)
      const t = 0.014;
      const tip = P([pos[0] + Math.cos(head) * t, pos[1] + Math.sin(head) * t]);
      const l = P([pos[0] + Math.cos(head + 2.5) * t * 0.6,
                   pos[1] + Math.sin(head + 2.5) * t * 0.6]);
      const r = P([pos[0] + Math.cos(head - 2.5) * t * 0.6,
                   pos[1] + Math.sin(head - 2.5) * t * 0.6]);
      g.poly([tip[0], tip[1], l[0], l[1], r[0], r[1]]).fill({ color: c2 });
    }
  }

  // Hit-testing is the projection's inverse (Rule 6.5): pointer -> world
  // coords -> nearest agent within a small radius.
  viewport.on("clicked", (e) => {
    if (!snapshot || !opts.onAgentClick) return;
    const [wx, wy] = isoUnproject([e.world.x, e.world.y]);
    const now = opts.clock ? opts.clock() : Date.now() / 1000;
    let best = null, bestD = 0.03 * WORLD_PX;
    for (const { a } of agentSprites.values()) {
      let pos = [0.5, 0.5];
      if (a.movement)
        pos = routePosition(a.movement.waypoints, a.movement.departed_at, now);
      const d = Math.hypot(pos[0] * WORLD_PX - wx, pos[1] * WORLD_PX - wy);
      if (d < bestD) { bestD = d; best = a; }
    }
    if (best) opts.onAgentClick(best.agent_uuid);
  });

  app.ticker.add(() => draw(opts.clock ? opts.clock() : Date.now() / 1000));
  return { setSnapshot, destroy: () => app.destroy(true, { children: true }) };
}
