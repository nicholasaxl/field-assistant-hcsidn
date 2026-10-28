import { AnswerView } from "./AnswerView";
import { DeviceIcon, Alert } from "./Icons";
import { Timeline } from "./Timeline";
import type { Turn } from "./types";
import { deviceKind, deviceLabel } from "./utils";

type Props = {
  turn: Turn;
  activeSource: number | null;
  onCite: (n: number) => void;
  onOpenSources: () => void;
  onOpenLibrary: () => void;
  onSearchAll: () => void;
  canSearchAll: boolean;
  onClarify: (option: string, kind: "device" | "detail") => void;
};

export function TurnView({
  turn,
  activeSource,
  onCite,
  onOpenSources,
  onOpenLibrary,
  onSearchAll,
  canSearchAll,
  onClarify,
}: Props) {
  const inferred = turn.answer?.device_inferred ?? null;
  return (
    <article className="turn" aria-busy={turn.status === "running"}>
      <div className="turn-q">
        <p>{turn.question}</p>
        <span className="chip">
          <DeviceIcon kind={deviceKind(inferred ?? turn.device)} />
          {inferred ? `Looking at ${inferred}` : deviceLabel(turn.device)}
        </span>
      </div>
      {inferred && (
        <p className="inferred-note">
          You left the device on All devices, so I narrowed the search from the question.{" "}
          <button className="link-btn" onClick={onSearchAll} disabled={!canSearchAll}>
            Search all devices
          </button>
        </p>
      )}

      {turn.stages.length > 0 || turn.status === "running" ? (
        <Timeline stages={turn.stages} running={turn.status === "running"} elapsed={turn.answer?.elapsed} />
      ) : null}

      {turn.status === "done" && turn.clarify && (
        <div className="clarify" role="status">
          <p className="clarify-prompt">{turn.clarify.prompt}</p>
          {turn.clarify.options.length > 0 && (
            <div className="reason-chips">
              {turn.clarify.options.map((option) => (
                <button key={option} className="reason-chip" onClick={() => onClarify(option, turn.clarify!.kind)}>
                  {deviceLabel(option)}
                </button>
              ))}
            </div>
          )}
          {turn.clarify.kind === "detail" && (
            <p className="inferred-note">Pick the device, then describe what you see in the box below.</p>
          )}
        </div>
      )}

      {turn.status === "done" && turn.answer && (
        <AnswerView
          answer={turn.answer}
          activeSource={activeSource}
          onCite={onCite}
          onOpenSources={onOpenSources}
          onOpenLibrary={onOpenLibrary}
        />
      )}

      {turn.status === "error" && (
        <div className="notice" data-tone="error" role="alert">
          <Alert />
          <div>
            <p className="notice-title">That didn't work</p>
            <p>{turn.error}</p>
          </div>
        </div>
      )}
    </article>
  );
}
