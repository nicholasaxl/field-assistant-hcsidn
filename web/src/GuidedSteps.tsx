import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";
import { postStep } from "./api";
import { FeedbackBar } from "./FeedbackBar";
import { Alert, Check } from "./Icons";
import type { Block } from "./types";

type Result = "done" | "failed";
type Phase = "step" | "failed" | "complete" | "handoff";

type Props = {
  steps: Block[];
  interactionId: string | null;
  activeSource: number | null;
  onCite: (n: number) => void;
  onExit: () => void;
};

const SLIDE = {
  initial: { opacity: 0, x: 28 },
  animate: { opacity: 1, x: 0 },
  exit: { opacity: 0, x: -28 },
  transition: { duration: 0.28, ease: [0.22, 1, 0.36, 1] as const },
};

/** One step at a time with Done / Didn't work. Results are saved so Insights can show which steps fail. */
export function GuidedSteps({ steps, interactionId, activeSource, onCite, onExit }: Props) {
  const [index, setIndex] = useState(0);
  const [results, setResults] = useState<Record<number, Result>>({});
  const [phase, setPhase] = useState<Phase>("step");
  const [error, setError] = useState<string | null>(null);

  const step = steps[index];
  const last = index === steps.length - 1;

  async function record(i: number, result: Result | null) {
    setResults((r) => {
      const next = { ...r };
      if (result === null) delete next[i];
      else next[i] = result;
      return next;
    });
    if (!interactionId) return;
    try {
      await postStep(interactionId, i, result);
      setError(null);
    } catch {
      setError("Couldn't save that step result, but you can keep going.");
    }
  }

  function markDone() {
    void record(index, "done");
    if (last) setPhase("complete");
    else setIndex(index + 1);
  }

  function markFailed() {
    void record(index, "failed");
    setPhase("failed");
  }

  function tryNext() {
    setPhase("step");
    if (!last) setIndex(index + 1);
    else setPhase("complete");
  }

  function back() {
    const previous = Math.max(0, index - 1);
    void record(previous, null); // going back un-marks that step so it can be re-judged
    setIndex(previous);
    setPhase("step");
  }

  return (
    <div className="guided">
      <ol className="guided-rail" aria-label="Progress">
        {steps.map((_, i) => (
          <li
            key={i}
            className="guided-dot"
            data-state={results[i] ?? (i === index && phase !== "complete" ? "current" : "todo")}
            aria-label={`Step ${i + 1}: ${results[i] === "done" ? "done" : results[i] === "failed" ? "did not work" : "not yet"}`}
          />
        ))}
      </ol>

      <AnimatePresence mode="wait" initial={false}>
        {phase === "step" && step && (
          <motion.div key={`step-${index}`} className="guided-card" {...SLIDE}>
            <p className="guided-count">
              Step {index + 1} of {steps.length}
            </p>
            <p className="guided-text">{step.text}</p>
            <div className="step-meta">
              {step.cites.map((c) => (
                <button
                  key={c}
                  className="cite"
                  aria-pressed={activeSource === c}
                  aria-label={`Show source ${c}`}
                  onClick={() => onCite(c)}
                >
                  {c}
                </button>
              ))}
              {!step.supported && (
                <span className="unverified">
                  <Alert />
                  Not found in the sources. Check before acting.
                </span>
              )}
            </div>
            <div className="guided-actions">
              <button className="primary-btn" onClick={markDone}>
                <Check />
                Done
              </button>
              <button className="pill-btn" onClick={markFailed}>
                Didn't work
              </button>
              {index > 0 && (
                <button className="link-btn guided-back" onClick={back}>
                  Back
                </button>
              )}
            </div>
          </motion.div>
        )}

        {phase === "failed" && (
          <motion.div key="failed" className="guided-card" {...SLIDE}>
            <p className="guided-count">Step {index + 1} didn't work</p>
            <p className="guided-text">
              {last
                ? "That was the last documented step. Hand this over with a summary of what you tried."
                : "You can try the next documented step, or hand this over with a summary of what you tried."}
            </p>
            <div className="guided-actions">
              {!last && (
                <button className="primary-btn" onClick={tryNext}>
                  Try the next step
                </button>
              )}
              <button className={last ? "primary-btn" : "pill-btn"} onClick={() => setPhase("handoff")}>
                Create handoff summary
              </button>
              <button className="link-btn guided-back" onClick={() => setPhase("step")}>
                Back to this step
              </button>
            </div>
          </motion.div>
        )}

        {phase === "handoff" && interactionId && (
          <motion.div key="handoff" className="guided-card" {...SLIDE}>
            <FeedbackBar interactionId={interactionId} initialPhase="reasons" initialReason="step_failed" />
          </motion.div>
        )}

        {phase === "complete" && (
          <motion.div key="complete" className="guided-card" {...SLIDE}>
            <p className="guided-count">All steps done</p>
            {interactionId && <FeedbackBar interactionId={interactionId} />}
          </motion.div>
        )}
      </AnimatePresence>

      {error && (
        <p className="feedback-error" role="alert">
          {error}
        </p>
      )}
      <button className="link-btn guided-exit" onClick={onExit}>
        Show all steps
      </button>
    </div>
  );
}
