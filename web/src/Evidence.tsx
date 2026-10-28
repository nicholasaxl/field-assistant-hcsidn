import { AnimatePresence, motion } from "motion/react";
import { useEffect, useRef, useState } from "react";
import { Close } from "./Icons";
import type { Source } from "./types";
import { deviceLabel, matchLevel } from "./utils";

type ContentProps = { sources: Source[]; active: number | null; onClose: () => void };

function SourceItem({ source, n, active, innerRef }: {
  source: Source;
  n: number;
  active: boolean;
  innerRef: (el: HTMLLIElement | null) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const long = source.text.length > 240;
  const level = matchLevel(source.distance);

  return (
    <li className="source" data-active={active} ref={innerRef}>
      <div className="source-head">
        <span className="source-n">{n}</span>
        <span className="source-label">{source.label}</span>
      </div>
      <div className="source-tags">
        <span>{source.kind === "error_code" ? "Error-code table" : "Manual or runbook"}</span>
        {source.device && source.device !== "all" && <span>{deviceLabel(source.device)}</span>}
        {source.kind === "error_code" ? (
          <span>Exact match</span>
        ) : (
          <span className="match" role="img" aria-label={level.label}>
            <span className="bars" aria-hidden="true">
              {[1, 2, 3].map((bar) => (
                <motion.span
                  key={bar}
                  className="bar"
                  data-on={bar <= level.bars}
                  initial={{ scaleY: 0.3, opacity: 0 }}
                  animate={{ scaleY: 1, opacity: 1 }}
                  transition={{ duration: 0.4, delay: 0.1 + bar * 0.08, ease: [0.22, 1, 0.36, 1] }}
                />
              ))}
            </span>
            {level.label}
          </span>
        )}
      </div>
      <p className="source-text" data-clamped={long && !expanded}>
        {source.text}
      </p>
      <div className="source-links">
        {long && (
          <button className="link-btn" onClick={() => setExpanded((e) => !e)}>
            {expanded ? "Show less" : "Show more"}
          </button>
        )}
        {source.kind === "document" && source.file && (
          <a
            className="link-btn"
            href={`/api/files/${encodeURIComponent(source.file)}${source.page ? `#page=${source.page}` : ""}`}
            target="_blank"
            rel="noreferrer"
          >
            {/\.pdf$/i.test(source.file) ? `Open the document${source.page ? ` at page ${source.page}` : ""}` : "Download the document"}
          </a>
        )}
      </div>
    </li>
  );
}

export function EvidenceContent({ sources, active, onClose }: ContentProps) {
  const refs = useRef<Record<number, HTMLLIElement | null>>({});

  useEffect(() => {
    if (active !== null) refs.current[active]?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [active]);

  return (
    <div className="evidence-inner">
      <div className="panel-head">
        <h2 className="panel-title">Sources</h2>
        <button className="icon-btn" onClick={onClose} aria-label="Close sources">
          <Close />
        </button>
      </div>
      <p className="panel-sub">What the answer was written from. Numbers match the chips on each step.</p>
      <ol className="evidence-list">
        {sources.map((source, i) => (
          <SourceItem
            key={`${source.label}-${i}`}
            source={source}
            n={i + 1}
            active={active === i + 1}
            innerRef={(el) => {
              refs.current[i + 1] = el;
            }}
          />
        ))}
      </ol>
    </div>
  );
}

type DockProps = ContentProps & { open: boolean; overlay: boolean };

/** Docked beside the conversation on wide screens, a slide-over sheet on narrow ones. */
export function EvidenceDock({ open, overlay, ...content }: DockProps) {
  if (overlay) {
    return (
      <AnimatePresence>
        {open && (
          <>
            <motion.div
              key="scrim"
              className="scrim"
              onClick={content.onClose}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
            />
            <motion.aside
              key="sheet"
              className="sheet"
              data-side="right"
              role="dialog"
              aria-label="Sources"
              initial={{ x: "100%" }}
              animate={{ x: 0 }}
              exit={{ x: "100%" }}
              transition={{ duration: 0.38, ease: [0.22, 1, 0.36, 1] }}
            >
              <EvidenceContent {...content} />
            </motion.aside>
          </>
        )}
      </AnimatePresence>
    );
  }

  return (
    <motion.aside
      className="evidence"
      aria-label="Sources"
      initial={false}
      animate={{ width: open ? 330 : 0 }}
      transition={{ duration: 0.42, ease: [0.22, 1, 0.36, 1] }}
      inert={!open}
      style={{ borderLeftWidth: open ? 1 : 0 }}
    >
      <EvidenceContent {...content} />
    </motion.aside>
  );
}
