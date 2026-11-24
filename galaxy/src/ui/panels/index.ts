// Lazily loaded planet modules. Register a new planet's panel here (key = PlanetDef.panel).
import { lazy, type ComponentType } from "react";
import type { PlanetDef } from "../../lib/planets";

type P = ComponentType<{ planet: PlanetDef }>;
const web = () => import("./web");

export const PANELS: Record<string, P> = {
  google: lazy(() => web().then((m) => ({ default: m.GooglePanel }))),
  youtube: lazy(() => web().then((m) => ({ default: m.YouTubePanel }))),
  ai: lazy(() => web().then((m) => ({ default: m.AIPanel }))),
  research: lazy(() => web().then((m) => ({ default: m.ResearchPanel }))),
  comms: lazy(() => import("./comms").then((m) => ({ default: m.CommsPanel }))),
  computer: lazy(() => import("./computer").then((m) => ({ default: m.ComputerPanel }))),
  life: lazy(() => import("./life").then((m) => ({ default: m.LifePanel }))),
  home: lazy(() => import("./home").then((m) => ({ default: m.HomePanel }))),
  settings: lazy(() => import("./settings").then((m) => ({ default: m.SettingsPanel }))),
};
