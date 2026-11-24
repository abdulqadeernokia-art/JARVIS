export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: { extend: { fontFamily: { hud: ["Rajdhani", "Segoe UI", "sans-serif"], mono: ["Consolas", "monospace"] },
    colors: { hud: { DEFAULT: "#7fe7ff", dim: "#3b8fb0", deep: "#06111c" } } } },
};
