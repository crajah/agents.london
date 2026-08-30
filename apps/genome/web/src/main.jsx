// Chrome is React; the canvas is not (interface-spec Rules 6.1/6.2).
import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { createWorldCanvas } from "./world/canvas.js";

const API = import.meta.env.VITE_GENOME_API ?? "";

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

  useEffect(() => {
    if (!realm || !ref.current) return;
    let canvas, timer, dead = false;
    (async () => {
      canvas = await createWorldCanvas(ref.current, {
        onPortalClick: (toWorld) => {           // traverse (Rule 5.3/5.4):
          history.pushState({}, "", `?world=${toWorld}`);  // free, unbounded
          setInspect(null); setRealm(toWorld);
        },
        onAgentClick: async (uuid) => {
          const [r, rd] = await Promise.all([
            fetch(`${API}/agents/${uuid}`),
            fetch(`${API}/agents/${uuid}/decisions?limit=8`)]);
          setInspect({ ...(await r.json()), decisions: await rd.json() });
        },
      });
      const load = async () => {
        try {
          const r = await fetch(`${API}/worlds/${realm}/snapshot`);
          if (!r.ok) throw new Error(r.status);
          canvas.setSnapshot(await r.json());
          setStatus(`watching ${realm}`);
        } catch (e) { setStatus(`cannot reach world: ${e.message}`); }
      };
      await load();
      timer = setInterval(load, 15000);     // events feed replaces this later
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
          <a className="text-sm underline opacity-80"
             href={`${API}/auth/google/login`}>Sign in with Google</a>
          <a className="text-sm underline opacity-80"
             href={`${API}/auth/microsoft/login`}>Microsoft</a>
        </>}
        {me?.authenticated &&
          <span className="text-sm opacity-60">your world: {me.world_realm}</span>}
      </header>
      <div className="flex-1 flex min-h-0">
        <div ref={ref} className="flex-1" />
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
