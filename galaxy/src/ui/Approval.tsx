import { AnimatePresence, motion } from "framer-motion";
import { send } from "../lib/bridge";
import { useJarvis } from "../lib/store";

/** Every risky action (send email, delete, run commands, settings) waits here for an explicit decision. */
export function ApprovalCard() {
  const a = useJarvis((s) => s.approval);
  return (
    <AnimatePresence>
      {a && (
        <motion.div initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.95 }}
          className="fixed left-1/2 top-1/2 z-50 w-[min(560px,92vw)] -translate-x-1/2 -translate-y-1/2">
          <div className="glass border-amber-300/40 p-5 shadow-[0_0_60px_rgba(255,196,77,0.15)]">
            <div className="hud-title !text-amber-200">Authorization required</div>
            <div className="mt-2 text-base text-amber-50">JARVIS wants to: {a.summary}</div>
            <div className="mt-1 font-mono text-[11px] text-amber-200/60">tool: {a.tool}</div>
            {a.preview && <pre className="mt-3 max-h-64 overflow-auto whitespace-pre-wrap rounded bg-black/40 p-3 text-xs text-cyan-50/90">{a.preview}</pre>}
            <div className="mt-4 flex justify-end gap-2">
              <button className="hud-btn danger" onClick={() => send("approval", { approve: false })}>Deny</button>
              <button className="hud-btn on" onClick={() => send("approval", { approve: true })}>Approve</button>
            </div>
            <div className="mt-2 text-right text-[10px] text-cyan-100/40">You can also answer out loud: "yes" or "no". No answer means denied.</div>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
