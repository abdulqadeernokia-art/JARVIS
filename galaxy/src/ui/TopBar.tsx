import { useEffect, useState } from "react";
import { request, send } from "../lib/bridge";
import { planetById } from "../lib/planets";
import { useJarvis } from "../lib/store";

const LABEL: Record<string, string> = {
  idle: "STANDBY", listening: "LISTENING", thinking: "THINKING", speaking: "SPEAKING", executing: "EXECUTING",
  error: "ERROR", privacy: "PRIVACY", approval: "AWAITING APPROVAL",
};

export function TopBar() {
  const [now, setNow] = useState(new Date());
  const [online, setOnline] = useState(navigator.onLine);
  const { connected, state, privacy, focus, hasMic, conversation } = useJarvis();
  const call = (type: string, payload: Record<string, any> = {}) =>
    request(type, payload).then((r) => r.error && useJarvis.getState().notify(r.error, "error"));
  const minimize = () => {
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
    call("window.minimize");
  };
  const close = (e: React.MouseEvent) => {
    const completely = e.shiftKey;
    if (!confirmClose(completely)) return;
    call("window.close", { completely });
  };
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    const on = () => setOnline(navigator.onLine);
    addEventListener("online", on); addEventListener("offline", on);
    return () => { clearInterval(t); removeEventListener("online", on); removeEventListener("offline", on); };
  }, []);
  const planet = planetById(focus);
  const dot = (ok: boolean) => <span className={`inline-block h-1.5 w-1.5 rounded-full ${ok ? "bg-cyan-300 shadow-[0_0_8px_#7fe7ff]" : "bg-red-400"}`} />;

  return (
    <div className="pointer-events-none fixed inset-x-0 top-0 z-20 flex items-start justify-between px-6 pt-4 font-hud">
      <div className="pointer-events-auto flex items-center gap-4">
        <div>
          <div className="text-lg font-semibold tracking-[0.5em] text-cyan-100 drop-shadow-[0_0_10px_rgba(63,184,255,0.8)]">J.A.R.V.I.S</div>
          <div className="text-[10px] tracking-[0.3em] text-cyan-300/60">{planet ? `◉ ${planet.name.toUpperCase()}` : "PERSONAL UNIVERSE"}</div>
        </div>
        {focus && <button className="hud-btn" onClick={() => useJarvis.getState().setFocus(null)} title="Esc">◂ Galaxy</button>}
      </div>
      <div className="glass pointer-events-auto flex items-center gap-5 px-4 py-2 text-[11px] tracking-[0.2em] text-cyan-100/80">
        <span className="flex items-center gap-2">{dot(connected)} CORE</span>
        <span className="flex items-center gap-2">{dot(online)} NET</span>
        <span className="flex items-center gap-2">{dot(hasMic && !privacy)} MIC</span>
        <span className={`${state === "error" ? "text-red-300" : state === "approval" ? "text-amber-200" : "text-cyan-200"}`}>{connected ? LABEL[state] : "OFFLINE"}</span>
        <span className="text-cyan-300/40">|</span>
        <span>{now.toLocaleDateString(undefined, { weekday: "short", day: "2-digit", month: "short" }).toUpperCase()}</span>
        <span className="font-mono text-cyan-100">{now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</span>
      </div>
      <div className="pointer-events-auto flex gap-2">
        <button className={`hud-btn ${conversation ? "border-cyan-300 text-cyan-100 shadow-[0_0_12px_rgba(127,231,255,0.6)]" : ""}`}
          disabled={!hasMic}
          title={conversation ? "End conversation mode" : "Conversation mode: talk back and forth hands-free (or say \"Jarvis, let's talk\")"}
          onClick={() => call("conversation", { on: !conversation })}>{conversation ? "◉ Talking" : "◎ Talk"}</button>
        <button className="hud-btn" title="Full screen (F)" onClick={toggleFullscreen}>⛶</button>
        <button className="hud-btn danger" title="Emergency stop (Ctrl+Shift+X): halts speech, denies pending approvals, cancels the running task"
          onClick={() => send("emergency_stop")}>■ Stop</button>
        <button className="hud-btn" title="Minimise" onClick={minimize}>—</button>
        <button className="hud-btn danger" title={"Exit JARVIS (he still wakes when you say \"Jarvis\"). Shift+click: quit completely."}
          onClick={close}>✕</button>
      </div>
    </div>
  );
}

// The HUD has no native title bar, so a click on ✕ is the only exit: make sure it was meant.
// (window.confirm is avoided on purpose: it blocks the 3D render loop.)
let armed = 0;
function confirmClose(completely: boolean): boolean {
  if (Date.now() - armed < 3000) return true;
  armed = Date.now();
  useJarvis.getState().notify(`Click ✕ again to ${completely ? "quit JARVIS completely" : "exit JARVIS"}.`, "info");
  return false;
}

export function toggleFullscreen() {
  if (document.fullscreenElement) document.exitFullscreen();
  else document.documentElement.requestFullscreen().catch(() => {});
}
