// Bottom dock: live transcription, conversation history, text input, mic/interrupt/clear controls, VU meter.
import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useRef, useState } from "react";
import { ask, levels, request, send } from "../lib/bridge";
import { useJarvis } from "../lib/store";

function VuMeter() {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    let raf = 0;
    const hist = new Array(48).fill(0);
    const draw = () => {
      const c = ref.current;
      if (c) {
        const g = c.getContext("2d")!;
        const st = useJarvis.getState().state;
        hist.shift();
        hist.push(st === "speaking" ? levels.speech : levels.mic);
        g.clearRect(0, 0, c.width, c.height);
        hist.forEach((v, i) => {
          const h = Math.max(1.5, v * c.height);
          g.fillStyle = st === "speaking" ? "rgba(200,245,255,0.85)" : "rgba(127,231,255,0.75)";
          g.fillRect(i * 3, (c.height - h) / 2, 2, h);
        });
      }
      raf = requestAnimationFrame(draw);
    };
    draw();
    return () => cancelAnimationFrame(raf);
  }, []);
  return <canvas ref={ref} width={144} height={26} className="opacity-90" />;
}

export function Conversation() {
  const { messages, partial, state, privacy, hasMic } = useJarvis();
  const [text, setText] = useState("");
  const [expanded, setExpanded] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const log = useRef<HTMLDivElement>(null);
  useEffect(() => { log.current?.scrollTo({ top: 1e9, behavior: "smooth" }); }, [messages.length, expanded]);
  useEffect(() => {
    const f = () => input.current?.focus();
    addEventListener("jarvis:focus-input", f);
    return () => removeEventListener("jarvis:focus-input", f);
  }, []);

  const submit = () => {
    if (!text.trim()) return;
    ask(text.trim());
    setText("");
  };
  const busy = ["thinking", "speaking", "executing", "approval"].includes(state);
  const shown = expanded ? messages : messages.slice(-4);

  return (
    <div className="fixed bottom-5 left-1/2 z-20 w-[min(760px,92vw)] -translate-x-1/2">
      <AnimatePresence>
        {(shown.length > 0 || partial) && (
          <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
            ref={log} className={`mb-2 space-y-1.5 overflow-y-auto px-2 ${expanded ? "glass max-h-[46vh] p-3" : "max-h-48"}`}
            style={expanded ? {} : { maskImage: "linear-gradient(transparent, #000 30%)" }}>
            {shown.map((m) => (
              <div key={m.id} className={`text-sm leading-relaxed ${m.who === "you" ? "text-right text-cyan-100/70" : m.who === "system" ? "text-xs text-cyan-300/60" : "text-cyan-50"}`}>
                {m.who === "jarvis" && <span className="mr-2 font-hud text-[10px] tracking-[0.3em] text-cyan-300">JARVIS</span>}
                <span className={m.who === "you" ? "inline-block rounded-lg bg-cyan-400/10 px-3 py-1" : ""}>{m.text}</span>
              </div>
            ))}
            {partial && <div className="text-right text-sm italic text-cyan-200/60">{partial}…</div>}
          </motion.div>
        )}
      </AnimatePresence>
      <div className="glass scanline relative flex items-center gap-2 px-3 py-2">
        <button className={`hud-btn ${state === "listening" ? "on" : ""}`} disabled={!hasMic || privacy}
          title={hasMic ? "Talk to JARVIS (Ctrl+Space). Or say 'Hey JARVIS'." : "No microphone detected"} onClick={() => send("wake")}>
          {state === "listening" ? "● Listening" : "🎙 Talk"}
        </button>
        <VuMeter />
        <input ref={input} className="hud-input flex-1" placeholder={privacy ? "Privacy mode: typing still works" : "Message JARVIS…  ( / to focus )"}
          value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") submit(); e.stopPropagation(); }} />
        <button className="hud-btn" onClick={submit} disabled={!text.trim()}>Send</button>
        <button className="hud-btn" disabled={!busy} title="Interrupt (Esc while busy)" onClick={() => send("interrupt")}>⏹</button>
        <button className={`hud-btn ${privacy ? "on" : ""}`} title="Microphone privacy: stops listening and remembering"
          onClick={() => send("privacy", { on: !privacy })}>{privacy ? "🔇" : "🔒"}</button>
        <button className="hud-btn" title="Show conversation history" onClick={() => setExpanded(!expanded)}>{expanded ? "▾" : "▴"}</button>
        <button className="hud-btn" title="Clear conversation (also resets JARVIS's context)"
          onClick={async () => { await request("clear_conversation"); useJarvis.getState().clearChat(); }}>✕</button>
      </div>
    </div>
  );
}
