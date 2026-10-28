export type Block = {
  kind: "step" | "text";
  text: string;
  cites: number[];
  supported: boolean | null;
};

export type Source = {
  label: string;
  text: string;
  kind: "error_code" | "document";
  distance: number | null;
  device: string | null;
};

export type Stage = { node: string; label: string; detail: string; at: number };

export type AnswerData = {
  fallback: boolean;
  intent: string | null;
  text: string;
  blocks: Block[];
  sources: Source[];
  elapsed: number;
};

export type Turn = {
  id: string;
  question: string;
  device: string;
  status: "running" | "done" | "error";
  stages: Stage[];
  answer?: AnswerData;
  error?: string;
};

export type StreamEvent =
  | ({ type: "stage" } & Stage)
  | ({ type: "answer" } & AnswerData)
  | { type: "error"; message: string };

export type DocInfo = { source: string; type: string; device_model: string; chunks: number };

export type UploadResult = {
  name: string;
  status: "added" | "updated" | "skipped" | "error";
  chunks?: number;
  message?: string;
};

export type Health = { ollama: boolean; ready: boolean; chat_model: string; embed_model: string };
