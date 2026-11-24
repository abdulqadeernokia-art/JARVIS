// WebSocket link to the Python core (jarvis_os/bridge/server.py). One shared connection, auto-reconnect.
import { useJarvis } from "./store";

type Reply = Record<string, any>;
let ws: WebSocket | null = null;
let rid = 0;
const pending = new Map<number, (r: Reply) => void>();
export const levels = { mic: 0, speech: 0 }; // read every frame by the 3D core (no React re-render)

const token = new URLSearchParams(location.search).get("token") || sessionStorage.getItem("jarvis-token") || "";
if (token) sessionStorage.setItem("jarvis-token", token);

export function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws?token=${encodeURIComponent(token)}`);
  ws.onopen = () => useJarvis.getState().setConnected(true);
  ws.onclose = () => {
    useJarvis.getState().setConnected(false);
    pending.forEach((cb) => cb({ error: "Disconnected from the JARVIS core." }));
    pending.clear();
    setTimeout(connect, 1500);
  };
  ws.onmessage = (m) => {
    const msg = JSON.parse(m.data);
    if (msg.type === "levels") {
      levels.mic = msg.mic;
      levels.speech = msg.speech;
    } else if (msg.type === "reply") {
      pending.get(msg.rid)?.(msg);
      pending.delete(msg.rid);
    } else if (msg.type === "snapshot") {
      useJarvis.getState().applySnapshot(msg);
    } else if (msg.type === "event") {
      useJarvis.getState().onEvent(msg.event, msg.data);
    }
  };
}

/** Fire-and-forget command. */
export function send(type: string, payload: Record<string, any> = {}) {
  if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type, ...payload }));
  else useJarvis.getState().notify("Not connected to the JARVIS core.", "error");
}

/** Command with a reply. */
export function request<T = Reply>(type: string, payload: Record<string, any> = {}): Promise<T & Reply> {
  return new Promise((resolve) => {
    if (ws?.readyState !== WebSocket.OPEN) return resolve({ error: "Not connected to the JARVIS core." } as any);
    const id = ++rid;
    pending.set(id, resolve as any);
    ws.send(JSON.stringify({ type, rid: id, ...payload }));
  });
}

export function openUrl(url: string) {
  return request("open_url", { url }).then((r) => {
    if (r.error) useJarvis.getState().notify(r.error, "error");
    else useJarvis.getState().activity("Opened " + new URL(url).hostname);
    return r;
  });
}

/** Hand a request to the JARVIS intelligence engine (same path as speaking to him). */
export const ask = (text: string) => send("text", { text });
