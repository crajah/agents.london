// Chrome is React; the canvas is not (interface-spec Rules 6.1/6.2).
import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { createWorldCanvas } from "./world/canvas.js";

const API = import.meta.env.VITE_GENOME_API ?? "";

// The A100 palette (genome-spec Rule 4.9): kind k ALWAYS wears A100[k],
// in every world. The per-world colourOf mapping this replaces knew only
// the world's own two kinds and painted the other eighteen grey.
const A100 = ["#FF8A80", "#FF80AB", "#EA80FC", "#B388FF", "#8C9EFF",
              "#82B1FF", "#80D8FF", "#84FFFF", "#A7FFEB", "#B9F6CA",
              "#CCFF90", "#F4FF81", "#FFFF8D", "#FFE57F", "#FFD180",
              "#FF9E80", "#D7CCC8", "#CFD8DC", "#F5F5F5", "#B2FFFF"];
const kindColour = (k) => A100[Number(k)] ?? "#777";

// every agent name wears its lineage: the world colour pair, then the
// generation, then the name (user directive 2026-09-04)
function AgentTag({ a }) {
  return (
    <span className="inline-flex items-center gap-1">
      {(a.colour_pair ?? []).map((c, i) => (
        <span key={i} className="w-2.5 h-2.5 rounded-full inline-block"
              style={{ background: c }} />))}
      {a.generation &&
        <span className="text-[10px] opacity-60 font-mono">
          G{a.generation}</span>}
      <span>{a.name ?? a.agent_uuid}</span>
    </span>);
}

function Chats({ onOpen }) {
  // the message inbox (user directive 2026-09-05): when an agent's answer
  // is ready it appears here, against the chat icon in the top bar
  const [items, setItems] = useState([]);
  const [open, setOpen] = useState(false);
  const [seen, setSeen] = useState(
    Number(localStorage.getItem("genome_chats_seen") || 0));
  useEffect(() => {
    const load = () => fetch(`${API}/me/replies`, { credentials: "include" })
      .then(r => r.ok ? r.json() : []).then(d => Array.isArray(d) && setItems(d))
      .catch(() => {});
    load(); const t = setInterval(load, 25000);
    return () => clearInterval(t);
  }, []);
  const unread = items.filter(i => i.at > seen).length;
  const markSeen = () => {
    const now = Date.now() / 1000;
    localStorage.setItem("genome_chats_seen", String(now));
    setSeen(now);
  };
  return (
    <span className="relative">
      <button onClick={() => { setOpen(!open); if (!open) markSeen(); }}
              className="text-lg" title="Messages from your agents">
        💬{unread > 0 &&
          <span className="text-xs text-violet-400">{unread}</span>}
      </button>
      {open && (
        <div className="absolute right-0 top-8 w-96 max-h-80 overflow-y-auto
                        bg-neutral-800 border border-neutral-600 rounded p-2
                        text-sm z-10">
          {items.length === 0 &&
            <div className="opacity-50">No messages yet. Instruct one of
              your agents and its answer arrives here.</div>}
          {items.map((m, i) => (
            <button key={i}
                    className="block w-full text-left py-1.5 border-b
                               border-neutral-700 hover:bg-neutral-700/50"
                    onClick={() => { setOpen(false); onOpen(m.agent_uuid); }}>
              <div className="text-xs text-violet-400/80 flex gap-1
                              items-center">
                {(m.colour_pair || []).map((c, j) =>
                  <span key={j} className="inline-block w-2 h-2 rounded-full"
                        style={{ background: c }} />)}
                {m.name || m.agent_uuid}
                <span className="opacity-50 ml-auto">
                  {new Date(m.at * 1000).toLocaleTimeString()}</span>
              </div>
              <div className="opacity-80 line-clamp-2">{m.text}</div>
            </button>))}
        </div>)}
    </span>);
}


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

function AdminPanel({ onClose }) {
  const [token, setToken] = useState(
    localStorage.getItem("genome_admin_token") || "");
  const [worlds, setWorlds] = useState(null);
  const [cfg, setCfg] = useState(null);
  const [costs, setCosts] = useState(null);
  const [err, setErr] = useState(null);
  const hdrs = { "x-admin-token": token, "Content-Type": "application/json" };
  const load = async () => {
    setErr(null);
    try {
      const [rw, rc] = await Promise.all([
        fetch(`${API}/admin/worlds`, { headers: hdrs }),
        fetch(`${API}/admin/config`, { headers: hdrs })]);
      if (!rw.ok) throw new Error("token rejected");
      localStorage.setItem("genome_admin_token", token);
      setWorlds(await rw.json());
      setCfg(await rc.json());
    } catch (e) { setErr(String(e.message || e)); setWorlds(null); }
  };
  const saveCfg = async (patch) => {
    const next = { ...cfg, ...patch };
    setCfg(next);
    await fetch(`${API}/admin/config`, {
      method: "PUT", headers: hdrs, body: JSON.stringify(next) });
  };
  const [roster, setRoster] = useState(null);
  const agentAct = async (uuid, verb) => {
    await fetch(`${API}/admin/agents/${uuid}/${verb}`,
                { method: "POST", headers: hdrs });
    load();
  };
  const act = async (realm, verb) => {
    await fetch(`${API}/admin/worlds/${realm}/${verb}`,
                { method: "POST", headers: hdrs });
    load();
  };
  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center"
         onClick={onClose}>
      <div className="absolute inset-0 bg-black/60" />
      <div className="relative z-50 w-[46rem] max-h-[85vh] overflow-y-auto
                      bg-neutral-900 border border-neutral-600 rounded-lg
                      shadow-2xl text-sm p-4"
           onClick={e => e.stopPropagation()}>
        <div className="flex items-center gap-3 mb-3">
          <strong className="text-base">Simulation admin</strong>
          <span className="flex-1" />
          <button onClick={onClose} className="opacity-60 text-lg">✕</button>
        </div>
        <div className="flex gap-2 mb-4">
          <input type="password" value={token}
                 onChange={e => setToken(e.target.value)}
                 placeholder="admin token"
                 className="flex-1 bg-neutral-800 px-2 py-1.5 rounded" />
          <button onClick={load}
                  className="px-3 py-1.5 bg-emerald-700 rounded">connect</button>
        </div>
        {err && <div className="text-amber-400 mb-3">{err}</div>}
        {cfg && (
          <div className="mb-4 p-3 bg-neutral-800/60 rounded">
            <div className="font-semibold mb-2">Free agents
              <span className="opacity-50 font-normal"> — ownerless
              citizens seeded into every world to thicken the society</span>
            </div>
            <div className="flex items-center gap-4 flex-wrap">
              <label className="flex items-center gap-2">
                <input type="checkbox" checked={!!cfg.free_agent_spawn}
                       onChange={e =>
                         saveCfg({ free_agent_spawn: e.target.checked })} />
                spawn enabled
              </label>
              <label className="flex items-center gap-2">
                every
                <input type="number" min="30"
                       value={cfg.spawn_interval_s}
                       onChange={e => saveCfg({ spawn_interval_s:
                         Number(e.target.value) })}
                       className="w-24 bg-neutral-800 border
                                  border-neutral-600 px-2 py-0.5 rounded" />
                seconds / world
              </label>
              <label className="flex items-center gap-2">
                cap
                <input type="number" min="1"
                       value={cfg.spawn_cap_per_world}
                       onChange={e => saveCfg({ spawn_cap_per_world:
                         Number(e.target.value) })}
                       className="w-16 bg-neutral-800 border
                                  border-neutral-600 px-2 py-0.5 rounded" />
                agents / world
              </label>
            </div>
          </div>)}
        {worlds && <>
          <div className="flex items-center gap-3 mb-1">
            <span className="opacity-60">
              {worlds.decisions_last_hour} decisions in the last hour</span>
            <span className="flex-1" />
            <button className="px-2 py-1 rounded bg-neutral-700 text-xs"
                    onClick={async () => {
                      const r = await fetch(`${API}/admin/costs`,
                                            { headers: hdrs });
                      setCosts(await r.json());
                    }}>💸 costs</button>
            <button className="px-2 py-1 rounded bg-rose-900
                               hover:bg-rose-800 text-xs"
                    title="Purge the pathosphere: clears every infection,
every antigen and every world's strain lineage. The epidemic restarts
from the next portal crossing."
                    onClick={async () => {
                      if (!confirm("Cure ALL infections and wipe every " +
                                   "strain? The epidemic starts over."))
                        return;
                      const r = await fetch(`${API}/admin/cure`, {
                        method: "POST", headers: hdrs });
                      const d = await r.json();
                      alert(d.ok
                        ? `Cured ${d.cured} agents; strains wiped in ` +
                          `${d.strains_wiped_in} worlds.`
                        : (d.error ?? "failed"));
                    }}>🧹 cure all plagues</button>
          </div>
          {costs && !costs.error && (
            <div className="mb-3 p-2 bg-neutral-800/60 rounded text-xs">
              <div className="font-semibold mb-1">LLM tokens spent —
                biggest first</div>
              <div className="grid grid-cols-3 gap-3">
                {[["by user", costs.tokens_by_user],
                  ["by world", costs.tokens_by_world],
                  ["by model", costs.tokens_by_model]].map(([t, rows]) => (
                  <div key={t}>
                    <div className="opacity-60 mb-0.5">{t}</div>
                    {(rows ?? []).slice(0, 6).map(([k, n]) => (
                      <div key={k} className="flex justify-between">
                        <span className="truncate mr-2">{k}</span>
                        <span className="opacity-70">
                          {n >= 1e6 ? `${(n / 1e6).toFixed(1)}M`
                            : n >= 1e3 ? `${(n / 1e3).toFixed(0)}k` : n}
                        </span>
                      </div>))}
                  </div>))}
              </div>
            </div>)}
          {costs?.error &&
            <div className="text-amber-400 text-xs mb-2">{costs.error}</div>}
          <table className="w-full text-xs">
            <thead><tr className="opacity-50 text-left">
              <th className="py-1">world</th><th>agents</th><th>due</th>
              <th>oldest due</th><th>flood</th><th>board</th>
              <th>store</th><th></th>
            </tr></thead>
            <tbody>
              {worlds.worlds.map(w => (
                <tr key={w.realm}
                    className={"border-t border-neutral-800 " +
                      (w.stalled ? "text-amber-400" : "")}>
                  <td className="py-1">
                    <a className="underline"
                       href={`?world=${w.realm}`}>{w.realm}</a>
                    {w.paused && " ⏸"}{w.stalled && " ⚠stalled"}</td>
                  <td>{w.agents}</td>
                  <td>{w.events_due}/{w.events_pending}</td>
                  <td>{w.oldest_due_age_s}s</td>
                  <td title={w.flood_at_in_s != null
                    ? `the water arrives in ${Math.round(w.flood_at_in_s / 60)} minutes (operator's clock -- agents cannot see this until the window opens)`
                    : "no flood scheduled"}>
                    {w.flood_at_in_s != null
                      ? `${Math.round(w.flood_at_in_s / 60)}m`
                      : "—"}{" "}
                    <span className="opacity-40">#{w.flood_count}</span></td>
                  <td>{w.open_listings}</td>
                  <td className="max-w-[9rem] truncate"
                      title={Object.entries(w.stock ?? {})
                        .map(([k, v]) => `kind ${k}: ${v}`).join("\n")}>
                    {Object.entries(w.stock ?? {})
                      .map(([k, v]) => `${k}:${v}`).join(" ") || "—"}
                  </td>
                  <td className="whitespace-nowrap">
                    <button className="underline opacity-70 mr-2"
                            title="Drop a free agent in now"
                            onClick={() => act(w.realm, "spawn")}>+agent</button>
                    <button className="underline opacity-70 mr-2"
                            title="Introduce a fresh strain: one random
resident becomes patient zero"
                            onClick={() => act(w.realm, "infect")}>+plague</button>
                    <button className="underline opacity-70 mr-2"
                            onClick={() => act(w.realm,
                              w.paused ? "resume" : "pause")}>
                      {w.paused ? "resume" : "pause"}</button>
                    <button className="underline text-sky-400/80 mr-2"
                            title="Bring the water NOW"
                            onClick={() => window.confirm(
                              `Flood ${w.realm} now?`) &&
                              act(w.realm, "flood")}>flood</button>
                    <button className="underline text-amber-400/80 mr-2"
                            title="Evacuation order: every agent leaves
immediately through the portals"
                            onClick={() => window.confirm(
                              `Scurry ${w.realm}? Every agent leaves now.`) &&
                              act(w.realm, "scurry")}>scurry</button>
                    <button className="underline opacity-70"
                            title="Inspect and act on this world's agents"
                            onClick={() => setRoster(
                              roster === w.realm ? null : w.realm)}>
                      agents…</button>
                  </td>
                </tr>))}
            </tbody>
          </table>
          {roster && (() => {
            const w = worlds.worlds.find(x => x.realm === roster);
            if (!w) return null;
            return (
              <div className="mt-3 p-3 bg-neutral-800/60 rounded">
                <div className="font-semibold mb-2">{w.realm}
                  <span className="opacity-50 font-normal"> — pace </span>
                  <input type="number" min="0.1" max="600" step="1"
                         defaultValue={w.time_scale}
                         className="w-20 bg-neutral-800 border
                                    border-neutral-600 px-1 py-0.5 rounded"
                         onBlur={async e => {
                           await fetch(
                             `${API}/admin/worlds/${w.realm}/time-scale`,
                             { method: "PUT", headers: hdrs,
                               body: JSON.stringify({ time_scale:
                                 Number(e.target.value) }) });
                           load();
                         }} />
                  <span className="opacity-50 font-normal">× real time</span>
                </div>
                <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
                  {(w.roster || []).map(a => (
                    <div key={a.uuid}
                         className="flex items-center gap-2 border-b
                                    border-neutral-700/50 py-0.5">
                      <span className="truncate flex-1">{a.uuid}</span>
                      <button className="underline opacity-70"
                              title="Schedule a decide now"
                              onClick={() => agentAct(a.uuid, "nudge")}>
                        nudge</button>
                      <button className="underline text-emerald-400/80"
                              title="Restore vitals in full"
                              onClick={() => agentAct(a.uuid, "heal")}>
                        heal</button>
                      <button className="underline text-red-400/80"
                              title="Death by decree — perishes and
regenerates by the game's own rules"
                              onClick={() => window.confirm(
                                `Kill ${a.uuid}?`) &&
                                agentAct(a.uuid, "kill")}>kill</button>
                    </div>))}
                  {(w.roster || []).length === 0 &&
                    <div className="opacity-50">nobody present</div>}
                </div>
              </div>);
          })()}
        </>}
      </div>
    </div>);
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

function Timeline({ realm }) {
  // Phase 11: the world's past, scrollable backwards -- built from the
  // events record, never a separate log
  const [open, setOpen] = useState(false);
  const [rows, setRows] = useState([]);
  const [done, setDone] = useState(false);
  const load = async (before) => {
    const r = await fetch(`${API}/worlds/${realm}/timeline?limit=40` +
                          (before ? `&before=${encodeURIComponent(before)}`
                                  : ""));
    const more = await r.json();
    if (more.length < 40) setDone(true);
    setRows(cur => before ? [...cur, ...more] : more);
  };
  const fmt = (iso) => {
    const t = Number(iso);
    return isFinite(t) ? new Date(t * 1000).toLocaleTimeString() : iso;
  };
  return (
    <div className="absolute bottom-10 left-2 z-20 text-xs">
      <button onClick={() => { setOpen(o => !o);
                               if (!open) { setDone(false); load(); } }}
              className="px-2 py-1 bg-neutral-800/90 border
                         border-neutral-600 rounded">⏱ timeline</button>
      {open && (
        <div className="mt-1 w-80 max-h-72 overflow-y-auto bg-neutral-900/95
                        border border-neutral-700 rounded p-2 font-mono">
          {rows.map((e, i) => (
            <div key={i} className={"py-0.5 border-t border-neutral-800 " +
                                    (e.voided ? "opacity-40" : "")}>
              <span className="opacity-50">{fmt(e.at)}</span>{" "}
              {(e.subject ?? "").slice(0, 16)}{" "}
              <span className="opacity-70">{e.kind}</span>
              {e.voided && " (voided)"}
            </div>))}
          {rows.length === 0 &&
            <div className="opacity-50">nothing recorded yet</div>}
          {!done && rows.length > 0 &&
            <button className="mt-1 underline opacity-70"
                    onClick={() => load(rows[rows.length - 1]?.at)}>
              older…</button>}
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

function EntityMenu({ menu, onClose, onInspect, onFollow, onTravel,
                      info }) {
  const colourOf = kindColour;
  const KChip = ({ k, u }) => (
    <span className="inline-flex items-center gap-1 bg-neutral-700/70
                     rounded px-1 mr-1" title={`kind ${k}`}>
      {Number(u).toFixed(0)}×
      <span className="w-2.5 h-2.5 rounded-full inline-block"
            style={{ background: colourOf(k) }} />
    </span>);
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
          <AgentTag a={hit.data} />
          {hit.data.infected && <span className="text-red-400"> · infected</span>}
        </div>
        <Item onClick={() => onInspect(hit.data.agent_uuid)}>Inspect</Item>
        <Item onClick={() => onFollow(hit.data.agent_uuid)}>Follow</Item>
      </>}
      {hit.type === "pile" && (() => {
        const p = hit.data;
        const dt = Math.max(0, now - p.measured_at);
        const qty = Math.min(p.cap, p.qty_at + p.rate * dt);
        return <>
          <div className="px-3 py-1.5 opacity-60 border-b border-neutral-700
                          flex items-center gap-2">
            resource pile
            <span className="w-3 h-3 rounded-full inline-block"
                  title={`kind ${p.kind}`}
                  style={{ background: colourOf(p.kind) }} /></div>
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
      {hit.type === "market" && <>
        <div className="px-3 py-1.5 opacity-60 border-b border-neutral-700">
          marketplace — {hit.data.listings.length} open listing
          {hit.data.listings.length === 1 ? "" : "s"}</div>
        {hit.data.listings.slice(0, 6).map(l => (
          <div key={l.key} className="px-3 py-1 text-xs">
            <span className="opacity-80">{l.by ?? "someone"}</span>
            <span className="opacity-60"> gives </span>
            {Object.entries(l.give).map(([k, u]) =>
              <KChip key={k} k={k} u={u} />)}
            <span className="opacity-60"> for </span>
            {Object.entries(l.want).map(([k, u]) =>
              <KChip key={k} k={k} u={u} />)}
          </div>))}
        {hit.data.listings.length === 0 &&
          <div className="px-3 py-1.5 opacity-60">the board is bare</div>}
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
                <KChip key={k} k={k} u={u} />)}
        </div>
        <div className="px-3 py-1.5 opacity-50">
          opens only to its line's colours</div>
      </>}
      {hit.type === "construction" && hit.data.name === "plan_post" && <>
        <div className="px-3 py-1.5 opacity-60 border-b border-neutral-700">
          drawing post</div>
        <div className="px-3 py-1.5">“{hit.data.plan_name ?? "a design"}”
          <div className="opacity-60">agents that stand here learn the
            plan and may raise it in any world</div>
        </div>
      </>}
      {hit.type === "construction" && hit.data.name !== "cache" &&
       hit.data.name !== "plan_post" && <>
        <div className="px-3 py-1.5 opacity-60 border-b border-neutral-700">
          {hit.data.kind === "ark" && hit.data.wreck ? "wreck of the Ark" :
            hit.data.kind === "ark" ? "the Ark" :
            `${hit.data.name ?? "construction"} · tier ${hit.data.tier ?? 1}`}
        </div>
        <div className="px-3 py-1.5">
          {hit.data.wreck
            ? "spent — the next flood takes it"
            : hit.data.carried
            ? "aloft — a party carries it as one body"
            : hit.data.building_until && !hit.data.complete
            ? `rising — ready in ~${Math.max(1, Math.round(
                (hit.data.building_until - now) / 60))}m`
            : `${Math.round((hit.data.progress ?? 0) * 100)}% ` +
              (hit.data.complete ? "— standing" : "filled")}
        </div>
      </>}
    </div>);
}

function Legend() {
  const [open, setOpen] = useState(true);
  const Dot = ({ c, ring }) => (
    <span className={"inline-block w-3 h-3 rounded-full mr-0.5" +
                     (ring ? " ring-2 ring-amber-300" : "")}
          style={{ background: c }} />);
  const Row = ({ icon, children }) => (
    <div className="flex items-center gap-2 py-0.5">
      <span className="w-8 text-center">{icon}</span>
      <span className="opacity-80">{children}</span>
    </div>);
  if (!open) return (
    <button onClick={() => setOpen(true)}
            className="absolute bottom-2 right-3 z-20 text-xs px-2 py-1
                       bg-neutral-800/90 border border-neutral-600 rounded">
      legend</button>);
  return (
    <div className="absolute bottom-2 right-3 z-20 bg-neutral-900/90 border
                    border-neutral-700 rounded p-2 text-xs w-60">
      <div className="flex justify-between items-center mb-1">
        <span className="opacity-60 font-semibold">legend</span>
        <button className="opacity-50" onClick={() => setOpen(false)}>✕</button>
      </div>
      <Row icon={<><Dot c="#e57373" /><Dot c="#64b5f6" /></>}>
        agent — disc + heading, tinted with its lineage colours</Row>
      <Row icon={<Dot c="#a5d6a7" ring />}>ringed agent — one of yours</Row>
      <Row icon={<span className="inline-block w-4 h-3 rounded-full
                                  bg-neutral-400/70 blur-[1px]" />}>
        pile — brighter is fuller, larger holds more</Row>
      <Row icon={<span className="inline-block w-3.5 h-3.5 rounded-full
                                  border-2 border-sky-400
                                  border-b-fuchsia-400" />}>
        portal — ring in the destination's colours</Row>
      <Row icon="⚑">muster flag — loads are deposited here</Row>
      <Row icon="⌗">market — the world's trading board</Row>
      <Row icon={<span className="inline-block w-3.5 h-3.5 bg-neutral-500/60
                                  border border-neutral-300/60" />}>
        construction — opacity tracks build progress</Row>
      <Row icon={<span className="inline-block w-3 h-3 rotate-45
                                  bg-emerald-700/70" />}>
        cache — a larder only its line's colours open</Row>
    </div>);
}

function PlanTable({ realm, info }) {
  const colourOf = kindColour;
  // Rule 13.6b: plans are authored conversationally, not through a form --
  // this is a conversation with the drafting table, retried in prose
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const send = async () => {
    if (!text.trim() || busy) return;
    setBusy(true);
    try {
      const r = await fetch(`${API}/worlds/${realm}/channel`, {
        method: "POST", credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }) });
      setResult(await r.json());
    } catch (e) { setResult({ error: String(e) }); }
    setBusy(false);
  };
  return (
    <div className="absolute bottom-10 right-3 z-20 text-xs">
      <button onClick={() => setOpen(o => !o)}
              className="px-2 py-1 bg-neutral-900/85 border
                         border-neutral-700 rounded"
              title="Describe a design; agents that find the drawing may
raise it in any world. Plans are structures only -- no effects.">
        📐 draw a plan</button>
      {open && (
        <div className="mt-1 w-80 bg-neutral-900/95 border
                        border-neutral-700 rounded p-2">
          <textarea className="w-full h-20 bg-neutral-800 rounded p-2"
                    placeholder="e.g. A windmill: sails of 6 units of kind 4,
on a tower of 10 of kind 16, two users for the tower…"
                    value={text} onChange={e => setText(e.target.value)} />
          <div className="flex justify-between items-center mt-1">
            <span className="opacity-50">structures only — effects are
              silently dropped</span>
            <button onClick={send} disabled={busy}
                    className="px-2 py-1 bg-emerald-700 rounded">
              {busy ? "drafting…" : "draft"}</button>
          </div>
          {result?.error && (
            <div className="text-amber-400 mt-1">{result.error} — rephrase
              and draft again.</div>)}
          {result?.ok && (
            <div className="mt-1">
              <div className="text-emerald-400">“{result.name}” posted.</div>
              {result.tree.map(n => (
                <div key={n.item} className="opacity-80">
                  {n.item}: {Object.entries(n.needs).map(([k, u]) => (
                    <span key={k} title={`kind ${k}`}
                          className="inline-flex items-center gap-0.5 mr-1">
                      {u}×<span className="w-2.5 h-2.5 rounded-full
                                           inline-block"
                        style={{ background: colourOf(k) }} /></span>))}
                  {n.after?.length ? ` (after ${n.after.join(", ")})` : ""}
                  {n.contributors > 1 ? ` · ${n.contributors} users` : ""}
                </div>))}
            </div>)}
        </div>)}
    </div>);
}

function MarketPanel({ info }) {
  const [open, setOpen] = useState(false);
  const listings = info?.listings ?? [];
  const colourOf = kindColour;
  const Chip = ({ k, u }) => (
    <span className="inline-flex items-center gap-1 bg-neutral-800 rounded
                     px-1 py-0.5 mr-1" title={`kind ${k}`}>
      {Number(u).toFixed(0)}×
      <span className="w-2.5 h-2.5 rounded-full inline-block"
            style={{ background: colourOf(k) }} />
    </span>);
  return (
    <div className="absolute top-2 right-60 z-20 text-xs">
      <button onClick={() => setOpen(o => !o)}
              title="Open market listings in this world"
              className="px-2 py-1 bg-neutral-900/85 border
                         border-neutral-700 rounded">
        ⌗ market{listings.length > 0 && ` (${listings.length})`}
      </button>
      {open && (
        <div className="mt-1 w-72 max-h-64 overflow-y-auto bg-neutral-900/95
                        border border-neutral-700 rounded p-2">
          <div className="opacity-60 mb-1">open listings — hand-to-hand at
            the board</div>
          {listings.length === 0 &&
            <div className="opacity-50">the board is bare</div>}
          {listings.map(l => (
            <div key={l.key} className="py-1 border-t border-neutral-800">
              <div className="opacity-70 truncate">{l.by ?? "someone"}</div>
              <span className="opacity-60">gives </span>
              {Object.entries(l.give ?? {}).map(([k, u]) =>
                <Chip key={k} k={k} u={u} />)}
              <span className="opacity-60"> for </span>
              {Object.entries(l.want ?? {}).map(([k, u]) =>
                <Chip key={k} k={k} u={u} />)}
            </div>))}
        </div>)}
    </div>);
}

function FloodWave({ active }) {
  // The water arrives ON SCREEN (user directive): a rising tide swallows the
  // world for a few seconds when a flood executes, then recedes.
  if (!active) return null;
  return (
    <div className="absolute inset-0 z-40 pointer-events-none overflow-hidden">
      <style>{`
        @keyframes genome-tide {
          0%   { transform: translateY(101%); }
          35%  { transform: translateY(6%); }
          70%  { transform: translateY(0%); }
          100% { transform: translateY(101%); }
        }
        @keyframes genome-swell {
          from { background-position-x: 0; }
          to   { background-position-x: 240px; }
        }`}</style>
      <div style={{
        position: "absolute", inset: 0,
        animation: "genome-tide 6s ease-in-out forwards",
        background: "linear-gradient(to bottom, rgba(56,130,190,.55)," +
                    " rgba(12,50,90,.92))" }}>
        <div style={{
          position: "absolute", top: -14, left: 0, right: 0, height: 16,
          animation: "genome-swell 1.2s linear infinite",
          background: "radial-gradient(circle at 12px 16px," +
                      " rgba(120,180,230,.9) 10px, transparent 11px)",
          backgroundSize: "48px 16px" }} />
      </div>
      <div className="absolute inset-x-0 top-1/3 text-center text-sky-100
                      text-2xl font-bold tracking-widest drop-shadow-lg"
           style={{ animation: "genome-tide 6s ease-in-out forwards",
                    animationName: "none" }}>
        🌊 THE WATER CAME
      </div>
    </div>);
}

function StockPanel({ info }) {
  if (!info) return null;
  const entries = Object.entries(info.stock ?? {})
    .sort((a, b) => Number(a[0]) - Number(b[0]));
  const colourOf = kindColour;
  const total = entries.reduce((t, [, v]) => t + Number(v), 0);
  return (
    <div className="absolute top-2 right-3 z-20 bg-neutral-900/85 border
                    border-neutral-700 rounded p-2 text-xs max-w-56">
      <div className="opacity-60 mb-1">
        world store · {total.toFixed(0)} units · {info.agentCount} agents</div>
      {entries.length === 0 &&
        <div className="opacity-50">the store is empty</div>}
      <div className="flex flex-wrap gap-1">
        {entries.map(([k, v]) => (
          <span key={k} title={`kind ${k}`}
                className="flex items-center gap-1 bg-neutral-800 rounded
                           px-1.5 py-0.5">
            <span className="w-2.5 h-2.5 rounded-full inline-block"
                  style={{ background: colourOf(k) }} />
            {Number(v).toFixed(0)}
          </span>))}
      </div>
    </div>);
}

function StrainStrip({ vec, dead }) {
  // the pathogen's face: its 6-dim signature as a colour strip; an
  // antigen's vector rendered the same way, so a match is VISIBLE
  if (!vec?.length) return null;
  return (
    <span className={"inline-flex h-3 rounded-sm overflow-hidden ml-1 " +
                     "align-middle" + (dead ? " opacity-30 grayscale" : "")}
          title={vec.map(v => v.toFixed(2)).join(" ")}>
      {vec.map((v, i) => (
        <span key={i} className="w-3 h-3 inline-block"
              style={{ background:
                `hsl(${Math.round(v * 300)}, 70%, 45%)` }} />))}
    </span>);
}

function AgentModal({ inspect, onClose }) {
  const [locusInfo, setLocusInfo] = useState(null);  // {name, value, text}
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
  useEffect(() => {
    load();
    // the agent replies on its own clock -- minutes after the instruction,
    // once the pursuit succeeds -- so the open panel keeps listening
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, [inspect.agent_uuid]);
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
          {inspect.generation &&
            <span className="text-xs opacity-60 font-mono">
              G{inspect.generation}</span>}
          <strong className="text-base">
            {inspect.name ?? inspect.agent_uuid}</strong>
          {inspect.infected &&
            <span className="text-red-400 text-xs">infected</span>}
          <span className="text-xs opacity-50">
            {inspect.models?.economy} · T={inspect.temperament}</span>
          {inspect.capability
            ? <span className="text-xs px-1.5 py-0.5 rounded bg-violet-900
                               text-violet-200"
                    title="Its one capability, rolled at birth. Never
traded, never inherited; it survives death.">
                ✦ {inspect.capability.name}</span>
            : inspect.capability === null &&
              <span className="text-xs opacity-40"
                    title="One in four agents is born plain -- the demand
side of the capability economy.">born plain</span>}
          <span className="flex-1" />
          <button onClick={onClose} className="opacity-60 text-lg">✕</button>
        </div>
        {locusInfo && (
          <div className="absolute inset-0 z-50 flex items-center
                          justify-center"
               onClick={e => { e.stopPropagation(); setLocusInfo(null); }}>
            <div className="absolute inset-0 bg-black/50 rounded-lg" />
            <div className="relative w-80 bg-neutral-800 border
                            border-neutral-500 rounded-lg shadow-2xl p-4"
                 onClick={e => e.stopPropagation()}>
              <div className="flex items-center justify-between mb-2">
                <strong>{locusInfo.name}</strong>
                <span className="flex items-center gap-3">
                  {locusInfo.value &&
                    <span className="text-emerald-400 font-mono">
                      {locusInfo.value}</span>}
                  <button className="opacity-60"
                          onClick={() => setLocusInfo(null)}>✕</button>
                </span>
              </div>
              {locusInfo.rows
                ? <div className="max-h-80 overflow-y-auto text-xs space-y-1">
                    {locusInfo.rows.map(([k, v], i) => (
                      <div key={i}>
                        <span className="opacity-50">{k}: </span>
                        {typeof v === "string"
                          ? <span className="whitespace-pre-wrap">{v}</span>
                          : v}
                      </div>))}
                  </div>
                : <div className="opacity-80">
                    {locusInfo.text ?? "No description recorded."}
                  </div>}
            </div>
          </div>)}
        <div className="flex-1 min-h-0 flex">
          <div className="w-1/2 overflow-y-auto p-4 border-r
                          border-neutral-800">
            {inspect.dispositions && <>
              <h4 className="opacity-70 mb-1">Dispositions</h4>
              {Object.entries(inspect.dispositions).map(([k, v]) => (
                <div key={k} className="flex items-center gap-2">
                  <button className="w-28 truncate text-left underline
                                     decoration-dotted decoration-neutral-600"
                          onClick={() => setLocusInfo({ name: k,
                            value: `${Math.round(v / 100)}%`,
                            text: inspect.locus_help?.[k] })}>{k}</button>
                  <div className="flex-1 h-1.5 bg-neutral-700 rounded">
                    <div className="h-1.5 rounded bg-neutral-300"
                         style={{ width: `${(v / 10000) * 100}%` }} />
                  </div>
                  <span className="w-10 text-right opacity-60">
                    {Math.round(v / 100)}%</span>
                </div>))}
              <h4 className="opacity-70 mt-3 mb-1">
                <button className="underline decoration-dotted
                                   decoration-neutral-600"
                        onClick={() => setLocusInfo({
                          name: "Expression — the phenotype",
                          text: "What each budgeted locus EXPRESSES after " +
                                "the genome's budget is applied — the " +
                                "working value, not the raw gene." })}>
                  Expression — the phenotype</button></h4>
              {Object.entries(inspect.expressed ?? {}).map(([k, v]) => (
                <div key={k} className="flex items-center gap-2">
                  <button className="w-28 truncate text-left underline
                                     decoration-dotted decoration-neutral-600"
                          onClick={() => setLocusInfo({ name: k,
                            value: `${Math.round(v * 100)}%`,
                            text: inspect.locus_help?.[k] })}>{k}</button>
                  <div className="flex-1 h-1.5 bg-neutral-700 rounded">
                    <div className="h-1.5 rounded bg-sky-300/80"
                         style={{ width: `${Math.min(100, v * 100)}%` }} />
                  </div>
                  <span className="w-10 text-right opacity-60">
                    {Math.round(v * 100)}%</span>
                </div>))}
              <h4 className="opacity-70 mt-3 mb-1">Faculties</h4>
              {Object.entries(inspect.faculties ?? {}).map(([k, v]) => (
                <div key={k} className="flex justify-between">
                  <button className="underline decoration-dotted
                                     decoration-neutral-600"
                          onClick={() => setLocusInfo({ name: k,
                            value: `${Math.round(v * 100)}%`,
                            text: inspect.locus_help?.[k] })}>{k}</button>
                  <span className="opacity-60">{Math.round(v * 100)}%</span>
                </div>))}
            </>}
            {(inspect.influences?.length > 0 ||
              inspect.prompt_mods?.length > 0) && <>
              <h4 className="opacity-70 mt-3 mb-1 text-fuchsia-300">
                Influences — placed in this agent by others</h4>
              {inspect.prompt_mods?.map((m, i) => (
                <div key={"pm" + i} className="text-xs mb-1">
                  <span className="text-fuchsia-400">✒ smithed</span> by{" "}
                  {m.by_name ?? m.by}: <span className="opacity-80">
                    “{m.text}”</span>
                </div>))}
              {inspect.influences?.filter(i => i.kind === "seeded")
                .map((m, i) => (
                <div key={"sd" + i} className="text-xs mb-1">
                  <span className="text-fuchsia-400">🌱 seeded</span> by{" "}
                  {m.by_name ?? m.by}: <span className="opacity-80">
                    “{m.text}”</span>
                </div>))}
              <div className="opacity-40 text-xs">the agent itself cannot
                see these unless it holds Introspection; they wash out at
                death</div>
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
                      believes {Math.round((l.believed ?? 0) / 100)}%
                      <span className="opacity-60"> · truth </span>
                      {l.actual != null
                        ? `${Math.round(l.actual / 100)}%` : "?"}
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
            {(inspect.infections?.length > 0 ||
              inspect.infection_history?.length > 0 ||
              inspect.antigens?.length > 0) && <>
              <h4 className="opacity-70 mt-3 mb-1">Health record</h4>
              {inspect.infections?.map((i, k) => (
                <button key={"inf" + k} className="block text-left
                             text-red-400 text-xs underline
                             decoration-dotted"
                  onClick={() => setLocusInfo({
                    name: i.strain_uuid ?? "unknown strain",
                    rows: [
                      ["signature", <StrainStrip vec={i.signature} />],
                      ["caught", i.caught_at
                        ? new Date(i.caught_at * 1000).toLocaleString() : "?"],
                      ["detected", i.detected ? "yes" : "not yet"],
                      ["synthesis completes", i.synth_done_at
                        ? new Date(i.synth_done_at * 1000).toLocaleString()
                        : "?"],
                      ["contagion", i.contagion?.toFixed?.(2) ?? "?"],
                      ["warps expression", Object.entries(i.mods ?? {})
                        .map(([l, f]) =>
                          `${l} ${f > 0 ? "+" : ""}${Math.round(f * 100)}%`)
                        .join(", ") || "unknown"],
                    ]})}>
                  ● infected — {i.strain_uuid ?? "unknown strain"}
                  <StrainStrip vec={i.signature} />
                  {i.detected ? " (detected)" : " (undetected)"}
                </button>))}
              {inspect.infection_history?.map((h, k) => (
                <div key={"his" + k} className="opacity-50 text-xs">
                  ○ survived {h.strain_uuid ?? "a strain"}
                  {(() => {
                    const ag = inspect.antigens?.find(a =>
                      a.strain_uuid === h.strain_uuid);
                    return ag ? " — countered by its antigen below" : "";
                  })()}
                </div>))}
              {(inspect.antigens ?? [])
                .filter(a => (a.potency ?? 0) > 0.05).map((a, k) => (
                <button key={"ant" + k} className="flex text-left
                             text-emerald-500/80 text-xs items-center gap-1
                             underline decoration-dotted"
                  onClick={() => setLocusInfo({
                    name: `antigen vs ${a.strain_uuid ?? "?"}`,
                    value: `${Math.round((a.potency ?? 0) * 100)}%`,
                    rows: [
                      ["vector", <StrainStrip vec={a.vector} />],
                      ["counters", a.strain_uuid ?? "an unknown strain"],
                      ["made", a.made_at
                        ? new Date(a.made_at * 1000).toLocaleString() : "?"],
                      ["decays", a.decay_rate
                        ? `${(a.decay_rate * 86400 * 100).toFixed(2)}%/day`
                        : "?"],
                      ["how it works", "coverage: each dimension of the " +
                       "vector shields the matching dimension of a strain " +
                       "signature; overlap above 55% blocks infection"],
                    ]})}>
                  ◆ antigen<StrainStrip vec={a.vector} />
                  <span className="opacity-70">
                    counters {a.strain_uuid ?? "an unknown strain"}</span>
                  <span className="flex-1 h-1 bg-neutral-700 rounded
                                   max-w-16">
                    <span className="block h-1 rounded bg-emerald-500"
                          style={{ width:
                            `${Math.round((a.potency ?? 0) * 100)}%` }} />
                  </span>
                  {Math.round((a.potency ?? 0) * 100)}%
                </button>))}
              {(inspect.antigens ?? [])
                .filter(a => (a.potency ?? 0) <= 0.05).map((a, k) => (
                <div key={"spent" + k} className="opacity-40 text-xs">
                  ◇ spent antigen<StrainStrip vec={a.vector} dead />
                  <span> once countered {a.strain_uuid ?? "a strain"} —
                    faded, the door is open again</span>
                </div>))}
            </>}
            {inspect.decisions?.length > 0 && <>
              <h4 className="opacity-70 mt-3 mb-1">Recent decisions</h4>
              {inspect.decisions.map((d, i) => (
                <button key={i}
                     className="block w-full text-left mb-1.5 pb-1.5
                                border-b border-neutral-800
                                hover:bg-neutral-800/50"
                  onClick={() => setLocusInfo({
                    name: `${d.choice} (${d.model})`,
                    rows: [
                      ["situation", d.situation ?? "?"],
                      ["options", (d.options ?? []).join(", ")],
                      ["chose", d.choice],
                      ["system prompt", d.prompt?.system ??
                       "(not recorded -- prompts are kept from 2026-09-04)"],
                      ["user prompt", d.prompt?.user ?? ""],
                    ]})}>
                  <div className="font-medium">{d.choice}</div>
                  <div className="opacity-50 text-xs">
                    of {(d.options ?? []).join(", ")} · {d.model}
                    {d.prompt && " · 📜"}</div>
                </button>))}
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
                    ? "text-emerald-500/70" : m.kind === "reply"
                    ? "text-violet-400/80" : "text-sky-500/70")}>
                    {m.kind === "instruction"
                      ? "owner instruction — becomes an objective"
                      : m.kind === "reply"
                      ? "your agent reports back"
                      : "assertion — a claim, not a command"}</div>
                  <div className={"rounded px-2 py-1 whitespace-pre-wrap "
                    + (m.kind === "reply"
                       ? "bg-violet-950/60 border border-violet-800/40"
                       : "bg-neutral-800")}>
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
    // back from the authority: the token already rides in a cookie; the
    // URL copy is transit residue and should not linger in the address bar
    const q = new URLSearchParams(location.search);
    if (q.get("authority_token")) {
      q.delete("authority_token");
      const qs = q.toString();
      history.replaceState({}, "", location.pathname + (qs ? `?${qs}` : ""));
    }
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
  const [adminOpen, setAdminOpen] = useState(false);
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
  const [snapInfo, setSnapInfo] = useState(null);
  const [floodAnim, setFloodAnim] = useState(false);
  const floodCountRef = useRef(null);
  const noteFloodCount = (snap) => {
    const n = snap.flood_count ?? 0;
    if (floodCountRef.current != null && n > floodCountRef.current) {
      setFloodAnim(true);
      setTimeout(() => setFloodAnim(false), 6500);
    }
    floodCountRef.current = n;
  };
  const [listOpen, setListOpen] = useState(false);
  const loadRef = useRef(null);
  const esRef = useRef(null);
  const [inspect, setInspect] = useState(null);   // Rule 13.1 panel
  const [menu, setMenu] = useState(null);         // {hit, x, y}
  const canvasApi = useRef(null);

  useEffect(() => {
    if (!realm || !ref.current) return;
    floodCountRef.current = null;        // a fresh world is not "a flood"
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
            ({ uuid: a.agent_uuid, name: a.name, infected: a.infected,
               colour_pair: a.colour_pair, generation: a.generation })));
          setSnapInfo({ stock: snap.stock, kinds: snap.kinds,
                        colours: snap.colours,
                        listings: snap.market_open ?? [],
                        agentCount: (snap.agents ?? []).length });
          noteFloodCount(snap);
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
      await load();                        // instant paint + fallback path
      // live stream: one server-side assembly serves every viewer; the
      // 5s poll survives only as the fallback when the stream errors
      let usePoll = false;
      const es = new EventSource(`${API}/worlds/${realm}/stream`);
      esRef.current = es;
      es.onmessage = (ev) => {
        if (dead) return;
        try {
          const snap = JSON.parse(ev.data);
          canvas.setSnapshot(snap);
          setAgentList((snap.agents ?? []).map(a =>
            ({ uuid: a.agent_uuid, name: a.name, infected: a.infected,
               colour_pair: a.colour_pair, generation: a.generation })));
          setSnapInfo({ stock: snap.stock, kinds: snap.kinds,
                        colours: snap.colours,
                        listings: snap.market_open ?? [],
                        agentCount: (snap.agents ?? []).length });
          noteFloodCount(snap);
          setFlood(snap.flood_countdown ?? null);
          setLive(true);
          setStatus(`live — ${realm}`);
        } catch { /* keepalive or partial frame */ }
      };
      es.onerror = () => {
        if (dead || usePoll) return;
        usePoll = true;                    // EventSource retries itself; we
        timer = setInterval(load, 5000);   // also poll so nothing freezes
        setStatus(`watching ${realm} (poll)`);
      };
    })();
    return () => { dead = true; clearInterval(timer);
                   esRef.current?.close(); canvas?.destroy(); };
  }, [realm]);

  return (
    <div className="h-screen w-screen flex flex-col bg-neutral-900 text-neutral-200">
      <header className="px-4 py-2 flex gap-3 items-center border-b border-neutral-700">
        <a href="/" className="no-underline text-inherit"><strong>genome</strong></a>
        <span className="text-xs opacity-50 hidden sm:inline">
          by <a className="underline" target="_blank" rel="noreferrer"
                href="https://www.linkedin.com/in/crajah">Chandan Rajah</a>
          {" · on "}
          <a className="underline" target="_blank" rel="noreferrer"
             href="https://crajah.github.io/post-graph">post-graph</a>
        </span>
        <input className="bg-neutral-800 px-2 py-1 rounded text-sm w-72"
               placeholder="world realm…" defaultValue={realm}
               onKeyDown={e => e.key === "Enter" && setRealm(e.target.value)} />
        <span className="text-sm opacity-70">{status}</span>
        <span className="flex-1" />
        {me && !me.authenticated && <>
          <span className="text-xs opacity-50">sign in:</span>
          <a className="text-sm px-2 py-1 rounded bg-neutral-100 text-neutral-900
                        hover:bg-white no-underline font-medium"
             href={`/authority/login/google?return_to=${
               encodeURIComponent("/genome/")}`}>Google</a>
          <a className="text-sm px-2 py-1 rounded bg-neutral-700
                        hover:bg-neutral-600 no-underline font-medium"
             href={`/authority/login/microsoft?return_to=${
               encodeURIComponent("/genome/")}`}>Microsoft</a>
        </>}
        <button className="text-sm opacity-60" title="Simulation admin"
                onClick={() => setAdminOpen(true)}>⌘</button>
        {me?.authenticated && <Settings />}
        {me?.authenticated && <Connections />}
        {me?.authenticated &&
          <Chats onOpen={(u) => setInspect({ agent_uuid: u })} />}
        {me?.authenticated && <Bell />}
        {me?.authenticated && me.world_realm && realm === me.world_realm &&
          <button title="Materialise a further agent: 2 units from each of
four distinct kinds in your store (Rule 2.1). The four-kind wall is the
whole game -- the commons market is how the far kinds arrive."
                  className="text-xs px-2 py-1 rounded bg-indigo-800
                             hover:bg-indigo-700"
                  onClick={async () => {
                    const r = await fetch(`${API}/me/materialize`, {
                      method: "POST", credentials: "include" });
                    const d = await r.json();
                    alert(d.ok
                      ? `A new agent takes shape: ${d.agent}`
                      : d.error);
                  }}>materialise agent</button>}
        {me?.authenticated && me.world_realm && realm !== me.world_realm &&
          <button title="Return to your home world"
                  className="text-lg"
                  onClick={() => {
                    history.pushState({}, "", `?world=${me.world_realm}`);
                    setRealm(me.world_realm);
                  }}>⌂</button>}
        {me?.authenticated && me.verified === false &&
          <span className="text-xs px-2 py-0.5 rounded bg-amber-900
                           text-amber-200"
                title="A verification link was sent to your address">
            unverified</span>}
        {me?.authenticated &&
          <span className="text-sm opacity-60">your world: {me.world_realm}</span>}
        {me?.authenticated &&
          <button className="text-xs px-2 py-1 rounded bg-neutral-800
                             hover:bg-neutral-700 opacity-80"
                  title="Sign out — your world keeps living without you"
                  onClick={async () => {
                    await fetch(`${API}/auth/logout`, {
                      method: "POST", credentials: "include" });
                    setMe({ authenticated: false });
                  }}>logout</button>}
      </header>
      <div className="flex-1 flex min-h-0 relative">
        {adminOpen && <AdminPanel onClose={() => setAdminOpen(false)} />}
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
                <AgentTag a={{ name: a.name, agent_uuid: a.uuid,
                               colour_pair: a.colour_pair,
                               generation: a.generation }} />
                {a.infected && <span className="text-red-400"> · infected</span>}
              </button>))}
            {agentList.length === 0 &&
              <div className="px-3 py-2 opacity-60">nobody here</div>}
          </nav>)}
        <StockPanel info={snapInfo} />
        <MarketPanel info={snapInfo} />
        {me?.authenticated && realm === me.world_realm &&
          <PlanTable realm={realm} info={snapInfo} />}
        <FloodWave active={floodAnim} />
        <Legend />
        <Timeline realm={realm} />
        <Ticker realm={realm} />
        {menu && <EntityMenu menu={menu} info={snapInfo}
          onClose={() => setMenu(null)}
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
