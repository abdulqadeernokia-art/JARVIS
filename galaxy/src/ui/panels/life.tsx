import { useEffect, useState } from "react";
import { request } from "../../lib/bridge";
import type { PlanetDef } from "../../lib/planets";
import { useJarvis } from "../../lib/store";
import { ErrorText, LinkGrid, Muted, Prompts, Section, runTool } from "./kit";

export function LifePanel({ planet }: { planet: PlanetDef }) {
  const mockCal = useJarvis((s) => s.mock.calendar);
  const [tasks, setTasks] = useState<any[]>([]);
  const [notes, setNotes] = useState<any[]>([]);
  const [cal, setCal] = useState("");
  const [title, setTitle] = useState("");
  const [due, setDue] = useState("");
  const [note, setNote] = useState({ title: "", body: "" });

  const loadTasks = () => request("tasks.list").then((r) => setTasks(r.items || []));
  const loadNotes = () => request("notes.list").then((r) => setNotes(r.items || []));
  const loadCal = async () => {
    const start = new Date(); const end = new Date(Date.now() + 2 * 864e5);
    const iso = (d: Date) => new Date(d.getTime() - d.getTimezoneOffset() * 6e4).toISOString().slice(0, 19);
    const r = await runTool("list_calendar_events", { start: iso(start), end: iso(end) });
    setCal(r.error || r.text.replace(/<\/?untrusted_content[^>]*>/g, "").trim());
  };
  useEffect(() => { loadTasks(); loadNotes(); loadCal(); }, []);

  return (
    <>
      <Section title="Next 48 hours" right={<button className="text-xs text-cyan-300/60 hover:text-cyan-200" onClick={loadCal}>refresh</button>}>
        {mockCal && <ErrorText>Calendar is in MOCK mode.</ErrorText>}
        <pre className="max-h-40 overflow-auto whitespace-pre-wrap text-xs text-cyan-100/80">{cal || "Loading…"}</pre>
      </Section>
      <Section title="Tasks & reminders">
        <div className="flex gap-2">
          <input className="hud-input" placeholder="New task…" value={title} onChange={(e) => setTitle(e.target.value)} onKeyDown={(e) => e.stopPropagation()} />
          <input className="hud-input !w-44" type="datetime-local" value={due} onChange={(e) => setDue(e.target.value)} onKeyDown={(e) => e.stopPropagation()} />
          <button className="hud-btn" disabled={!title.trim()} onClick={async () => { await request("tasks.create", { title, due: due || null }); setTitle(""); setDue(""); loadTasks(); }}>Add</button>
        </div>
        <div className="mt-2 space-y-1">
          {tasks.length === 0 && <Muted>No open tasks.</Muted>}
          {tasks.map((t) => (
            <div key={t.id} className="flex items-center gap-2 text-sm">
              <button className="h-4 w-4 rounded border border-cyan-300/40 hover:bg-cyan-300/30" title="Complete"
                onClick={async () => { await request("tasks.complete", { id: t.id }); loadTasks(); }} />
              <span className="flex-1 text-cyan-50">{t.title}</span>
              {t.due_at && <span className="text-xs text-cyan-300/50">{new Date(t.due_at * 1000).toLocaleString([], { dateStyle: "short", timeStyle: "short" })}</span>}
              {t.recurrence && <span className="text-[10px] text-cyan-300/50">↻ {t.recurrence}</span>}
            </div>
          ))}
        </div>
      </Section>
      <Section title="Notes">
        <input className="hud-input mb-2" placeholder="Title" value={note.title} onChange={(e) => setNote({ ...note, title: e.target.value })} onKeyDown={(e) => e.stopPropagation()} />
        <textarea className="hud-input h-20" placeholder="Note…" value={note.body} onChange={(e) => setNote({ ...note, body: e.target.value })} onKeyDown={(e) => e.stopPropagation()} />
        <button className="hud-btn mt-2" disabled={!note.body.trim()} onClick={async () => { await request("notes.create", note); setNote({ title: "", body: "" }); loadNotes(); }}>Save note</button>
        <div className="mt-3 space-y-1">
          {notes.map((n) => (
            <details key={n.id} className="rounded border border-cyan-300/10 p-2 text-sm">
              <summary className="flex cursor-pointer justify-between text-cyan-50"><span>{n.title}</span>
                <button className="text-xs text-red-300/60 hover:text-red-200" onClick={async (e) => { e.preventDefault(); await request("notes.delete", { id: n.id }); loadNotes(); }}>delete</button></summary>
              <pre className="mt-1 whitespace-pre-wrap text-xs text-cyan-100/70">{n.body}</pre>
            </details>
          ))}
        </div>
      </Section>
      <Section title="Planning"><Prompts items={["Plan my day", "What do I have scheduled tomorrow?", "Book an hour for deep work tomorrow afternoon", "Remind me in 20 minutes to stretch", "Every Friday at 5, summarize my week"]} /></Section>
      <Section title="Open"><LinkGrid links={planet.links!} /></Section>
    </>
  );
}
