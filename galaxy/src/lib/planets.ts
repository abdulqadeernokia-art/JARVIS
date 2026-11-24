// Planet registry. To add a planet: append an entry here and (optionally) a panel in src/ui/panels/.
// `panel` names a lazily loaded component in src/ui/panels/index.ts; `links` are real destinations.

export type PlanetLink = { label: string; url: string; hint?: string };
export type PlanetDef = {
  id: string;
  name: string;
  description: string;
  position: [number, number, number];
  radius: number;
  colors: [string, string, string]; // base, accent, atmosphere
  surface: "gas" | "rocky" | "ocean" | "ice" | "lava" | "tech";
  ring?: boolean;
  panel: string;
  links?: PlanetLink[];
  shortcut: string; // keyboard key (1-9)
};

export const PLANETS: PlanetDef[] = [
  {
    id: "google", name: "Google", shortcut: "1", panel: "google", surface: "ocean", radius: 1.25,
    description: "Search, Maps, Drive, Docs and every Google service.",
    position: [-11, 1.5, -4], colors: ["#1b4fbf", "#3fb06a", "#8ec5ff"],
    links: [
      { label: "Google", url: "https://www.google.com" },
      { label: "Maps", url: "https://maps.google.com" },
      { label: "Drive", url: "https://drive.google.com" },
      { label: "Docs", url: "https://docs.google.com" },
      { label: "Sheets", url: "https://sheets.google.com" },
      { label: "Calendar", url: "https://calendar.google.com" },
      { label: "Photos", url: "https://photos.google.com" },
      { label: "Translate", url: "https://translate.google.com" },
    ],
  },
  {
    id: "youtube", name: "YouTube", shortcut: "2", panel: "youtube", surface: "lava", radius: 1.05,
    description: "Search videos and channels, browse and play.",
    position: [-7, -2.8, 6], colors: ["#7a0d10", "#ff3b2f", "#ff9a7a"],
    links: [
      { label: "Home", url: "https://www.youtube.com" },
      { label: "Subscriptions", url: "https://www.youtube.com/feed/subscriptions" },
      { label: "History", url: "https://www.youtube.com/feed/history" },
      { label: "Watch later", url: "https://www.youtube.com/playlist?list=WL" },
    ],
  },
  {
    id: "comms", name: "Communication", shortcut: "3", panel: "comms", surface: "ice", radius: 1.0,
    description: "Gmail: read, triage, draft and reply. Sending always asks you first.",
    position: [3, 3.4, 10], colors: ["#d7e6f5", "#6aa8ff", "#cfe8ff"],
    links: [{ label: "Gmail", url: "https://mail.google.com" }, { label: "Contacts", url: "https://contacts.google.com" }],
  },
  {
    id: "ai", name: "Artificial Intelligence", shortcut: "4", panel: "ai", surface: "tech", radius: 1.35, ring: true,
    description: "Claude, ChatGPT and other AI tools, plus JARVIS's own engine.",
    position: [11, 0.5, 4], colors: ["#2a1a5e", "#9b7bff", "#c7b8ff"],
    links: [
      { label: "Claude", url: "https://claude.ai" },
      { label: "ChatGPT", url: "https://chatgpt.com" },
      { label: "Gemini", url: "https://gemini.google.com" },
      { label: "Perplexity", url: "https://www.perplexity.ai" },
      { label: "Hugging Face", url: "https://huggingface.co" },
      { label: "Anthropic Console", url: "https://console.anthropic.com" },
    ],
  },
  {
    id: "computer", name: "Computer System", shortcut: "5", panel: "computer", surface: "rocky", radius: 1.15,
    description: "Files, folders, apps, terminal, system information.",
    position: [8, -3, -8], colors: ["#5a4632", "#c8a46a", "#ffd9a0"],
  },
  {
    id: "research", name: "Research", shortcut: "6", panel: "research", surface: "gas", radius: 1.5, ring: true,
    description: "Web research, reports, comparisons, news, source verification.",
    position: [-2, 5.5, -13], colors: ["#7a5a2a", "#e8c27a", "#ffe6b0"],
    links: [
      { label: "Google News", url: "https://news.google.com" },
      { label: "Google Scholar", url: "https://scholar.google.com" },
      { label: "Wikipedia", url: "https://en.wikipedia.org" },
      { label: "arXiv", url: "https://arxiv.org" },
    ],
  },
  {
    id: "life", name: "Personal Life", shortcut: "7", panel: "life", surface: "ocean", radius: 1.0,
    description: "Calendar, tasks, reminders, notes and daily planning.",
    position: [-13, -1, 9], colors: ["#0f5a4a", "#4fe0b0", "#a8ffe0"],
    links: [{ label: "Google Calendar", url: "https://calendar.google.com" }, { label: "Google Keep", url: "https://keep.google.com" }],
  },
  {
    id: "home", name: "Smart Home", shortcut: "8", panel: "home", surface: "tech", radius: 0.9,
    description: "Home Assistant: lights, climate, scenes and devices.",
    position: [13, 3.5, -6], colors: ["#0e3b46", "#3fd0e0", "#9ff4ff"],
  },
  {
    id: "settings", name: "Settings & Systems", shortcut: "9", panel: "settings", surface: "ice", radius: 0.8, ring: true,
    description: "Voice, personality, permissions, memory, API keys, diagnostics.",
    position: [1, -4.5, -10], colors: ["#3a4656", "#a9c4e0", "#e6f2ff"],
  },
];

export const planetById = (id: string | null) => PLANETS.find((p) => p.id === id) || null;
