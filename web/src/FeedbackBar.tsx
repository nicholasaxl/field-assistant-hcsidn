import { AnimatePresence, motion } from "motion/react";
import { useEffect, useRef, useState } from "react";
import { postFeedback, undoFeedback } from "./api";
import { Check, Copy, ThumbDown, ThumbUp } from "./Icons";
import type { Reason } from "./types";

const REASONS: { id: Reason; label: string }[] = [
  { id: "step_failed", label: "A step didn't work" },
  { id: "different_problem", label: "It's a different problem" },
  { id: "doc_wrong", label: "The document is wrong or outdated" },
  { id: "need_person", label: "I need a person" },
];

type Phase = "ask" | "fixed" | "reasons" | "handoff";

const PANEL = {
  initial: { opacity: 0, y: 6 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: -6 },
  transition: { duration: 0.22, ease: [0.22, 1, 0.36, 1] as const },
};

/** The closed loop: did the answer fix it? A "no" asks why and produces an escalation summary. */
export function FeedbackBar({ interactionId, noAnswer = false }: { interactionId: string; noAnswer?: boolean }) {
  const [phase, setPhase] = useState<Phase>("ask");
  const [reason, setReason] = useState<Reason | null>(null);
  const [note, setNote] = useState("");
  const [handoff, setHandoff] = useState("");
  const [escalated, setEscalated] = useState(false);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const root = useRef<HTMLDivElement>(null);

  // The form and the handoff open below the fold; bring them into view when the panel changes.
  const firstRender = useRef(true);
  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    const timer = setTimeout(
      () => root.current?.scrollIntoView({ block: "nearest", behavior: reduce ? "auto" : "smooth" }),
      240,
    );
    return () => clearTimeout(timer);
  }, [phase]);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't save that. Try again.");
    } finally {
      setBusy(false);
    }
  }

  const markFixed = () =>
    run(async () => {
      await postFeedback(interactionId, "fixed");
      setPhase("fixed");
    });

  const submitNotFixed = () =>
    run(async () => {
      const res = await postFeedback(interactionId, "not_fixed", reason ?? undefined, note.trim() || undefined);
      setHandoff(res.handoff ?? "");
      setEscalated(false);
      setPhase("handoff");
    });

  const markEscalated = () =>
    run(async () => {
      const res = await postFeedback(interactionId, "escalated", "need_person", note.trim() || undefined);
      setHandoff(res.handoff ?? handoff);
      setEscalated(true);
    });

  // No answer was found: the useful next step is handing the problem to a person with a summary.
  const escalateUnanswered = () =>
    run(async () => {
      const res = await postFeedback(interactionId, "escalated", "need_person", note.trim() || undefined);
      setHandoff(res.handoff ?? "");
      setEscalated(true);
      setPhase("handoff");
    });

  const undo = () =>
    run(async () => {
      await undoFeedback(interactionId);
      setPhase("ask");
      setReason(null);
      setNote("");
      setHandoff("");
      setEscalated(false);
    });

  async function copy() {
    try {
      await navigator.clipboard.writeText(handoff);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      /* clipboard can be blocked; the text is still selectable on screen */
    }
  }

  return (
    <div className="feedback" ref={root}>
      <AnimatePresence mode="wait" initial={false}>
        {phase === "ask" && noAnswer && (
          <motion.div key="ask-none" className="feedback-row" {...PANEL}>
            <button className="primary-btn" onClick={escalateUnanswered} disabled={busy}>
              Escalate with a summary
            </button>
          </motion.div>
        )}

        {phase === "ask" && !noAnswer && (
          <motion.div key="ask" className="feedback-row" {...PANEL}>
            <span className="feedback-q">Did this fix it?</span>
            <button className="pill-btn" onClick={markFixed} disabled={busy}>
              <ThumbUp />
              Fixed it
            </button>
            <button className="pill-btn" onClick={() => setPhase("reasons")} disabled={busy}>
              <ThumbDown />
              Didn't fix it
            </button>
          </motion.div>
        )}

        {phase === "fixed" && (
          <motion.div key="fixed" className="feedback-row" {...PANEL}>
            <span className="feedback-done">
              <Check /> Marked as fixed. Thanks, this helps improve the answers.
            </span>
            <button className="link-btn feedback-undo" onClick={undo} disabled={busy}>
              Undo
            </button>
          </motion.div>
        )}

        {phase === "reasons" && (
          <motion.div key="reasons" className="feedback-form" {...PANEL}>
            <p className="feedback-q">What happened?</p>
            <div className="reason-chips" role="radiogroup" aria-label="What happened">
              {REASONS.map((r) => (
                <button
                  key={r.id}
                  role="radio"
                  aria-checked={reason === r.id}
                  className="reason-chip"
                  onClick={() => setReason(r.id)}
                >
                  {r.label}
                </button>
              ))}
            </div>
            <label className="sr-only" htmlFor={`note-${interactionId}`}>
              Add a note for the next engineer
            </label>
            <textarea
              id={`note-${interactionId}`}
              className="feedback-note"
              rows={2}
              maxLength={1000}
              placeholder="Add a note for the next engineer (optional)"
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
            <div className="feedback-actions">
              <button className="primary-btn" onClick={submitNotFixed} disabled={!reason || busy}>
                Create handoff summary
              </button>
              <button className="pill-btn" onClick={() => setPhase("ask")} disabled={busy}>
                Cancel
              </button>
            </div>
          </motion.div>
        )}

        {phase === "handoff" && (
          <motion.div key="handoff" className="feedback-form" {...PANEL}>
            <p className="feedback-q">Handoff summary</p>
            <p className="feedback-help">
              {escalated
                ? "Marked as escalated. Send this to the next level of support."
                : "Send this to the next level of support so they don't start from zero."}
            </p>
            <pre className="handoff" tabIndex={0}>
              {handoff}
            </pre>
            <div className="feedback-actions">
              <button className="primary-btn" onClick={copy}>
                {copied ? <Check /> : <Copy />}
                {copied ? "Copied" : "Copy summary"}
              </button>
              {!escalated && (
                <button className="pill-btn" onClick={markEscalated} disabled={busy}>
                  Mark as escalated
                </button>
              )}
              <button className="link-btn feedback-undo" onClick={undo} disabled={busy}>
                Undo
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {error && (
        <p className="feedback-error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
