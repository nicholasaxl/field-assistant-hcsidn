import { AnimatePresence, motion } from "motion/react";
import { useEffect, useState } from "react";
import { Arcs } from "./Arcs";
import { Check, Chevron } from "./Icons";
import type { Stage } from "./types";

const NEXT_LABEL: Record<string, string> = {
  classify: "Searching the manuals",
  lookup_code: "Searching the manuals",
  retrieve: "Checking relevance",
  rewrite: "Searching the manuals",
  generate: "Verifying sources",
  format_citations: "Safety check",
};

/** What the agent is doing right now, inferred from the last stage that finished. */
function pendingLabel(stages: Stage[]): string {
  const last = stages[stages.length - 1];
  if (!last) return "Reading the question";
  if (last.node === "grade") {
    return /^Nothing/.test(last.detail) ? "Rephrasing the search" : "Writing the answer";
  }
  return NEXT_LABEL[last.node] ?? "Working";
}

type Props = { stages: Stage[]; running: boolean; elapsed?: number };

export function Timeline({ stages, running, elapsed }: Props) {
  const [open, setOpen] = useState(true);

  // Open while the agent works, tuck away once the answer lands.
  useEffect(() => {
    setOpen(running);
  }, [running]);

  const title = running
    ? pendingLabel(stages)
    : `Worked through ${stages.length} step${stages.length === 1 ? "" : "s"}${elapsed !== undefined ? ` in ${elapsed} s` : ""}`;

  return (
    <div className="timeline">
      <button className="timeline-head" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <span className="timeline-lead">{running ? <Arcs count={3} size={22} strokeWidth={11} active /> : <Check />}</span>
        <span className="timeline-title" aria-live="polite">
          {title}
        </span>
        <Chevron className="timeline-chev" />
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.ol
            className="timeline-list"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.32, ease: [0.22, 1, 0.36, 1] }}
          >
            {stages.map((stage, i) => (
              <motion.li
                key={`${stage.node}-${i}`}
                className="timeline-item"
                initial={{ opacity: 0, x: -8 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.3 }}
              >
                <span className="tl-dot">
                  <Check />
                </span>
                <span className="tl-label">{stage.label}</span>
                <span className="tl-time">{stage.at} s</span>
                {stage.detail && <span className="tl-detail">{stage.detail}</span>}
              </motion.li>
            ))}
            {running && (
              <li className="timeline-item" data-pending="true">
                <span className="tl-dot" style={{ color: "var(--accent)" }}>
                  <Arcs count={3} size={20} strokeWidth={11} active />
                </span>
                <span className="tl-label">{pendingLabel(stages)}</span>
              </li>
            )}
          </motion.ol>
        )}
      </AnimatePresence>
    </div>
  );
}
