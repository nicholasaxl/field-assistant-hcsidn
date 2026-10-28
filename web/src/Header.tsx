import { AnimatePresence, motion } from "motion/react";
import { Arcs } from "./Arcs";
import { InsightsIcon, LibraryIcon, Moon, SourcesIcon, Sun } from "./Icons";
import type { Health, ModelsInfo } from "./types";

type Props = {
  theme: "light" | "dark";
  onTheme: () => void;
  health: Health | null;
  models: ModelsInfo | null;
  modelOpen: boolean;
  onModel: () => void;
  docCount: number | null;
  libraryOpen: boolean;
  onLibrary: () => void;
  insightsOpen: boolean;
  onInsights: () => void;
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

/** What the pill says: where the answer-writing model runs, and which one it is. Problems take priority. */
function modelPill(health: Health | null, models: ModelsInfo | null) {
  const h = healthView(health);
  const active = models?.active;
  if (h.state === "offline" || h.state === "partial") return { ...h, kind: "Problem", name: h.text, local: true };
  if (!active) return { ...h, kind: "", name: h.text, local: true };
  const title = active.local
    ? `${active.label} writes the answers on this computer. Search uses ${models?.search.model}, also on this computer.`
    : `${active.label} writes the answers on ${active.where.replace(/ \(online\)$/, "")}, over the internet. Questions and the document passages found for them are sent there. Search stays on this computer.`;
  return { state: h.state, title, kind: active.local ? "Local" : "Online", name: active.label, local: active.local };
}

export function Header(p: Props) {
  const pill = modelPill(p.health, p.models);
  return (
    <header className="app-header">
      <div className="brand">
        <span className="brand-mark">
          <Arcs count={3} size={18} strokeWidth={11} />
        </span>
        <span className="brand-name">Field Assist</span>
      </div>

      <div className="header-actions">
        <button
          className="model-pill"
          data-state={pill.state}
          data-local={pill.local}
          aria-expanded={p.modelOpen}
          onClick={p.onModel}
          title={pill.title}
          aria-label={`Model: ${pill.kind} ${pill.name}. Open model settings`}
        >
          <span className="health-dot" />
          {pill.kind && <span className="model-kind">{pill.kind}</span>}
          <span className="model-name">{pill.name}</span>
        </button>

        <button className="pill-btn" aria-expanded={p.libraryOpen} onClick={p.onLibrary} aria-label="Open library">
          <LibraryIcon />
          <span className="btn-label">Library</span>
          <span className="count">{p.docCount ?? "…"}</span>
        </button>

        <button className="pill-btn" aria-pressed={p.insightsOpen} onClick={p.onInsights} aria-label="Open insights">
          <InsightsIcon />
          <span className="btn-label">Insights</span>
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
