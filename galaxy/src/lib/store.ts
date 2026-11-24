import { create } from "zustand";

export type CoreState = "idle" | "listening" | "thinking" | "speaking" | "executing" | "error" | "privacy" | "approval";
export type Msg = { id: number; who: "you" | "jarvis" | "system"; text: string; ts: number };
export type Note = { id: number; text: string; kind: "info" | "error" | "ok"; ts: number };
export type Approval = { id: number; tool: string; summary: string; preview: string } | null;
export type TaskRow = { id: number; tool: string; summary: string; status: string; ts: number };

let nid = 0;

type S = {
  connected: boolean;
  state: CoreState;
  partial: string;
  messages: Msg[];
  notes: Note[];
  tasks: TaskRow[];
  approval: Approval;
  settings: Record<string, any>;
  voices: string[];
  tools: string[];
  privacy: boolean;
  conversation: boolean; // hands-free conversation mode running
  memoryEnabled: boolean;
  hasMic: boolean;
  mock: { email: boolean; calendar: boolean };
  focus: string | null; // planet the camera travels to
  hover: string | null;
  panelOpen: boolean;
  overlay: null | "memory" | "settings";
  setConnected(v: boolean): void;
  applySnapshot(s: any): void;
  onEvent(type: string, d: any): void;
  notify(text: string, kind?: Note["kind"]): void;
  activity(text: string): void;
  say(who: Msg["who"], text: string): void;
  setFocus(id: string | null): void;
  setHover(id: string | null): void;
  clearChat(): void;
  set(p: Partial<S>): void;
};

let errorTimer: any;

export const useJarvis = create<S>((set, get) => ({
  connected: false,
  state: "idle",
  partial: "",
  messages: [],
  notes: [],
  tasks: [],
  approval: null,
  settings: {},
  voices: [],
  tools: [],
  privacy: false,
  conversation: false,
  memoryEnabled: true,
  hasMic: false,
  mock: { email: false, calendar: false },
  focus: null,
  hover: null,
  panelOpen: false,
  overlay: null,
  set: (p) => set(p),
  setConnected: (v) => set(v ? { connected: true, state: "idle" } : { connected: false, state: "error" }),
  applySnapshot: (s) =>
    set({
      settings: s.settings, voices: s.voices, tools: s.tools, privacy: s.privacy,
      state: s.privacy ? "privacy" : "idle", memoryEnabled: s.memory_enabled, hasMic: s.has_mic, mock: s.mock,
    }),
  notify: (text, kind = "info") =>
    set((st) => ({ notes: [{ id: ++nid, text, kind, ts: Date.now() }, ...st.notes].slice(0, 40) })),
  activity: (text) => get().notify(text, "ok"),
  say: (who, text) => set((st) => ({ messages: [...st.messages, { id: ++nid, who, text, ts: Date.now() }].slice(-200) })),
  setFocus: (id) => set({ focus: id, panelOpen: false, hover: null }),
  setHover: (id) => set({ hover: id }),
  clearChat: () => set({ messages: [], partial: "" }),
  onEvent: (t, d) => {
    const st = get();
    const setState = (s: CoreState) => {
      if (get().state !== "privacy" || s === "idle") set({ state: s });
    };
    switch (t) {
      case "voice.state": {
        const map: Record<string, CoreState> = {
          idle: "idle", listening: "listening", transcribing: "thinking", privacy: "privacy",
          dictating: "listening", meeting: "listening",
        };
        if (map[d.state] && !(d.state === "idle" && ["speaking", "executing"].includes(get().state))) setState(map[d.state]);
        break;
      }
      case "voice.transcript":
        if (d.partial) set({ partial: d.text });
        else { set({ partial: "" }); st.say("you", d.text); }
        break;
      case "agent.started":
      case "agent.thinking":
        setState("thinking");
        break;
      case "speaker":
        if (d.speaking) { setState("speaking"); if (d.text) st.say("jarvis", d.text); }
        else if (get().state === "speaking") setState("idle");
        break;
      case "tool.started":
        setState("executing");
        set((s) => ({ tasks: [{ id: ++nid, tool: d.tool, summary: d.summary || "", status: "running", ts: Date.now() }, ...s.tasks].slice(0, 30) }));
        break;
      case "tool.finished": {
        const idx = get().tasks.findIndex((y) => y.tool === d.tool && y.status === "running");
        set((s) => ({ tasks: s.tasks.map((x, i) => (i === idx ? { ...x, status: d.status } : x)) }));
        if (d.status !== "ok") st.notify(`${d.tool}: ${d.status}`, "error");
        setState("thinking");
        break;
      }
      case "approval.requested":
        set({ approval: { id: d.id, tool: d.tool, summary: d.summary, preview: d.preview }, state: "approval" });
        break;
      case "approval.resolved":
        set({ approval: null });
        setState("thinking");
        st.notify(`Approval ${d.decision} (${d.by})`, d.decision === "approved" ? "ok" : "info");
        break;
      case "agent.completed":
      case "agent.cancelled":
        if (!["speaking", "privacy"].includes(get().state)) setState("idle");
        break;
      case "agent.failed":
        set({ state: "error" });
        st.notify(String(d.output || "Request failed").slice(0, 200), "error");
        clearTimeout(errorTimer);
        errorTimer = setTimeout(() => get().state === "error" && set({ state: "idle" }), 3500);
        break;
      case "notify":
        st.notify(d.text || "", "info");
        break;
      case "conversation":
        set({ conversation: !!d.on });
        st.notify(d.on ? "Conversation mode on. Say \"stop conversation\" to end." : "Conversation mode off.", "ok");
        break;
      case "privacy.changed":
        set({ privacy: d.on, state: d.on ? "privacy" : "idle" });
        break;
      case "task.created":
        st.notify(`Task created: ${d.title}`, "ok");
        break;
      case "settings.changed":
        set((s) => ({ settings: { ...s.settings, ...d } }));
        break;
      case "meeting.segment":
        st.say("system", `[${d.clock}] ${d.text}`);
        break;
    }
  },
}));
