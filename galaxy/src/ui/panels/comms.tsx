import { useState } from "react";
import { ask } from "../../lib/bridge";
import type { PlanetDef } from "../../lib/planets";
import { useJarvis } from "../../lib/store";
import { ErrorText, LinkGrid, Muted, Prompts, Section, runTool } from "./kit";

type Mail = { id: string; from: string; subject: string; date: string; snippet: string };

function parse(text: string): Mail[] {
  return text.split("\n").filter((l) => l.startsWith("id=")).map((l) => {
    const f = Object.fromEntries(l.split(" | ").map((kv) => { const i = kv.indexOf(kv.startsWith("id=") ? "=" : ":"); return [kv.slice(0, i).trim(), kv.slice(i + 1).trim()]; }));
    return { id: f.id, from: f.from, subject: f.subject, date: f.date, snippet: f.snippet };
  });
}

export function CommsPanel({ planet }: { planet: PlanetDef }) {
  const mock = useJarvis((s) => s.mock.email);
  const [query, setQuery] = useState("is:unread in:inbox");
  const [mails, setMails] = useState<Mail[] | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState({ to: "", subject: "", body: "" });
  const [draftMsg, setDraftMsg] = useState("");

  const search = async () => {
    setBusy(true); setErr("");
    const r = await runTool("search_email", { query, max_results: 15 });
    setBusy(false);
    if (r.error || r.is_error) return setErr(r.error || r.text);
    setMails(parse(r.text));
  };
  const saveDraft = async () => {
    const r = await runTool("draft_email", draft);
    setDraftMsg(r.error || r.text);
  };

  return (
    <>
      {mock && <ErrorText>Email is in MOCK mode (JARVIS_MOCK_EMAIL=1). Messages below are test data.</ErrorText>}
      <Section title="Inbox">
        <div className="flex gap-2">
          <input className="hud-input" value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => { e.stopPropagation(); e.key === "Enter" && search(); }} />
          <button className="hud-btn" onClick={search} disabled={busy}>{busy ? "…" : "Fetch"}</button>
        </div>
        {err && <div className="mt-2"><ErrorText>{err}</ErrorText><Muted>Gmail needs credentials.json (OAuth Desktop client) in the jarvis folder; first use opens a Google sign-in.</Muted></div>}
        <div className="mt-2 space-y-1.5">
          {mails?.length === 0 && <Muted>No messages match.</Muted>}
          {mails?.map((m) => (
            <div key={m.id} className="rounded border border-cyan-300/10 p-2 text-xs">
              <div className="flex justify-between text-cyan-200"><span className="truncate">{m.from}</span><span className="shrink-0 text-cyan-300/40">{m.date?.slice(0, 16)}</span></div>
              <div className="text-sm text-cyan-50">{m.subject}</div>
              <div className="truncate text-cyan-100/50">{m.snippet}</div>
              <div className="mt-1 flex gap-2">
                <button className="text-cyan-300/80 hover:text-cyan-100" onClick={() => ask(`Read email ${m.id} and summarise it for me.`)}>Summarise</button>
                <button className="text-cyan-300/80 hover:text-cyan-100" onClick={() => ask(`Prepare a reply draft to email ${m.id}. Don't send it.`)}>Draft reply</button>
              </div>
            </div>
          ))}
        </div>
      </Section>
      <Section title="Compose (creates a draft, never sends)">
        <div className="space-y-2">
          {(["to", "subject"] as const).map((k) => (
            <input key={k} className="hud-input" placeholder={k} value={draft[k]} onChange={(e) => setDraft({ ...draft, [k]: e.target.value })} onKeyDown={(e) => e.stopPropagation()} />
          ))}
          <textarea className="hud-input h-28" placeholder="body" value={draft.body} onChange={(e) => setDraft({ ...draft, body: e.target.value })} onKeyDown={(e) => e.stopPropagation()} />
          <div className="flex items-center gap-2">
            <button className="hud-btn" disabled={!draft.to || !draft.subject} onClick={saveDraft}>Save draft</button>
            <Muted>To send, ask JARVIS: "send it". Sending always shows an approval card first.</Muted>
          </div>
          {draftMsg && <div className="text-xs text-cyan-100/70">{draftMsg}</div>}
        </div>
      </Section>
      <Section title="Ask JARVIS"><Prompts items={["Which emails need my attention?", "Summarise today's unread email", "Draft a polite follow-up to my last sent email"]} /></Section>
      <Section title="Open"><LinkGrid links={planet.links!} /></Section>
    </>
  );
}
