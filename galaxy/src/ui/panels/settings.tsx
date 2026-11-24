import { useEffect, useState } from "react";
import { request, send } from "../../lib/bridge";
import { useJarvis } from "../../lib/store";
import { Muted, Section } from "./kit";

const TRUST = ["0 · Observe only", "1 · Ask before everything", "2 · Ask for external & destructive (recommended)", "3 · Trusted tools auto-approved", "4 · Autonomous (still asks for destructive)"];
const TABS = ["General", "Permissions", "Memory", "Keys", "Audit", "Diagnostics"] as const;

export function SettingsPanel() {
  const [tab, setTab] = useState<(typeof TABS)[number]>("General");
  return (
    <>
      <div className="mb-4 flex flex-wrap gap-1.5">{TABS.map((t) => <button key={t} className={`hud-btn !px-2 ${tab === t ? "on" : ""}`} onClick={() => setTab(t)}>{t}</button>)}</div>
      {tab === "General" && <General />}
      {tab === "Permissions" && <Permissions />}
      {tab === "Memory" && <Memory />}
      {tab === "Keys" && <Keys />}
      {tab === "Audit" && <Audit />}
      {tab === "Diagnostics" && <Diagnostics />}
    </>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="mb-3 block text-xs text-cyan-200/70"><div className="mb-1">{label}</div>{children}</label>;
}

function General() {
  const { settings, voices } = useJarvis();
  const [v, setV] = useState<Record<string, any>>(settings);
  const [saved, setSaved] = useState("");
  const set = (k: string, val: any) => setV({ ...v, [k]: val });
  const save = async () => {
    const keys = ["user_name", "voice", "wake_sensitivity", "follow_up_seconds", "proactive", "briefing_time", "model_fast", "model_reasoning", "personality", "graphics_quality", "approval_timeout"];
    const r = await request("settings.update", { values: Object.fromEntries(keys.map((k) => [k, v[k]])) });
    if (r.settings) useJarvis.getState().set({ settings: r.settings });
    setSaved(r.error || "Saved.");
  };
  const stop = (e: React.KeyboardEvent) => e.stopPropagation();
  return (
    <Section title="JARVIS configuration">
      <Field label="How JARVIS addresses you"><input className="hud-input" value={v.user_name || ""} onChange={(e) => set("user_name", e.target.value)} onKeyDown={stop} /></Field>
      <Field label="Voice (Microsoft neural voices via edge-tts)">
        <select className="hud-input" value={v.voice} onChange={(e) => set("voice", e.target.value)}>{voices.map((x) => <option key={x} className="bg-slate-900">{x}</option>)}</select>
      </Field>
      <Field label="Personality (added to the system prompt)"><textarea className="hud-input h-16" value={v.personality || ""} onChange={(e) => set("personality", e.target.value)} onKeyDown={stop} /></Field>
      <Field label={`Wake word sensitivity: ${v.wake_sensitivity} (wake word "Hey JARVIS", restart to apply)`}>
        <input type="range" min={0.2} max={0.9} step={0.05} className="w-full" value={v.wake_sensitivity} onChange={(e) => set("wake_sensitivity", +e.target.value)} />
      </Field>
      <Field label={`Follow-up listening window: ${v.follow_up_seconds}s`}>
        <input type="range" min={3} max={30} step={1} className="w-full" value={v.follow_up_seconds} onChange={(e) => set("follow_up_seconds", +e.target.value)} />
      </Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Fast model"><input className="hud-input" value={v.model_fast || ""} onChange={(e) => set("model_fast", e.target.value)} onKeyDown={stop} /></Field>
        <Field label="Reasoning model"><input className="hud-input" value={v.model_reasoning || ""} onChange={(e) => set("model_reasoning", e.target.value)} onKeyDown={stop} /></Field>
        <Field label="Daily briefing time (blank = off)"><input className="hud-input" value={v.briefing_time || ""} onChange={(e) => set("briefing_time", e.target.value)} onKeyDown={stop} /></Field>
        <Field label="Graphics quality">
          <select className="hud-input" value={v.graphics_quality || "low"} onChange={(e) => set("graphics_quality", e.target.value)}><option className="bg-slate-900">high</option><option className="bg-slate-900">low</option></select>
        </Field>
      </div>
      <label className="mb-3 flex items-center gap-2 text-xs text-cyan-200/70"><input type="checkbox" checked={!!v.proactive} onChange={(e) => set("proactive", e.target.checked)} /> Proactive reminders and heads-ups</label>
      <button className="hud-btn on" onClick={save}>Save</button> <span className="text-xs text-cyan-200/60">{saved}</span>
    </Section>
  );
}

function Permissions() {
  const { settings, tools } = useJarvis();
  const [lvl, setLvl] = useState(settings.trust_level ?? 2);
  const [ask, setAsk] = useState<string[]>(settings.always_ask_tools || []);
  const [msg, setMsg] = useState("");
  const save = async () => {
    const r = await request("permissions.update", { trust_level: lvl, always_ask_tools: ask });
    if (r.settings) useJarvis.getState().set({ settings: r.settings });
    setMsg(r.error || "Permissions saved.");
  };
  return (
    <Section title="Security permissions">
      <Field label="Trust level">
        <select className="hud-input" value={lvl} onChange={(e) => setLvl(+e.target.value)}>{TRUST.map((t, i) => <option key={i} value={i} className="bg-slate-900">{t}</option>)}</select>
      </Field>
      <Muted>Sending email, invitations, deleting files, running commands and changing settings always need approval at level 2. Trust level can only be changed here, never by voice.</Muted>
      <div className="mt-4 mb-2 text-xs text-cyan-200/70">Always ask before these tools:</div>
      <div className="grid max-h-56 grid-cols-2 gap-1 overflow-y-auto text-xs">
        {tools.map((t) => (
          <label key={t} className="flex items-center gap-2 text-cyan-100/80">
            <input type="checkbox" checked={ask.includes(t)} onChange={(e) => setAsk(e.target.checked ? [...ask, t] : ask.filter((x) => x !== t))} />{t}
          </label>
        ))}
      </div>
      <button className="hud-btn on mt-3" onClick={save}>Save permissions</button> <span className="text-xs text-cyan-200/60">{msg}</span>
    </Section>
  );
}

function Memory() {
  const [items, setItems] = useState<any[]>([]);
  const [q, setQ] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [edit, setEdit] = useState<{ id: number; content: string } | null>(null);
  const [history, setHistory] = useState<any[]>([]);
  const load = () => request("memory.list", { query: q }).then((r) => { setItems(r.items || []); setEnabled(r.enabled); });
  useEffect(() => { load(); request("history.list").then((r) => setHistory(r.items || [])); }, []);
  return (
    <>
      <Section title="Long-term memory" right={<label className="flex items-center gap-2 text-xs text-cyan-200/70"><input type="checkbox" checked={enabled}
        onChange={async (e) => { const r = await request("memory.enable", { on: e.target.checked }); setEnabled(r.enabled); }} /> Memory enabled</label>}>
        <div className="mb-2 flex gap-2"><input className="hud-input" placeholder="Search memories…" value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => { e.stopPropagation(); e.key === "Enter" && load(); }} /><button className="hud-btn" onClick={load}>Search</button></div>
        <div className="max-h-72 space-y-1 overflow-y-auto">
          {items.length === 0 && <Muted>No memories stored.</Muted>}
          {items.map((m) => (
            <div key={m.id} className="rounded border border-cyan-300/10 p-2 text-xs">
              {edit?.id === m.id ? (
                <div className="flex gap-1"><input className="hud-input" value={edit?.content ?? ""} onChange={(e) => setEdit({ id: m.id, content: e.target.value })} onKeyDown={(e) => e.stopPropagation()} />
                  <button className="hud-btn" onClick={async () => { await request("memory.update", { ...edit }); setEdit(null); load(); }}>Save</button></div>
              ) : (
                <div className="flex items-start gap-2">
                  <span className="rounded bg-cyan-400/10 px-1.5 text-[10px] uppercase text-cyan-300">{m.category}</span>
                  <span className="flex-1 text-cyan-50">{m.content}</span>
                  <button className="text-cyan-300/60 hover:text-cyan-100" onClick={() => setEdit({ id: m.id, content: m.content })}>edit</button>
                  <button className="text-red-300/60 hover:text-red-200" onClick={async () => { await request("memory.delete", { id: m.id }); load(); }}>delete</button>
                </div>
              )}
            </div>
          ))}
        </div>
      </Section>
      <Section title="Conversation history" right={<button className="hud-btn danger !py-0.5" onClick={async () => {
        if (!confirm("Delete all stored conversation history and tool traces? Memories and notes are kept.")) return;
        await request("history.clear", { confirm: true }); await request("clear_conversation"); useJarvis.getState().clearChat(); setHistory([]);
      }}>Clear all</button>}>
        <div className="max-h-60 space-y-1 overflow-y-auto text-xs">
          {history.length === 0 && <Muted>No history.</Muted>}
          {history.map((h) => (
            <div key={h.id} className="border-b border-cyan-300/5 pb-1">
              <span className="text-cyan-300/40">{new Date(h.started_at * 1000).toLocaleString([], { dateStyle: "short", timeStyle: "short" })} · {h.channel}</span>
              <div className="text-cyan-100/90">› {h.input}</div>
              {h.output && <div className="truncate text-cyan-100/50">{h.output}</div>}
            </div>
          ))}
        </div>
      </Section>
    </>
  );
}

function Keys() {
  const [st, setSt] = useState<{ status: Record<string, boolean>; labels: Record<string, string> } | null>(null);
  const [vals, setVals] = useState<Record<string, string>>({});
  useEffect(() => { request("secrets.status").then((r) => setSt(r as any)); }, []);
  if (!st) return null;
  return (
    <Section title="API keys (encrypted with Windows DPAPI)">
      {Object.entries(st.labels).map(([k, label]) => (
        <Field key={k} label={`${label} ${st.status[k] ? "· ✓ set" : "· not set"}`}>
          <div className="flex gap-2">
            <input className="hud-input" type="password" placeholder={st.status[k] ? "•••••••• (stored)" : k} value={vals[k] || ""}
              onChange={(e) => setVals({ ...vals, [k]: e.target.value })} onKeyDown={(e) => e.stopPropagation()} />
            <button className="hud-btn" disabled={!vals[k]} onClick={async () => { const r = await request("secrets.set", { name: k, value: vals[k] }); setSt({ ...st, status: r.status }); setVals({ ...vals, [k]: "" }); }}>Save</button>
            {st.status[k] && <button className="hud-btn danger" onClick={async () => { const r = await request("secrets.set", { name: k, value: "" }); setSt({ ...st, status: r.status }); }}>Remove</button>}
          </div>
        </Field>
      ))}
      <Muted>
        Claude: no key needed. JARVIS uses your Claude Code login (run <code>claude</code> once).<br />
        OpenAI: platform.openai.com → API keys (pay-as-you-go billing required), plus <code>pip install openai</code>.<br />
        Keys never leave this PC and are never displayed again.
      </Muted>
    </Section>
  );
}

function Audit() {
  const [data, setData] = useState<any>(null);
  const load = () => request("audit.list", { limit: 120 }).then(setData);
  useEffect(() => { load(); }, []);
  return (
    <Section title="Audit log" right={<button className="text-xs text-cyan-300/60 hover:text-cyan-200" onClick={load}>refresh</button>}>
      <div className="max-h-[52vh] space-y-0.5 overflow-y-auto font-mono text-[11px]">
        {data?.items?.map((r: any) => (
          <div key={r.id} className="flex gap-2 text-cyan-100/70">
            <span className="text-cyan-300/40">{new Date(r.ts * 1000).toLocaleTimeString()}</span>
            <span className="w-14 text-cyan-300/60">{r.kind}</span>
            <span className="flex-1 truncate text-cyan-50">{r.name}</span>
            <span className={r.status === "ok" || r.status === "approved" ? "text-emerald-300/80" : "text-amber-200/80"}>{r.status}</span>
          </div>
        ))}
      </div>
    </Section>
  );
}

function Diagnostics() {
  const { connected, hasMic, privacy, mock, tools } = useJarvis();
  const [info, setInfo] = useState<any>(null);
  const [fps, setFps] = useState(0);
  useEffect(() => {
    request("sysinfo").then(setInfo);
    let n = 0, raf = 0; const t0 = performance.now();
    const tick = () => { n++; if (performance.now() - t0 < 2000) raf = requestAnimationFrame(tick); else setFps(Math.round(n / 2)); };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);
  const row = (k: string, v: any, ok = true) => <div className="flex justify-between border-b border-cyan-300/5 py-1"><span className="text-cyan-200/60">{k}</span><span className={ok ? "text-cyan-50" : "text-amber-200"}>{String(v)}</span></div>;
  return (
    <Section title="System diagnostics">
      <div className="text-xs">
        {row("Core link", connected ? "connected" : "offline", connected)}
        {row("Microphone", hasMic ? (privacy ? "privacy mode" : "active") : "not available", hasMic)}
        {row("Email adapter", mock.email ? "MOCK" : "Gmail", !mock.email)}
        {row("Calendar adapter", mock.calendar ? "MOCK" : "Google Calendar", !mock.calendar)}
        {row("Registered tools", tools.length)}
        {row("Render FPS", fps || "measuring…", fps === 0 || fps > 40)}
        {info && row("Requests / failed", `${info.metrics.runs} / ${info.metrics.runs_failed}`)}
        {info && row("Tool calls / errors / denied", `${info.metrics.tool_calls} / ${info.metrics.tool_errors} / ${info.metrics.tool_denied}`)}
        {info && row("Avg tool latency", `${info.metrics.avg_tool_ms} ms`)}
        {info && row("Bridge uptime", `${Math.round(info.uptime_s / 60)} min`)}
      </div>
      <button className="hud-btn mt-3" onClick={() => send("wake")} disabled={!hasMic}>Test microphone (wake)</button>
    </Section>
  );
}
