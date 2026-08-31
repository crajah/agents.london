// Chrome is React; the canvas is not (interface-spec Rules 6.1/6.2).
import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { createWorldCanvas } from "./world/canvas.js";

const API = import.meta.env.VITE_GENOME_API ?? "";

function Bell() {
  const [items, setItems] = useState([]);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const load = () => fetch(`${API}/notifications`,
      { credentials: "include" }).then(r => r.json()).then(setItems);
    load(); const t = setInterval(load, 20000);
    return () => clearInterval(t);
  }, []);
  const unread = items.filter(i => !i.read).length;
  return (
    <span className="relative">
      <button onClick={() => setOpen(!open)} className="text-lg">
        🔔{unread > 0 && <span className="text-xs text-amber-400">{unread}</span>}
      </button>
      {open && (
        <div className="absolute right-0 top-8 w-96 max-h-80 overflow-y-auto
                        bg-neutral-800 border border-neutral-600 rounded p-2
                        text-sm z-10">
          {items.length === 0 && <div className="opacity-50">quiet so far</div>}
          {items.map(i => (
            <div key={i.key}
                 className={`py-1 border-b border-neutral-700 ${
                   i.read ? "opacity-50" : ""}`}>
              <span className="opacity-60">[{i.source}]</span> {i.message}
            </div>))}
          {unread > 0 &&
            <button className="mt-1 underline opacity-70" onClick={async () => {
              await fetch(`${API}/notifications/read`, { method: "POST",
                credentials: "include",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ keys: items.map(i => i.key) })});
              setItems(items.map(i => ({ ...i, read: true })));
            }}>mark all read</button>}
        </div>)}
    </span>);
}

function Connections() {
  const [open, setOpen] = useState(false);
  const [props, setProps] = useState({ incoming: [], outgoing: [] });
  const load = () =>
    fetch(`${API}/proposals`, { credentials: "include" })
      .then(r => r.json()).then(setProps).catch(() => {});
  useEffect(() => { load(); const t = setInterval(load, 30000);
    return () => clearInterval(t); }, []);
  const respond = async (key, accept) => {
    await fetch(`${API}/proposals/respond`, {
      method: "POST", credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key, accept }) });
    load();
  };
  const n = props.incoming.length;
  return (
    <div className="relative">
      <button onClick={() => setOpen(o => !o)} className="text-sm opacity-80">
        ⇄ {n > 0 && <span className="text-amber-400">{n}</span>}
      </button>
      {open && (
        <div className="absolute right-0 top-7 z-30 w-80 bg-neutral-800 border
                        border-neutral-600 rounded shadow-lg text-sm p-3">
          <div className="font-semibold mb-2">Connections</div>
          <div className="flex gap-3 mb-3">
            <a className="underline opacity-80"
               href={`${API}/contacts/import/google/start`}>
              Import Google contacts</a>
            <a className="underline opacity-80"
               href={`${API}/contacts/import/microsoft/start`}>
              Import Microsoft</a>
          </div>
          {props.incoming.length === 0 && props.outgoing.length === 0 &&
            <div className="opacity-60">No open proposals. Importing scans
              your address book, keeps only matches with existing users, and
              proposes links — addresses of non-users are never stored.</div>}
          {props.incoming.map(p => (
            <div key={p.key} className="flex items-center gap-2 py-1.5
                                        border-t border-neutral-700">
              <span className="flex-1">A user who has your address proposes
                linking worlds.</span>
              <button className="px-2 py-0.5 bg-emerald-700 rounded"
                      onClick={() => respond(p.key, true)}>Link</button>
              <button className="px-2 py-0.5 bg-neutral-700 rounded"
                      onClick={() => respond(p.key, false)}>Decline</button>
            </div>))}
          {props.outgoing.map(p => (
            <div key={p.key} className="py-1.5 border-t border-neutral-700
                                        opacity-60">
              Proposal sent — awaiting their confirmation.</div>))}
        </div>)}
    </div>);
}

function Ticker({ realm }) {
  const [lines, setLines] = useState([]);
  useEffect(() => {
    if (!realm) return;
    let since = "";
    const load = async () => {
      try {
        const r = await fetch(`${API}/worlds/${realm}/events?since=${since}`);
        const evs = await r.json();
        if (evs.length) {
          since = evs[evs.length - 1].done_at;
          setLines(l => [...evs.map(e =>
            `${(e.subject ?? "").slice(0, 18)} · ${e.kind}`), ...l].slice(0, 8));
        }
      } catch {}
    };
    load(); const t = setInterval(load, 8000);
    return () => clearInterval(t);
  }, [realm]);
  if (!lines.length) return null;
  return (
    <div className="absolute bottom-2 left-2 bg-neutral-900/80 rounded p-2
                    text-xs font-mono space-y-0.5 pointer-events-none">
      {lines.map((l, i) =>
        <div key={i} style={{ opacity: 1 - i * 0.11 }}>{l}</div>)}
    </div>);
}

function EntityMenu({ menu, onClose, onInspect, onFollow, onTravel }) {
  const { hit, x, y } = menu;
  const Item = ({ children, onClick }) => (
    <button onClick={onClick}
      className="block w-full text-left px-3 py-1.5 hover:bg-neutral-700">
      {children}</button>);
  const now = Date.now() / 1000;
  return (
    <div className="absolute z-20 bg-neutral-800 border border-neutral-600
                    rounded shadow-lg text-sm min-w-52"
         style={{ left: x + 8, top: y + 8 }}
         onMouseLeave={onClose}>
      {hit.type === "agent" && <>
        <div className="px-3 py-1.5 opacity-60 border-b border-neutral-700">
          {hit.data.name ?? hit.data.agent_uuid}
          {hit.data.infected && <span className="text-red-400"> · infected</span>}
        </div>
        <Item onClick={() => onInspect(hit.data.agent_uuid)}>Inspect genotype</Item>
        <Item onClick={() => onFollow(hit.data.agent_uuid)}>Follow</Item>
      </>}
      {hit.type === "pile" && (() => {
        const p = hit.data;
        const dt = Math.max(0, now - p.measured_at);
        const qty = Math.min(p.cap, p.qty_at + p.rate * dt);
        return <>
          <div className="px-3 py-1.5 opacity-60 border-b border-neutral-700">
            resource pile · kind {p.kind}</div>
          <div className="px-3 py-1.5">
            {qty.toFixed(1)} / {p.cap.toFixed(1)} units
            <div className="opacity-60">
              regenerates {(p.rate * 3600).toFixed(2)}/hour</div>
          </div>
        </>; })()}
      {hit.type === "portal" && <>
        <div className="px-3 py-1.5 opacity-60 border-b border-neutral-700">
          teleport portal
          <span className="ml-2">
            {(hit.data.dest_colours ?? []).map(c =>
              <span key={c} className="inline-block w-3 h-3 rounded-full mr-1"
                    style={{ background: c }} />)}
          </span>
        </div>
        <div className="px-3 py-1.5 opacity-70">to {hit.data.to_world}</div>
        <Item onClick={() => onTravel(hit.data.to_world)}>View that world</Item>
      </>}
      {hit.type === "muster" && <>
        <div className="px-3 py-1.5 opacity-60 border-b border-neutral-700">
          muster point {hit.data.idx + 1} of 5</div>
        <div className="px-3 py-1.5 opacity-70">
          agents deliver their load at the nearest flag</div>
      </>}
      {hit.type === "construction" && <>
        <div className="px-3 py-1.5 opacity-60 border-b border-neutral-700">
          {hit.data.kind === "ark" ? "the Ark" :
            `${hit.data.name ?? "construction"} · tier ${hit.data.tier ?? 1}`}
        </div>
        <div className="px-3 py-1.5">
          {Math.round((hit.data.progress ?? 0) * 100)}% built
        </div>
      </>}
    </div>);
}

function App() {
  const ref = useRef(null);
  const [realm, setRealm] = useState(
    new URLSearchParams(location.search).get("world") ?? "");
  const [me, setMe] = useState(null);
  useEffect(() => {
    fetch(`${API}/me`, { credentials: "include" })
      .then(r => r.json()).then(d => {
        setMe(d);
        if (!realm && d.world_realm) setRealm(d.world_realm);
      }).catch(() => setMe({ authenticated: false }));
  }, []);
  const [status, setStatus] = useState("no world selected");
  const [inspect, setInspect] = useState(null);   // Rule 13.1 panel
  const [menu, setMenu] = useState(null);         // {hit, x, y}
  const canvasApi = useRef(null);

  useEffect(() => {
    if (!realm || !ref.current) return;
    let canvas, timer, dead = false;
    (async () => {
      canvas = await createWorldCanvas(ref.current, {
        onEntityMenu: (hit, at) => setMenu({ hit, x: at.x, y: at.y }),
      });
      canvasApi.current = canvas;
      const load = async () => {
        try {
          const r = await fetch(`${API}/worlds/${realm}/snapshot`);
          if (!r.ok) throw new Error(r.status);
          canvas.setSnapshot(await r.json());
          setStatus(`watching ${realm}`);
        } catch (e) { setStatus(`cannot reach world: ${e.message}`); }
      };
      await load();
      timer = setInterval(load, 5000);     // events feed replaces this later
    })();
    return () => { dead = true; clearInterval(timer); canvas?.destroy(); };
  }, [realm]);

  return (
    <div className="h-screen w-screen flex flex-col bg-neutral-900 text-neutral-200">
      <header className="px-4 py-2 flex gap-3 items-center border-b border-neutral-700">
        <strong>genome</strong>
        <input className="bg-neutral-800 px-2 py-1 rounded text-sm w-72"
               placeholder="world realm…" defaultValue={realm}
               onKeyDown={e => e.key === "Enter" && setRealm(e.target.value)} />
        <span className="text-sm opacity-70">{status}</span>
        <span className="flex-1" />
        {me && !me.authenticated && <>
          <input className="bg-neutral-800 px-2 py-1 rounded text-sm w-56"
                 placeholder="your@email — enter to begin"
                 onKeyDown={async e => {
                   if (e.key !== "Enter") return;
                   const r = await fetch(`${API}/auth/email/login`, {
                     method: "POST", credentials: "include",
                     headers: { "Content-Type": "application/json" },
                     body: JSON.stringify({ email: e.target.value })});
                   const d = await r.json();
                   if (d.world_realm) { setMe({ authenticated: true,
                     world_realm: d.world_realm }); setRealm(d.world_realm); }
                 }} />
          <a className="text-sm underline opacity-80"
             href={`${API}/auth/google/login`}>Google</a>
          <a className="text-sm underline opacity-80"
             href={`${API}/auth/microsoft/login`}>Microsoft</a>
        </>}
        {me?.authenticated && <Connections />}
        {me?.authenticated && <Bell />}
        {me?.authenticated && me.verified === false &&
          <span className="text-xs px-2 py-0.5 rounded bg-amber-900
                           text-amber-200"
                title="A verification link was sent to your address">
            unverified</span>}
        {me?.authenticated &&
          <span className="text-sm opacity-60">your world: {me.world_realm}</span>}
      </header>
      <div className="flex-1 flex min-h-0 relative">
        <div ref={ref} className="flex-1" />
        <Ticker realm={realm} />
        {menu && <EntityMenu menu={menu} onClose={() => setMenu(null)}
          onInspect={async (uuid) => {
            const [r, rd] = await Promise.all([
              fetch(`${API}/agents/${uuid}`),
              fetch(`${API}/agents/${uuid}/decisions?limit=8`)]);
            setInspect({ ...(await r.json()), decisions: await rd.json() });
            setMenu(null);
          }}
          onFollow={(uuid) => { canvasApi.current?.follow(uuid); setMenu(null); }}
          onTravel={(toWorld) => {
            history.pushState({}, "", `?world=${toWorld}`);
            setInspect(null); setMenu(null); setRealm(toWorld);
          }} />}
        {inspect && (
          <aside className="w-80 overflow-y-auto border-l border-neutral-700 p-3 text-sm">
            <div className="flex justify-between items-center mb-2">
              <strong>{inspect.name ?? inspect.agent_uuid}</strong>
              <button onClick={() => setInspect(null)} className="opacity-60">✕</button>
            </div>
            <div className="flex gap-1 mb-3">
              {(inspect.colour_pair ?? []).map(c =>
                <span key={c} className="w-5 h-5 rounded-full inline-block"
                      style={{ background: c }} />)}
              {inspect.infected && <span className="text-red-400 ml-2">infected</span>}
            </div>
            {inspect.dispositions && <>
              <h4 className="opacity-70 mt-2 mb-1">Dispositions</h4>
              {Object.entries(inspect.dispositions).map(([k, v]) => (
                <div key={k} className="flex items-center gap-2">
                  <span className="w-28 truncate">{k}</span>
                  <div className="flex-1 h-1.5 bg-neutral-700 rounded">
                    <div className="h-1.5 rounded bg-neutral-300"
                         style={{ width: `${(v / 10000) * 100}%` }} />
                  </div>
                  <span className="w-10 text-right opacity-60">{Math.round(v)}</span>
                </div>))}
              <h4 className="opacity-70 mt-3 mb-1">Faculties</h4>
              {Object.entries(inspect.faculties ?? {}).map(([k, v]) => (
                <div key={k} className="flex justify-between">
                  <span>{k}</span><span className="opacity-60">{v.toFixed(3)}</span>
                </div>))}
            </>}
            {inspect.decisions?.length > 0 && <>
              <h4 className="opacity-70 mt-3 mb-1">Recent decisions</h4>
              {inspect.decisions.map((d, i) => (
                <div key={i} className="mb-1.5 pb-1.5 border-b border-neutral-800">
                  <div className="font-medium">{d.choice}</div>
                  <div className="opacity-50 text-xs">
                    of {(d.options ?? []).join(", ")} · {d.model}
                  </div>
                </div>))}
            </>}
          </aside>)}
      </div>
    </div>
  );
}

createRoot(document.getElementById("root")).render(<App />);
