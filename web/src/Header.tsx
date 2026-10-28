import { AnimatePresence, motion } from "motion/react";
import { Arcs } from "./Arcs";
import { LibraryIcon, Moon, SourcesIcon, Sun } from "./Icons";
import type { Health } from "./types";

type Props = {
  theme: "light" | "dark";
  onTheme: () => void;
  health: Health | null;
  docCount: number;
  libraryOpen: boolean;
  onLibrary: () => void;
  sourcesAvailable: boolean;
  sourcesOpen: boolean;
  onSources: () => void;
};

function healthView(health: Health | null) {
  if (!health) return { state: "checking", text: "Checking model", title: "Checking the local model" };
  if (!health.ollama)
    return { state: "offline", text: "Ollama offline", title: "Can't reach Ollama. Start it, then ask again." };
  if (!health.ready)
    return {
      state: "partial",
      text: "Models missing",
      title: `Run: ollama pull ${health.chat_model} and ollama pull ${health.embed_model}`,
    };
  return { state: "ready", text: "Model ready", title: `${health.chat_model} with ${health.embed_model}, running locally` };
}

export function Header(p: Props) {
  const h = healthView(p.health);
  return (
    <header className="app-header">
      <div className="brand">
        <span className="brand-mark">
          <Arcs count={3} size={22} strokeWidth={11} />
        </span>
        <span className="brand-name">Field Assist</span>
      </div>

      <div className="header-actions">
        <span className="health" data-state={h.state} title={h.title} role="status">
          <span className="health-dot" />
          <span className="health-text">{h.text}</span>
        </span>

        <button className="pill-btn" aria-expanded={p.libraryOpen} onClick={p.onLibrary} aria-label="Open library">
          <LibraryIcon />
          <span className="btn-label">Library</span>
          <span className="count">{p.docCount}</span>
        </button>

        <AnimatePresence initial={false}>
          {p.sourcesAvailable && (
            <motion.button
              key="sources"
              className="pill-btn"
              aria-pressed={p.sourcesOpen}
              onClick={p.onSources}
              aria-label="Toggle sources"
              initial={{ opacity: 0, scale: 0.9 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.9 }}
              transition={{ duration: 0.2 }}
            >
              <SourcesIcon />
              <span className="btn-label">Sources</span>
            </motion.button>
          )}
        </AnimatePresence>

        <button
          className="icon-btn"
          onClick={p.onTheme}
          aria-label={p.theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
        >
          <AnimatePresence mode="wait" initial={false}>
            <motion.span
              key={p.theme}
              style={{ display: "grid" }}
              initial={{ rotate: -50, opacity: 0, scale: 0.7 }}
              animate={{ rotate: 0, opacity: 1, scale: 1 }}
              exit={{ rotate: 50, opacity: 0, scale: 0.7 }}
              transition={{ duration: 0.18 }}
            >
              {p.theme === "dark" ? <Sun /> : <Moon />}
            </motion.span>
          </AnimatePresence>
        </button>
      </div>
    </header>
  );
}
