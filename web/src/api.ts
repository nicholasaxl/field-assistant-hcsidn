import type { DocInfo, Health, InsightsData, Outcome, Reason, Scorecard, StreamEvent, UploadResult } from "./types";

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* keep the generic message */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

/** POST a question and read the server-sent event stream as it arrives. */
export async function askStream(
  question: string,
  device: string,
  infer: boolean,
  onEvent: (event: StreamEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  const res = await fetch("/api/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, device_model: device, infer_device: infer }),
    signal,
  });
  if (!res.ok || !res.body) throw new Error(`Can't reach the assistant (${res.status}). Is the server running?`);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let end: number;
    while ((end = buffer.indexOf("\n\n")) >= 0) {
      const raw = buffer.slice(0, end);
      buffer = buffer.slice(end + 2);
      if (raw.startsWith("data: ")) onEvent(JSON.parse(raw.slice(6)) as StreamEvent);
    }
  }
}

export const getHealth = () => fetch("/api/health").then((r) => json<Health>(r));
export const getDevices = () => fetch("/api/devices").then((r) => json<string[]>(r));
export const getDocuments = () =>
  fetch("/api/documents").then((r) => json<{ documents: DocInfo[]; extensions: string[]; max_mb: number }>(r));

export async function uploadDocuments(files: File[], deviceModel: string) {
  const form = new FormData();
  files.forEach((f) => form.append("files", f));
  form.append("device_model", deviceModel);
  return json<{ results: UploadResult[] }>(await fetch("/api/documents", { method: "POST", body: form }));
}

const post = (url: string, body: unknown) =>
  fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

export const postFeedback = (interactionId: string, outcome: Outcome, reason?: Reason, note?: string) =>
  post("/api/feedback", { interaction_id: interactionId, outcome, reason: reason ?? null, note: note || null }).then((r) =>
    json<{ ok: boolean; handoff: string | null }>(r),
  );

export const undoFeedback = (interactionId: string) =>
  fetch(`/api/feedback/${encodeURIComponent(interactionId)}`, { method: "DELETE" }).then((r) => json<{ ok: boolean }>(r));

export const postStep = (interactionId: string, index: number, result: "done" | "failed" | null) =>
  post("/api/steps", { interaction_id: interactionId, index, result }).then((r) => json<{ ok: boolean }>(r));

export const getInsights = (days: number, minutes: number | null) =>
  fetch(`/api/insights?days=${days}${minutes === null ? "" : `&minutes=${minutes}`}`).then((r) => json<InsightsData>(r));

export const loadSampleData = () => post("/api/insights/sample", {}).then((r) => json<{ loaded: number }>(r));
export const removeSampleData = () =>
  fetch("/api/insights/sample", { method: "DELETE" }).then((r) => json<{ removed: number }>(r));
export const clearAllData = () =>
  fetch("/api/insights/data", { method: "DELETE" }).then((r) => json<{ removed: number }>(r));
export const getScorecard = () => fetch("/api/scorecard").then((r) => json<Scorecard>(r));

export const deleteDocument =(source: string) =>
  fetch(`/api/documents/${encodeURIComponent(source)}`, { method: "DELETE" }).then((r) =>
    json<{ removed: string }>(r),
  );
