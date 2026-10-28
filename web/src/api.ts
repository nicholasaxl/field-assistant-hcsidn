import type { DocInfo, Health, StreamEvent, UploadResult } from "./types";

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
  onEvent: (event: StreamEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  const res = await fetch("/api/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, device_model: device }),
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

export const deleteDocument = (source: string) =>
  fetch(`/api/documents/${encodeURIComponent(source)}`, { method: "DELETE" }).then((r) =>
    json<{ removed: string }>(r),
  );
