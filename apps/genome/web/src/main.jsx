// Chrome is React; the canvas is not (interface-spec Rules 6.1/6.2).
import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { createWorldCanvas } from "./world/canvas.js";

const API = import.meta.env.VITE_GENOME_API ?? "";

function App() {
  const ref = useRef(null);
  const [realm, setRealm] = useState(
    new URLSearchParams(location.search).get("world") ?? "");
  const [status, setStatus] = useState("no world selected");

  useEffect(() => {
    if (!realm || !ref.current) return;
    let canvas, timer, dead = false;
    (async () => {
      canvas = await createWorldCanvas(ref.current, {});
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
      </header>
      <div ref={ref} className="flex-1" />
    </div>
  );
}

createRoot(document.getElementById("root")).render(<App />);
