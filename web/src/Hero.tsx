import { motion, useReducedMotion } from "motion/react";
import { Arcs } from "./Arcs";
import { DeviceIcon } from "./Icons";
import type { DeviceKind } from "./utils";

const SUGGESTIONS: { text: string; kind: DeviceKind }[] = [
  { text: "How do I clear a note jam?", kind: "atm" },
  { text: "I'm getting P-1002 on the terminal", kind: "pos" },
  { text: "The card reader is not detected", kind: "kiosk" },
  { text: "Receipts are printing blank", kind: "pos" },
];

const LINES = ["What's wrong", "with the device?"];
const EASE = [0.22, 1, 0.36, 1] as const;

/** The one orchestrated moment: arcs draw in, the headline rises line by line, then the examples settle. */
export function Hero({ onPick }: { onPick: (question: string) => void }) {
  const reduce = useReducedMotion();
  return (
    <section className="hero" aria-labelledby="hero-title">
      <Arcs className="hero-arcs" count={5} strokeWidth={2.2} draw />

      <h1 className="hero-title" id="hero-title">
        {LINES.map((line, i) => (
          <span className="hero-title-line" key={line}>
            <motion.span
              style={{ display: "block" }}
              initial={reduce ? false : { y: "105%" }}
              animate={{ y: 0 }}
              transition={{ duration: 0.8, delay: 0.35 + i * 0.12, ease: EASE }}
            >
              {line}
            </motion.span>
          </span>
        ))}
      </h1>

      <motion.p
        className="hero-sub"
        initial={reduce ? false : { opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.7, delay: 0.75 }}
      >
        Describe the fault or paste an error code. Every answer comes from your manuals and runbooks, and each step shows
        which one.
      </motion.p>

      <ul className="suggestions">
        {SUGGESTIONS.map((s, i) => (
          <motion.li
            key={s.text}
            initial={reduce ? false : { opacity: 0, x: -10 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.5, delay: 0.95 + i * 0.07, ease: EASE }}
          >
            <button className="suggestion" onClick={() => onPick(s.text)}>
              <span className="suggestion-icon">
                <DeviceIcon kind={s.kind} />
              </span>
              {s.text}
            </button>
          </motion.li>
        ))}
      </ul>
    </section>
  );
}
