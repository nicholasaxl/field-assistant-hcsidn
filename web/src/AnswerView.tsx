import { motion, useReducedMotion } from "motion/react";
import { useState } from "react";
import { Alerts } from "./Alerts";
import { FeedbackBar } from "./FeedbackBar";
import { GuidedSteps } from "./GuidedSteps";
import { Alert, Copy, Check, GuideIcon, Info, LibraryIcon, SourcesIcon } from "./Icons";
import type { AnswerData, Block } from "./types";

type Props = {
  answer: AnswerData;
  activeSource: number | null;
  onCite: (n: number) => void;
  onOpenSources: () => void;
  onOpenLibrary: () => void;
};

const EASE = [0.22, 1, 0.36, 1] as const;
const RING = 2 * Math.PI * 14;

function StepMark({ n, supported, delay }: { n: number; supported: boolean; delay: number }) {
  return (
    <span className="step-mark" data-supported={supported}>
      <svg viewBox="0 0 34 34" aria-hidden="true">
        <circle className="step-ring-track" cx="17" cy="17" r="14" />
        {supported && (
          <motion.circle
            className="step-ring"
            cx="17"
            cy="17"
            r="14"
            strokeDasharray={RING}
            initial={{ strokeDashoffset: RING }}
            animate={{ strokeDashoffset: 0 }}
            transition={{ duration: 0.7, delay: delay + 0.15, ease: EASE }}
          />
        )}
      </svg>
      <span className="step-num">{n}</span>
    </span>
  );
}

type Group = { kind: "text"; text: string } | { kind: "steps"; steps: Block[] };

function group(blocks: Block[]): Group[] {
  const groups: Group[] = [];
  for (const block of blocks) {
    if (block.kind === "text") {
      groups.push({ kind: "text", text: block.text });
    } else {
      const last = groups[groups.length - 1];
      if (last && last.kind === "steps") last.steps.push(block);
      else groups.push({ kind: "steps", steps: [block] });
    }
  }
  return groups;
}

export function AnswerView({ answer, activeSource, onCite, onOpenSources, onOpenLibrary }: Props) {
  const reduce = useReducedMotion();
  const [copied, setCopied] = useState(false);
  const alerts = answer.alerts ?? [];
  // A critical alert comes first; the procedure stays one deliberate click away.
  const [showSteps, setShowSteps] = useState(!alerts.some((a) => a.level === "critical"));
  const [guided, setGuided] = useState(false);

  if (answer.fallback) {
    return (
      <div className="answer">
        <Alerts alerts={alerts} />
        <div className="notice" role="status">
          <Info />
          <div>
            {answer.exhausted ? (
              <>
                <p className="notice-title">No more documented steps</p>
                <p>
                  Everything the documents suggest for this has been tried. Hand it over with a summary so the next
                  person doesn't start from zero.
                </p>
              </>
            ) : (
              <>
                <p className="notice-title">Nothing in the library matches</p>
                <p>
                  This may not be a field-support question. If it is, name the device or error code, or add the
                  manual that covers it. Otherwise escalate to level 2 support.
                </p>
                <button className="pill-btn" onClick={onOpenLibrary}>
                  <LibraryIcon />
                  Open library
                </button>
              </>
            )}
          </div>
        </div>
        {answer.interaction_id && <FeedbackBar interactionId={answer.interaction_id} noAnswer />}
      </div>
    );
  }

  const groups = group(answer.blocks);
  const allSteps = answer.blocks.filter((b) => b.kind === "step");
  let stepNumber = 0;

  async function copySteps() {
    const text = allSteps.map((s, i) => `${i + 1}. ${s.text}`).join("\n");
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      /* clipboard can be blocked; nothing else to do */
    }
  }

  return (
    <div className="answer">
      <Alerts alerts={alerts} />
      <div className="answer-tags">
        {answer.strength && (
          <p className="strength" data-level={answer.strength.level} title={answer.strength.reason}>
            <span className="strength-dot" />
            {answer.strength.label}
          </p>
        )}
        {answer.fast && (
          <p className="tag" title="These steps are copied from the manual. No model wrote them.">
            Copied from the manual
          </p>
        )}
        {answer.model && !answer.fast && (
          <p
            className="tag"
            data-local={answer.model.local}
            title={
              answer.model.local
                ? `Written on this computer by ${answer.model.label}. Nothing left the machine.`
                : `Written online by ${answer.model.label}. The question and the document passages found for it were sent to the provider over the internet.`
            }
          >
            {answer.model.local ? "On this computer" : "Online"} · {answer.model.label}
          </p>
        )}
        {answer.cached && (
          <p className="tag" title="You asked this before and the documents haven't changed.">
            Saved answer
          </p>
        )}
      </div>
      {!showSteps ? (
        <div className="gate">
          <p>The documented procedure is hidden until you've read the alert above.</p>
          <button className="pill-btn" onClick={() => setShowSteps(true)}>
            Show the documented procedure
          </button>
        </div>
      ) : guided ? (
        <GuidedSteps
          steps={allSteps}
          interactionId={answer.interaction_id}
          activeSource={activeSource}
          onCite={onCite}
          onExit={() => setGuided(false)}
        />
      ) : (
        groups.map((g, gi) =>
        g.kind === "text" ? (
          <p className="answer-text" key={gi}>
            {g.text}
          </p>
        ) : (
          <ol className="steps" key={gi}>
            {g.steps.map((step) => {
              stepNumber += 1;
              const n = stepNumber;
              const delay = reduce ? 0 : (n - 1) * 0.09;
              return (
                <motion.li
                  key={n}
                  className="step"
                  data-highlight={activeSource !== null && step.cites.includes(activeSource)}
                  initial={reduce ? false : { opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.45, delay, ease: EASE }}
                >
                  <StepMark n={n} supported={Boolean(step.supported)} delay={delay} />
                  <div className="step-body">
                    <p className="step-text">{step.text}</p>
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
                  </div>
                </motion.li>
              );
            })}
          </ol>
        ),
        )
      )}

      <div className="answer-actions">
        {allSteps.length >= 2 && showSteps && !guided && (
          <button className="pill-btn" onClick={() => setGuided(true)}>
            <GuideIcon />
            Guide me step by step
          </button>
        )}
        {allSteps.length > 0 && (
          <button className="pill-btn" onClick={copySteps}>
            {copied ? <Check /> : <Copy />}
            {copied ? "Copied" : "Copy steps"}
          </button>
        )}
        {answer.sources.length > 0 && (
          <button className="pill-btn" onClick={onOpenSources}>
            <SourcesIcon />
            Sources
            <span className="count">{answer.sources.length}</span>
          </button>
        )}
        <span className="elapsed">{answer.elapsed} s</span>
      </div>

      {answer.interaction_id && !guided && <FeedbackBar interactionId={answer.interaction_id} />}
    </div>
  );
}
