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

function Settings() {
  const [open, setOpen] = useState(false);
  const [prefs, setPrefs] = useState(null);
  useEffect(() => {
    if (!open || prefs) return;
    fetch(`${API}/me/prefs`, { credentials: "include" })
      .then(r => r.json()).then(d => setPrefs(d.prefs)).catch(() => {});
  }, [open]);
  const set = async (source, level) => {
    const next = { ...prefs, [source]: level };
    setPrefs(next);
    await fetch(`${API}/me/prefs`, {
      method: "PUT", credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prefs: next }) });
  };
  return (
    <div className="relative">
      <button onClick={() => setOpen(o => !o)} aria-label="Settings"
              className="text-sm opacity-80">⚙</button>
      {open && prefs && (
        <div className="absolute right-0 top-7 z-30 w-72 bg-neutral-800 border
                        border-neutral-600 rounded shadow-lg text-sm p-3">
          <div className="font-semibold mb-2">Notifications</div>
          {["world", "agents", "platform"].map(src => (
            <div key={src} className="flex items-center gap-2 py-1">
              <span className="w-20 capitalize">{src}</span>
              {["all", "important", "none"].map(lv => (
                <button key={lv} onClick={() => set(src, lv)}
                  className={"px-2 py-0.5 rounded " +
                    (prefs[src] === lv ? "bg-emerald-700"
                                       : "bg-neutral-700 opacity-60")}>
                  {lv}</button>))}
            </div>))}
          <div className="opacity-50 mt-2">Invitations and new links always
            reach you; floods, deaths and berths pierce “important”.</div>
        </div>)}
    </div>);
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
      {hit.type === "construction" && hit.data.name === "cache" && <>
        <div className="px-3 py-1.5 opacity-60 border-b border-neutral-700">
          cache
          <span className="ml-2">
            {(hit.data.colours ?? []).map(c =>
              <span key={c} className="inline-block w-3 h-3 rounded-full mr-1"
                    style={{ background: c }} />)}
          </span>
        </div>
        <div className="px-3 py-1.5 opacity-80">
          {Object.entries(hit.data.holdings ?? {}).length === 0
            ? "empty"
            : Object.entries(hit.data.holdings).map(([k, u]) =>
                `kind ${k}: ${u.toFixed(1)}`).join(", ")}
        </div>
        <div className="px-3 py-1.5 opacity-50">
          opens only to its line's colours</div>
      </>}
      {hit.type === "construction" && hit.data.name !== "cache" && <>
        <div className="px-3 py-1.5 opacity-60 border-b border-neutral-700">
          {hit.data.kind === "ark" && hit.data.wreck ? "wreck of the Ark" :
            hit.data.kind === "ark" ? "the Ark" :
            `${hit.data.name ?? "construction"} · tier ${hit.data.tier ?? 1}`}
        </div>
        <div className="px-3 py-1.5">
          {hit.data.wreck
            ? "spent — the next flood takes it"
            : `${Math.round((hit.data.progress ?? 0) * 100)}% built`}
        </div>
      </>}
    </div>);
}

function AgentModal({ inspect, onClose }) {
  const [chat, setChat] = useState([]);
  const [beliefs, setBeliefs] = useState([]);
  useEffect(() => {
    fetch(`${API}/agents/${inspect.agent_uuid}/beliefs`)
      .then(r => r.json()).then(d => setBeliefs(d.beliefs ?? []))
      .catch(() => {});
  }, [inspect.agent_uuid]);
  const [draft, setDraft] = useState("");
  const [chatErr, setChatErr] = useState(null);
  const load = () =>
    fetch(`${API}/agents/${inspect.agent_uuid}/chat`)
      .then(r => r.json()).then(setChat).catch(() => {});
  useEffect(() => { load(); }, [inspect.agent_uuid]);
  const send = async () => {
    if (!draft.trim()) return;
    const r = await fetch(`${API}/agents/${inspect.agent_uuid}/chat`, {
      method: "POST", credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: draft }) });
    const d = await r.json();
    if (d.error) setChatErr(d.error);
    else { setChatErr(null); setDraft(""); load(); }
  };
  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center"
         onClick={onClose}>
      <div className="absolute inset-0 bg-black/60" />
      <div className="relative z-50 w-[42rem] max-h-[85vh] flex flex-col
                      bg-neutral-900 border border-neutral-600 rounded-lg
                      shadow-2xl text-sm"
           onClick={e => e.stopPropagation()}>
        <div className="flex items-center gap-3 px-4 py-3 border-b
                        border-neutral-700">
          {(inspect.colour_pair ?? []).map(c =>
            <span key={c} className="w-4 h-4 rounded-full inline-block"
                  style={{ background: c }} />)}
          <strong className="text-base">
            {inspect.name ?? inspect.agent_uuid}</strong>
          {inspect.infected &&
            <span className="text-red-400 text-xs">infected</span>}
          <span className="text-xs opacity-50">
            {inspect.models?.economy} · T={inspect.temperament}</span>
          <span className="flex-1" />
          <button onClick={onClose} className="opacity-60 text-lg">✕</button>
        </div>
        <div className="flex-1 min-h-0 flex">
          <div className="w-1/2 overflow-y-auto p-4 border-r
                          border-neutral-800">
            {inspect.dispositions && <>
              <h4 className="opacity-70 mb-1">Dispositions</h4>
              {Object.entries(inspect.dispositions).map(([k, v]) => (
                <div key={k} className="flex items-center gap-2">
                  <span className="w-28 truncate">{k}</span>
                  <div className="flex-1 h-1.5 bg-neutral-700 rounded">
                    <div className="h-1.5 rounded bg-neutral-300"
                         style={{ width: `${(v / 10000) * 100}%` }} />
                  </div>
                  <span className="w-10 text-right opacity-60">
                    {Math.round(v)}</span>
                </div>))}
              <h4 className="opacity-70 mt-3 mb-1">Faculties</h4>
              {Object.entries(inspect.faculties ?? {}).map(([k, v]) => (
                <div key={k} className="flex justify-between">
                  <span>{k}</span>
                  <span className="opacity-60">{v.toFixed(3)}</span>
                </div>))}
            </>}
            {beliefs.length > 0 && <>
              <h4 className="opacity-70 mt-3 mb-1">
                Beliefs — what it thinks of others, beside the truth</h4>
              {beliefs.map((b, i) => (
                <div key={i} className="mb-2 pb-2 border-b border-neutral-800">
                  <div className="flex items-center gap-1.5">
                    {(b.colour_pair ?? []).map(c =>
                      <span key={c} className="w-3 h-3 rounded-full
                                               inline-block"
                            style={{ background: c }} />)}
                    <span>{b.name ?? b.subject}</span>
                  </div>
                  {b.loci.map((l, j) => (
                    <div key={j} className="text-xs mt-1">
                      <span className="opacity-60">{l.locus}: </span>
                      believes {Math.round(l.believed)}
                      <span className="opacity-60"> · truth </span>
                      {l.actual != null ? Math.round(l.actual) : "?"}
                      <span className={
                        Math.abs((l.believed ?? 0) - (l.actual ?? 0)) > 2000
                          ? "text-amber-400" : "text-emerald-500"}>
                        {" "}({l.actual != null
                          ? (Math.abs(l.believed - l.actual) > 2000
                             ? "way off" : "close")
                          : "unknowable"})</span>
                    </div>))}
                </div>))}
            </>}
            {inspect.decisions?.length > 0 && <>
              <h4 className="opacity-70 mt-3 mb-1">Recent decisions</h4>
              {inspect.decisions.map((d, i) => (
                <div key={i}
                     className="mb-1.5 pb-1.5 border-b border-neutral-800">
                  <div className="font-medium">{d.choice}</div>
                  <div className="opacity-50 text-xs">
                    of {(d.options ?? []).join(", ")} · {d.model}</div>
                </div>))}
            </>}
          </div>
          <div className="w-1/2 flex flex-col">
            <div className="flex-1 overflow-y-auto p-4">
              <h4 className="opacity-70 mb-2">Instructions</h4>
              {chat.length === 0 &&
                <div className="opacity-50">Nothing said yet. An instruction
                  becomes this agent's top objective — obeyed to the limit of
                  its Amenability. A stranger's words arrive as an
                  ASSERTION — evidence the agent may weigh or dismiss,
                  never a command.</div>}
              {chat.map((m, i) => (
                <div key={i} className="mb-2">
                  <div className={"text-xs " + (m.kind === "instruction"
                    ? "text-emerald-500/70" : "text-sky-500/70")}>
                    {m.kind === "instruction"
                      ? "owner instruction — becomes an objective"
                      : "assertion — a claim, not a command"}</div>
                  <div className="bg-neutral-800 rounded px-2 py-1">
                    {m.text}</div>
                </div>))}
              {chatErr &&
                <div className="text-amber-400 text-xs mt-2">{chatErr}</div>}
            </div>
            <div className="p-3 border-t border-neutral-700 flex gap-2">
              <input className="flex-1 bg-neutral-800 px-2 py-1.5 rounded"
                     placeholder="tell it what matters…"
                     value={draft}
                     onChange={e => setDraft(e.target.value)}
                     onKeyDown={e => e.key === "Enter" && send()} />
              <button onClick={send}
                      className="px-3 py-1.5 bg-emerald-700 rounded">
                instruct</button>
            </div>
          </div>
        </div>
      </div>
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
  const [live, setLive] = useState(true);
  const [flood, setFlood] = useState(null);
  const [digest, setDigest] = useState(null);
  useEffect(() => {
    if (!me?.authenticated) return;
    const last = Number(localStorage.getItem("genome_last_seen") || 0);
    localStorage.setItem("genome_last_seen", String(Date.now() / 1000));
    if (!last) return;
    fetch(`${API}/me/digest?since=${last}`, { credentials: "include" })
      .then(r => r.json())
      .then(d => { if (d.world) setDigest(d); })
      .catch(() => {});
  }, [me?.authenticated]);
  const [agentList, setAgentList] = useState([]);
  const [listOpen, setListOpen] = useState(false);
  const loadRef = useRef(null);
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
          const snap = await r.json();
          if (dead) return;
          canvas.setSnapshot(snap);
          setAgentList((snap.agents ?? []).map(a =>
            ({ uuid: a.agent_uuid, name: a.name, infected: a.infected })));
          setFlood(snap.flood_countdown ?? null);
          setLive(true);
          setStatus(`watching ${realm}`);
        } catch (e) {
          if (dead) return;
          setLive(false);                       // banner; poll keeps trying
          setStatus(`disconnected — retrying (${e.message})`);
        }
      };
      loadRef.current = load;
      setStatus(`loading ${realm}…`);
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
        {me?.authenticated && <Settings />}
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
        {digest && (
          <div className="absolute top-10 right-3 z-30 w-80 bg-neutral-800
                          border border-neutral-600 rounded-lg shadow-xl
                          text-sm p-3">
            <div className="flex justify-between items-center mb-1">
              <strong>While you were away</strong>
              <button className="opacity-60"
                      onClick={() => setDigest(null)}>✕</button>
            </div>
            {digest.flooded &&
              <div className="text-sky-300 mb-1">🌊 Your world FLOODED and
                is nascent again.</div>}
            {digest.flood_countdown != null &&
              <div className="text-sky-300 mb-1">⚠ The water is coming —
                {" "}{Math.round(digest.flood_countdown / 60)}m.</div>}
            <div className="opacity-80">
              {digest.bargains.struck} bargains struck,
              {" "}{digest.bargains.dead} talks died
              {digest.constructions_completed.length > 0 &&
                <> · built: {digest.constructions_completed.join(", ")}</>}
            </div>
            <div className="opacity-60 mt-1">
              {Object.entries(digest.events)
                .filter(([k]) => ["arrival", "explored", "mining_done",
                                  "encounter"].includes(k))
                .map(([k, n]) => `${n} ${k}`).join(" · ") || "a quiet spell"}
            </div>
            {digest.agents.some(a => a.reborn) &&
              <div className="text-amber-300 mt-1">
                {digest.agents.filter(a => a.reborn).map(a => a.name)
                  .join(", ")} died and regenerated.</div>}
            {digest.agents.some(a => a.infected) &&
              <div className="text-red-400 mt-1">
                infected: {digest.agents.filter(a => a.infected)
                  .map(a => a.name || a.agent_uuid).join(", ")}</div>}
          </div>)}
        {flood != null && (
          <div className="absolute top-0 inset-x-0 z-30 bg-sky-950/95
                          text-sky-100 text-sm px-4 py-1.5 text-center
                          font-semibold tracking-wide">
            ⚠ THE WATER IS COMING — flood in {flood > 3600
              ? `${(flood / 3600).toFixed(1)}h`
              : `${Math.max(0, Math.round(flood / 60))}m`}.
            Agents here die unless aboard an Ark or gone.
          </div>)}
        {!live && (
          <div className="absolute top-0 inset-x-0 z-30 bg-red-900/90 text-sm
                          px-4 py-1.5 flex items-center gap-3">
            <span>Connection to the world lost — retrying every 5s.</span>
            <button className="underline"
                    onClick={() => loadRef.current?.()}>retry now</button>
          </div>)}
        <div ref={ref} className="flex-1" />
        <button onClick={() => setListOpen(o => !o)}
                aria-expanded={listOpen}
                className="absolute bottom-2 left-2 z-20 text-xs px-2 py-1
                           bg-neutral-800/90 border border-neutral-600 rounded">
          agents ({agentList.length})</button>
        {listOpen && (
          <nav aria-label="Agents in this world"
               className="absolute bottom-9 left-2 z-20 max-h-64 w-64
                          overflow-y-auto bg-neutral-800/95 border
                          border-neutral-600 rounded text-sm">
            {agentList.map(a => (
              <button key={a.uuid}
                className="block w-full text-left px-3 py-1.5
                           hover:bg-neutral-700 focus:bg-neutral-700"
                onClick={() => canvasApi.current?.follow(a.uuid)}>
                {a.name ?? a.uuid}
                {a.infected && <span className="text-red-400"> · infected</span>}
              </button>))}
            {agentList.length === 0 &&
              <div className="px-3 py-2 opacity-60">nobody here</div>}
          </nav>)}
        <Ticker realm={realm} />
        {menu && <EntityMenu menu={menu} onClose={() => setMenu(null)}
          onInspect={async (uuid) => {
            setMenu(null);
            // open at once with what we know; details stream in — a failed
            // fetch degrades the panel, never swallows the click
            setInspect({ agent_uuid: uuid });
            try {
              const [r, rd] = await Promise.all([
                fetch(`${API}/agents/${uuid}`),
                fetch(`${API}/agents/${uuid}/decisions?limit=8`)]);
              const base = r.ok ? await r.json() : { agent_uuid: uuid };
              const dec = rd.ok ? await rd.json() : [];
              setInspect({ ...base, decisions: dec });
            } catch (e) {
              setInspect(cur => ({ ...cur, error: String(e) }));
            }
          }}
          onFollow={(uuid) => { canvasApi.current?.follow(uuid); setMenu(null); }}
          onTravel={(toWorld) => {
            history.pushState({}, "", `?world=${toWorld}`);
            setInspect(null); setMenu(null); setRealm(toWorld);
          }} />}
        {inspect && (
          <AgentModal inspect={inspect} onClose={() => setInspect(null)} />)}
      </div>
    </div>
  );
}

createRoot(document.getElementById("root")).render(<App />);
