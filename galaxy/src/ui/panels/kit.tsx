import { useState, type ReactNode } from "react";
import { ask, openUrl, request } from "../../lib/bridge";
import type { PlanetLink } from "../../lib/planets";

export function Section({ title, children, right }: { title: string; children: ReactNode; right?: ReactNode }) {
  return (
    <section className="mb-6">
      <div className="mb-2 flex items-center justify-between"><div className="hud-title">{title}</div>{right}</div>
      {children}
    </section>
  );
}

export function LinkGrid({ links }: { links: PlanetLink[] }) {
  return (
    <div className="grid grid-cols-3 gap-2">
      {links.map((l) => (
        <button key={l.url} className="tile" onClick={() => openUrl(l.url)}>
          <span className="text-cyan-50">{l.label}</span>
          <span className="mt-0.5 text-[10px] text-cyan-300/50">{new URL(l.url).hostname.replace("www.", "")}</span>
        </button>
      ))}
    </div>
  );
}

/** A search box that opens a real browser URL built from the query. */
export function SearchBox({ placeholder, build, actions }: { placeholder: string; build: (q: string) => string; actions?: { label: string; build: (q: string) => string }[] }) {
  const [q, setQ] = useState("");
  const go = (b: (q: string) => string) => q.trim() && openUrl(b(encodeURIComponent(q.trim())));
  return (
    <div className="flex gap-2">
      <input className="hud-input" placeholder={placeholder} value={q} onChange={(e) => setQ(e.target.value)}
        onKeyDown={(e) => { e.stopPropagation(); if (e.key === "Enter") go(build); }} />
      <button className="hud-btn" onClick={() => go(build)}>Go</button>
      {actions?.map((a) => <button key={a.label} className="hud-btn whitespace-nowrap" onClick={() => go(a.build)}>{a.label}</button>)}
    </div>
  );
}

/** Delegate to the JARVIS engine with a pre-filled instruction template. */
export function AskBox({ placeholder, template, button = "Ask JARVIS" }: { placeholder: string; template: (q: string) => string; button?: string }) {
  const [q, setQ] = useState("");
  const go = () => { if (q.trim()) { ask(template(q.trim())); setQ(""); } };
  return (
    <div className="flex gap-2">
      <input className="hud-input" placeholder={placeholder} value={q} onChange={(e) => setQ(e.target.value)}
        onKeyDown={(e) => { e.stopPropagation(); if (e.key === "Enter") go(); }} />
      <button className="hud-btn whitespace-nowrap" onClick={go}>{button}</button>
    </div>
  );
}

export function Prompts({ items }: { items: string[] }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((t) => <button key={t} className="rounded-full border border-cyan-300/20 px-3 py-1 text-xs text-cyan-100/80 hover:bg-cyan-400/10" onClick={() => ask(t)}>{t}</button>)}
    </div>
  );
}

/** Run a registered backend tool. It goes through the same policy, approval and audit path the agent uses. */
export async function runTool(tool: string, args: Record<string, any> = {}) {
  return request<{ text: string; is_error: boolean }>("run_tool", { tool, args });
}

export const Muted = ({ children }: { children: ReactNode }) => <div className="text-xs leading-relaxed text-cyan-100/50">{children}</div>;
export const ErrorText = ({ children }: { children: ReactNode }) => <div className="rounded border border-red-400/30 bg-red-500/10 p-2 text-xs text-red-200">{children}</div>;
