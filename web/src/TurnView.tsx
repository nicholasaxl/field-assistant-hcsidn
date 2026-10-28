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
};

export function TurnView({ turn, activeSource, onCite, onOpenSources, onOpenLibrary }: Props) {
  return (
    <article className="turn" aria-busy={turn.status === "running"}>
      <div className="turn-q">
        <p>{turn.question}</p>
        <span className="chip">
          <DeviceIcon kind={deviceKind(turn.device)} />
          {deviceLabel(turn.device)}
        </span>
      </div>

      {turn.stages.length > 0 || turn.status === "running" ? (
        <Timeline stages={turn.stages} running={turn.status === "running"} elapsed={turn.answer?.elapsed} />
      ) : null}

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
