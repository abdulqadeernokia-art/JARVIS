import { useEffect } from "react";
import { send } from "../lib/bridge";
import { PLANETS } from "../lib/planets";
import { useJarvis } from "../lib/store";
import { toggleFullscreen } from "./TopBar";

/**
 * 1-9 fly to a planet · Esc interrupts if busy, else returns to the galaxy · H home view · F full screen
 * / focuses the message box · Ctrl+Space talks · Ctrl+Shift+X emergency stop
 */
export function useShortcuts() {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = (e.target as HTMLElement)?.closest?.("input, textarea, select");
      const st = useJarvis.getState();
      if (e.ctrlKey && e.shiftKey && e.key.toLowerCase() === "x") { e.preventDefault(); send("emergency_stop"); return; }
      if (e.ctrlKey && e.code === "Space") { e.preventDefault(); send("wake"); return; }
      if (e.key === "Escape") {
        if (["speaking", "thinking", "executing"].includes(st.state)) send("interrupt");
        else if (st.focus) st.setFocus(null);
        return;
      }
      if (typing || e.ctrlKey || e.altKey || e.metaKey) return;
      const p = PLANETS.find((x) => x.shortcut === e.key);
      if (p) st.setFocus(p.id);
      else if (e.key === "h") st.setFocus(null);
      else if (e.key === "f") toggleFullscreen();
      else if (e.key === "/") { e.preventDefault(); dispatchEvent(new Event("jarvis:focus-input")); }
    };
    addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
  }, []);
}
