import { useEffect, useState } from "react";
import { request } from "../../lib/bridge";
import { useJarvis } from "../../lib/store";
import { ErrorText, Muted, Prompts, Section, runTool } from "./kit";

const gb = (b: number) => (b / 1024 ** 3).toFixed(1) + " GB";
const size = (b: number) => (b > 1024 ** 3 ? gb(b) : b > 1024 ** 2 ? (b / 1024 ** 2).toFixed(1) + " MB" : (b / 1024).toFixed(0) + " KB");
const APPS = [["Explorer", "explorer"], ["Terminal", "wt"], ["VS Code", "code"], ["Notepad", "notepad"], ["Calculator", "calc"], ["Browser", "msedge"], ["Settings", "ms-settings:"], ["Task Mgr", "taskmgr"]];

export function ComputerPanel() {
  const [dir, setDir] = useState<any>(null);
  const [info, setInfo] = useState<any>(null);
  const [msg, setMsg] = useState("");
  const [shot, setShot] = useState("");
  const notify = useJarvis((s) => s.notify);

  const open = (path: string) => request("files.list", { path }).then(setDir);
  useEffect(() => { open(""); request("sysinfo").then(setInfo); }, []);

  const launch = async (name: string) => {
    const r = await runTool("open_application", { name });
    setMsg(r.error || r.text);
  };

  return (
    <>
      <Section title="Applications">
        <div className="grid grid-cols-4 gap-2">
          {APPS.map(([l, n]) => <button key={n} className="tile !items-center !p-2 text-xs" onClick={() => launch(n)}>{l}</button>)}
        </div>
        {msg && <div className="mt-2 text-xs text-cyan-100/60">{msg}</div>}
      </Section>
      <Section title="Files" right={dir?.path ? <button className="text-xs text-cyan-300/70 hover:text-cyan-100" onClick={() => open(dir.parent || "")}>▲ up</button> : null}>
        <div className="mb-2 flex flex-wrap gap-1.5">
          {dir?.roots?.map((r: any) => <button key={r.path} className={`hud-btn !px-2 !py-1 !text-[10px] ${dir?.path?.startsWith(r.path) ? "on" : ""}`} onClick={() => open(r.path)}>{r.name}</button>)}
        </div>
        {dir?.error && <ErrorText>{dir.error}</ErrorText>}
        {dir?.path && <div className="mb-1 truncate font-mono text-[10px] text-cyan-300/50">{dir.path}</div>}
        <div className="max-h-64 overflow-y-auto rounded border border-cyan-300/10">
          {dir?.path && dir.items?.length === 0 && <div className="p-2"><Muted>Empty folder.</Muted></div>}
          {dir?.path && dir.items?.map((f: any) => (
            <button key={f.path} className="flex w-full items-center gap-2 px-2 py-1 text-left text-xs hover:bg-cyan-400/10"
              onDoubleClick={async () => { if (f.dir) open(f.path); else { const r = await request("files.open", { path: f.path }); if (r.error) notify(r.error, "error"); } }}>
              <span>{f.dir ? "📁" : "📄"}</span><span className="flex-1 truncate text-cyan-50">{f.name}</span>
              {!f.dir && <span className="text-cyan-300/40">{size(f.size)}</span>}
            </button>
          ))}
        </div>
        <div className="mt-1"><Muted>Double-click to open. Only your allowed folders are visible (Settings → file roots).</Muted></div>
      </Section>
      <Section title="Automation">
        <Prompts items={["Organize my Downloads folder", "Find PDFs I downloaded this week", "Open my coding environment", "Close all Notepad windows", "Take a screenshot and tell me what you see"]} />
      </Section>
      <Section title="Screen">
        <button className="hud-btn" onClick={async () => { const r = await runTool("list_windows"); setShot(r.error || r.text); }}>List open windows</button>
        {shot && <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap text-[11px] text-cyan-100/70">{shot}</pre>}
      </Section>
      <Section title="System" right={<button className="text-xs text-cyan-300/60 hover:text-cyan-200" onClick={() => request("sysinfo").then(setInfo)}>refresh</button>}>
        {info && (
          <div className="space-y-1 text-xs text-cyan-100/80">
            <div>{info.os} · {info.machine} · {info.cores} cores</div>
            <div className="truncate text-cyan-100/50">{info.cpu}</div>
            {info.memory && <Bar label={`RAM ${gb(info.memory.total - info.memory.free)} / ${gb(info.memory.total)}`} v={info.memory.load / 100} />}
            {info.disks.map((d: any) => <Bar key={d.drive} label={`${d.drive} ${gb(d.total - d.free)} / ${gb(d.total)}`} v={1 - d.free / d.total} />)}
            <div className="text-cyan-100/50">JARVIS: {info.metrics.runs} requests · {info.metrics.tool_calls} tool calls · {info.metrics.tool_errors} errors</div>
          </div>
        )}
      </Section>
    </>
  );
}

function Bar({ label, v }: { label: string; v: number }) {
  return (
    <div>
      <div className="flex justify-between"><span>{label}</span><span>{Math.round(v * 100)}%</span></div>
      <div className="h-1 rounded bg-cyan-300/10"><div className={`h-1 rounded ${v > 0.9 ? "bg-red-400" : "bg-cyan-300"}`} style={{ width: `${v * 100}%` }} /></div>
    </div>
  );
}
