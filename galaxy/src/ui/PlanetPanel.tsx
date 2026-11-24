import { AnimatePresence, motion } from "framer-motion";
import { Suspense } from "react";
import { planetById } from "../lib/planets";
import { useJarvis } from "../lib/store";
import { PANELS } from "./panels";

export function PlanetPanel() {
  const { focus, panelOpen } = useJarvis();
  const p = planetById(focus);
  const Panel = p ? PANELS[p.panel] : null;
  return (
    <AnimatePresence>
      {p && panelOpen && Panel && (
        <motion.div key={p.id} initial={{ opacity: 0, x: 40, filter: "blur(8px)" }} animate={{ opacity: 1, x: 0, filter: "blur(0px)" }}
          exit={{ opacity: 0, x: 40 }} transition={{ duration: 0.45, ease: "easeOut" }}
          className="glass scanline fixed bottom-28 right-5 top-20 z-30 flex w-[min(520px,94vw)] flex-col overflow-hidden">
          <div className="flex items-center justify-between border-b border-cyan-300/10 px-5 py-3">
            <div>
              <div className="hud-title">Destination · {p.shortcut}</div>
              <div className="font-hud text-xl tracking-[0.2em] text-cyan-50">{p.name.toUpperCase()}</div>
            </div>
            <button className="hud-btn" onClick={() => useJarvis.getState().setFocus(null)}>◂ Galaxy</button>
          </div>
          <div className="flex-1 overflow-y-auto p-5">
            <Suspense fallback={<div className="text-sm text-cyan-200/60">Loading module…</div>}>
              <Panel planet={p} />
            </Suspense>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
