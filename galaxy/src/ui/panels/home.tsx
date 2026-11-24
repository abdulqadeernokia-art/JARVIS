import { useEffect, useState } from "react";
import { request } from "../../lib/bridge";
import { useJarvis } from "../../lib/store";
import { ErrorText, Muted, Section } from "./kit";

const TOGGLE = new Set(["light", "switch", "fan", "input_boolean", "media_player"]);

export function HomePanel() {
  const url = useJarvis((s) => s.settings.home_assistant_url);
  const [form, setForm] = useState({ url: url || "", token: "" });
  const [items, setItems] = useState<any[] | null>(null);
  const [err, setErr] = useState("");
  const [hasToken, setHasToken] = useState(false);

  const load = async () => {
    setErr("");
    const r = await request("ha.states");
    if (r.error) { setErr(r.error); setItems(null); } else setItems(r.items);
  };
  useEffect(() => {
    request("secrets.status").then((r) => { setHasToken(!!r.status?.HOME_ASSISTANT_TOKEN); if (url && r.status?.HOME_ASSISTANT_TOKEN) load(); });
  }, []);

  const save = async () => {
    await request("settings.update", { values: { home_assistant_url: form.url.trim() } });
    if (form.token) { await request("secrets.set", { name: "HOME_ASSISTANT_TOKEN", value: form.token }); setHasToken(true); }
    setForm({ ...form, token: "" });
    const p = await request("ha.ping");
    if (p.error) setErr(p.error); else load();
  };
  const call = async (e: any, service: string) => {
    let r = await request("ha.call", { entity_id: e.entity_id, service });
    if (r.needs_confirm && confirm(`Really ${service.replace("_", " ")} ${e.name}?`)) r = await request("ha.call", { entity_id: e.entity_id, service, confirmed: true });
    if (r.error) setErr(r.error); else setTimeout(load, 400);
  };

  const groups = (items || []).reduce((m: Record<string, any[]>, e) => ((m[e.domain] ||= []).push(e), m), {});
  return (
    <>
      <Section title="Home Assistant connection">
        <div className="space-y-2">
          <input className="hud-input" placeholder="http://homeassistant.local:8123" value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} onKeyDown={(e) => e.stopPropagation()} />
          <input className="hud-input" type="password" placeholder={hasToken ? "Token stored (encrypted). Paste to replace." : "Long-lived access token"} value={form.token}
            onChange={(e) => setForm({ ...form, token: e.target.value })} onKeyDown={(e) => e.stopPropagation()} />
          <div className="flex gap-2"><button className="hud-btn" onClick={save} disabled={!form.url}>Connect</button>{items && <button className="hud-btn" onClick={load}>Refresh</button>}</div>
          <Muted>Needs a running Home Assistant (free, home-assistant.io). Create a token under Profile → Security → Long-lived access tokens. The token is encrypted with Windows DPAPI and never shown again.</Muted>
        </div>
        {err && <div className="mt-2"><ErrorText>{err}</ErrorText></div>}
      </Section>
      {items && Object.entries(groups).sort().map(([domain, list]) => (
        <Section key={domain} title={domain.replace("_", " ")}>
          <div className="grid grid-cols-2 gap-2">
            {list.slice(0, 40).map((e) => (
              <div key={e.entity_id} className="tile !cursor-default">
                <span className="truncate text-cyan-50">{e.name}</span>
                <span className={`text-xs ${e.state === "on" || e.state === "open" || e.state === "unlocked" ? "text-amber-200" : "text-cyan-300/60"}`}>{e.state}{e.unit ? " " + e.unit : ""}</span>
                <div className="mt-1 flex gap-1">
                  {TOGGLE.has(e.domain) && <button className="hud-btn !px-2 !py-0.5" onClick={() => call(e, "toggle")}>Toggle</button>}
                  {(e.domain === "scene" || e.domain === "script") && <button className="hud-btn !px-2 !py-0.5" onClick={() => call(e, "turn_on")}>Run</button>}
                  {e.domain === "cover" && <><button className="hud-btn !px-2 !py-0.5" onClick={() => call(e, "open_cover")}>Open</button><button className="hud-btn !px-2 !py-0.5" onClick={() => call(e, "close_cover")}>Close</button></>}
                  {e.domain === "lock" && <><button className="hud-btn !px-2 !py-0.5" onClick={() => call(e, "lock")}>Lock</button><button className="hud-btn danger !px-2 !py-0.5" onClick={() => call(e, "unlock")}>Unlock</button></>}
                </div>
              </div>
            ))}
          </div>
        </Section>
      ))}
    </>
  );
}
