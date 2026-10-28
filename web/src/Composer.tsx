import { AnimatePresence, motion } from "motion/react";
import { useLayoutEffect, useRef } from "react";
import { DeviceSwitch } from "./DeviceSwitch";
import { Send, Stop } from "./Icons";
import { useMedia } from "./utils";

type Props = {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  onStop: () => void;
  running: boolean;
  devices: string[];
  device: string;
  onDevice: (device: string) => void;
  followups: string[];
  onFollowup: (text: string) => void;
  hasConversation: boolean;
};

export function Composer({
  value,
  onChange,
  onSubmit,
  onStop,
  running,
  devices,
  device,
  onDevice,
  followups,
  onFollowup,
  hasConversation,
}: Props) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const compact = useMedia("(max-width: 520px)");

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (!value) {
      el.style.height = ""; // empty: let the CSS min-height decide
      return;
    }
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 168)}px`;
  }, [value]);

  const canSend = value.trim().length > 0 && !running;

  return (
    <div className="dock">
      <AnimatePresence initial={false}>
        {followups.length > 0 && (
          <motion.div
            className="followups"
            initial={{ opacity: 0, y: 8, height: 0 }}
            animate={{ opacity: 1, y: 0, height: "auto" }}
            exit={{ opacity: 0, y: 8, height: 0 }}
            transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
          >
            {followups.map((text) => (
              <button key={text} className="reason-chip" onClick={() => onFollowup(text)}>
                {text}
              </button>
            ))}
          </motion.div>
        )}
      </AnimatePresence>
      <form
        className="composer"
        onSubmit={(e) => {
          e.preventDefault();
          if (canSend) onSubmit();
        }}
      >
        <label htmlFor="question" className="sr-only">
          Describe the problem or enter an error code
        </label>
        <textarea
          id="question"
          ref={ref}
          className="composer-input"
          rows={1}
          value={value}
          placeholder={
            compact
              ? hasConversation
                ? "Ask a follow-up or a new problem"
                : "Describe the fault or error code"
              : hasConversation
                ? "Ask a follow-up, or describe a new problem"
                : "Describe the fault, or paste an error code like P-1002"
          }
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              if (canSend) onSubmit();
            }
          }}
        />
        <div className="composer-bar">
          <DeviceSwitch devices={devices} value={device} onChange={onDevice} />
          <span className="hint">Enter to ask</span>
          <button
            type={running ? "button" : "submit"}
            className="send"
            data-mode={running ? "stop" : "ask"}
            disabled={!running && !canSend}
            onClick={running ? onStop : undefined}
            aria-label={running ? "Stop" : "Ask"}
          >
            <AnimatePresence mode="wait" initial={false}>
              <motion.span
                key={running ? "stop" : "ask"}
                style={{ display: "grid" }}
                initial={{ opacity: 0, scale: 0.6 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.6 }}
                transition={{ duration: 0.14 }}
              >
                {running ? <Stop /> : <Send />}
              </motion.span>
            </AnimatePresence>
          </button>
        </div>
      </form>
    </div>
  );
}
