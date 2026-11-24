import { motion } from "framer-motion";
import { ask } from "../lib/bridge";
import { PLANETS } from "../lib/planets";
import { useJarvis } from "../lib/store";

const ago = (ts: number) => {
  const s = Math.round((Date.now() - ts) / 1000);
  return s < 60 ? `${s}s` : s < 3600 ? `${Math.round(s / 60)}m` : `${Math.round(s / 3600)}h`;
};

export function SidePanels() {
  const { notes, tasks } = useJarvis();
  return (
    <>
      <motion.div initial={{ opacity: 0, x: -20 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: 1.5 }}
        className="fixed left-5 top-24 z-10 w-64 space-y-3">
        <div className="glass p-3">
          <div className="hud-title mb-2">Notifications</div>
          <div className="max-h-48 space-y-1.5 overflow-y-auto text-xs">
            {notes.length === 0 && <div className="text-cyan-100/40">All quiet.</div>}
            {notes.slice(0, 12).map((n) => (
              <div key={n.id} className={`flex gap-2 ${n.kind === "error" ? "text-red-300" : n.kind === "ok" ? "text-emerald-200/90" : "text-cyan-100/80"}`}>
                <span className="w-7 shrink-0 text-cyan-300/40">{ago(n.ts)}</span><span>{n.text}</span>
              </div>
            ))}
          </div>
        </div>
        <div className="glass p-3">
          <div className="hud-title mb-2">Current tasks</div>
          <div className="max-h-56 space-y-1.5 overflow-y-auto text-xs">
            {tasks.length === 0 && <div className="text-cyan-100/40">No tool activity yet.</div>}
            {tasks.slice(0, 12).map((t) => (
              <div key={t.id} className="flex items-start gap-2">
                <span className={t.status === "running" ? "animate-pulse text-cyan-300" : t.status === "ok" ? "text-emerald-300" : "text-red-300"}>
                  {t.status === "running" ? "◌" : t.status === "ok" ? "✓" : "✕"}</span>
                <span className="text-cyan-100/80"><b className="font-medium text-cyan-200">{t.tool}</b> {t.summary.slice(0, 70)}</span>
              </div>
            ))}
          </div>
        </div>
      </motion.div>
      <motion.div initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: 1.7 }}
        className="fixed right-5 top-24 z-10 w-56 space-y-3">
        <div className="glass p-3">
          <div className="hud-title mb-2">Destinations</div>
          <div className="space-y-0.5">
            {PLANETS.map((p) => (
              <button key={p.id} className="flex w-full items-center gap-2 rounded px-2 py-1 text-left text-xs text-cyan-100/80 hover:bg-cyan-400/10"
                onMouseEnter={() => useJarvis.getState().setHover(p.id)} onMouseLeave={() => useJarvis.getState().setHover(null)}
                onClick={() => useJarvis.getState().setFocus(p.id)}>
                <span className="h-2 w-2 rounded-full" style={{ background: p.colors[1], boxShadow: `0 0 8px ${p.colors[1]}` }} />
                <span className="flex-1">{p.name}</span><span className="font-mono text-cyan-300/40">{p.shortcut}</span>
              </button>
            ))}
          </div>
        </div>
        <div className="glass p-3">
          <div className="hud-title mb-2">Quick tools</div>
          <div className="grid grid-cols-2 gap-1.5 text-[11px]">
            {[
              ["Briefing", "Give me a short briefing: today's calendar, important unread email and my open tasks."],
              ["Screen", "What's on my screen right now?"],
              ["Inbox", "Which emails need my attention?"],
              ["Tomorrow", "What do I have scheduled tomorrow?"],
            ].map(([l, q]) => <button key={l} className="hud-btn !px-2" onClick={() => ask(q)}>{l}</button>)}
          </div>
        </div>
      </motion.div>
    </>
  );
}
