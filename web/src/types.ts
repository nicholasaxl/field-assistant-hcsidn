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

export type Alert = { id: string; level: "critical" | "warning"; title: string; message: string };

export type Strength = { level: "strong" | "good" | "check"; label: string; reason: string };

export type Reason = "step_failed" | "different_problem" | "doc_wrong" | "need_person";
export type Outcome = "fixed" | "not_fixed" | "escalated";

export type AnswerData = {
  interaction_id: string | null;
  alerts: Alert[];
  strength: Strength | null;
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

export type InsightsData = {
  sample: boolean;
  has_real: boolean;
  days: number;
  minutes_per_escalation: number;
  questions: number;
  answered: number;
  no_answer: number;
  feedback_count: number;
  feedback_coverage: number | null;
  fixed: number;
  not_fixed: number;
  escalated: number;
  fixed_rate: number | null;
  escalation_rate: number | null;
  median_seconds: number | null;
  estimated_hours_saved: number;
  volume: { date: string; count: number }[];
  topics: { topic: string; count: number }[];
  gaps: { question: string; device: string; kind: "no_answer" | "not_fixed"; reason: Reason | null; count: number }[];
  documents: { document: string; answers: number; fixed: number; not_fixed: number; fix_rate: number | null }[];
  failing_steps: { step: string; count: number }[];
  recent: { question: string; device: string; outcome: Outcome; reason: Reason | null; ts: string }[];
};

export type Scorecard =
  | { available: false }
  | {
      available: true;
      date: string;
      model: string;
      corpus: { documents: number; chunks: number };
      questions: { in_scope: number; out_of_scope: number; critical: number };
      retrieval_hit_rate: number | null;
      refusal_rate: number | null;
      answer_pass_rate: number | null;
      traced_rate: number | null;
      alert_rate: number | null;
      median_seconds: number | null;
    };

export type Health ={ ollama: boolean; ready: boolean; chat_model: string; embed_model: string };
