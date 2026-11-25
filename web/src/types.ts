// Shapes of the JSON the FastAPI backend returns (see src/storyquest/api/).

export type ChapterState = "playable" | "prepared" | "not_prepared" | "preparing" | "failed";

export interface Chapter {
  idx: number;
  title: string;
  state: ChapterState;
  beats?: number;
  message?: string;
}

export interface LibraryBook {
  id: number | null;
  title: string;
  author: string;
  summary?: string;
  content_notes?: string;
  status?: string;
  error?: string;
  chapters: Chapter[];
}

export interface Mission {
  book_id: number;
  book: string;
  chapter_idx: number;
  chapter: string;
  beats: number;
}

export interface Card {
  id: string;
  text: string;
}

export interface Beat {
  title: string;
  narration: string;
  clues: string[];
  vocabulary: string[];
  choice: { prompt: string; cards: Card[] };
}

export interface QuestSummary {
  beats_completed: number;
  first_try: number;
  questions_asked: number;
  vocabulary: string[];
}

export interface SessionView {
  id: string;
  status: "active" | "completed";
  book: string;
  chapter: string;
  progress: { beat: number; total: number };
  questions_left: number;
  beat?: Beat;
  wrong_cards?: string[];
  hint?: string;
  feedback?: string;
  summary?: QuestSummary;
}

export interface AskResult {
  reply: string;
  back: string;
  questions_left: number;
}

export interface ReviewBeat {
  idx: number;
  title: string;
  status: string;
  flags: string[];
  narration: string;
  question?: string;
  cards: { text: string; right: boolean }[];
  hints: string[];
}

export interface ReviewChapter {
  idx: number;
  title: string;
  beats: ReviewBeat[];
}

export interface ReviewView {
  title: string;
  status: string;
  problems: string[];
  chapters: ReviewChapter[];
}

export interface ApproveBody {
  chapter_idx?: number;
  beat_idx?: number;
  include_flagged?: boolean;
}

export interface ApproveResult {
  approved: number;
  flagged_left?: number;
  empty_left?: number;
}

export interface PublishResult {
  published: boolean;
  problems: string[];
  embedding_error?: string;
}

export interface AddBookBody {
  gutenberg_id: number;
  title: string;
  author: string;
  summary: string;
  content_notes: string;
  text: string;
}

// ---- Trace dashboard (src/storyquest/api/traces.py) ----

export interface TraceRow {
  id: number;
  session_id: string;
  created_at: number; // epoch seconds
  mode: string;
  route: string;
  stored: "summary" | "full";
  question: string;
  total_latency_s: number;
  prompt_tokens: number;
  completion_tokens: number;
  cached: boolean;
  flags: string[];
}

export interface TraceList {
  items: TraceRow[];
  total: number;
}

export interface TraceFilters {
  mode?: string;
  route?: string;
  flag?: string;
  since?: number;
  until?: number;
  min_latency?: number;
  cached?: boolean;
  otel_trace?: string; // an OpenTelemetry trace id, or its first digits
}

export interface TraceStats {
  total: number;
  by_route: Record<string, number>;
  latency_mean_s: number;
  latency_p95_s: number;
  tokens_per_turn: number;
  top_flags: { flag: string; count: number }[];
  retrieval_miss_rate: number;
}

export interface TraceStep {
  name: string;
  prompt_tokens: number;
  completion_tokens: number;
  latency_s: number; // for a cached step: the original call's latency, not this one's
  cached: boolean;
  model: string;
  finish_reason: string | null;
  messages?: { role: string; content: string }[]; // only when stored in full
  output?: string; // only when stored in full
}

export interface TraceToolCall {
  tool: string;
  argument: string;
  found: number; // passages returned
  latency_s: number;
  error: string; // why the tool failed, if it did
}

export interface TracePassage {
  chunk_id: number;
  chapter: number;
  beat: number;
  idx: number;
  score: number;
  bm25_rank: number | null;
  dense_rank: number | null;
  rerank_rank: number | null;
  rerank_score: number | null;
  source: string; // "chunk", "entity" (a card) or "scene" (the current beat's retelling)
  text?: string; // only when stored in full
}

export interface TraceDetail {
  id: number;
  session_id: string;
  created_at: number;
  stored: "summary" | "full";
  question: string;
  reply: string;
  prompt_tokens: number;
  completion_tokens: number;
  cached: boolean;
  trace: {
    route: string;
    mode: string;
    started_at: number;
    total_latency_s: number;
    timings: Record<string, number>;
    steps: TraceStep[];
    passages: TracePassage[];
    flags: string[];
    evidence: string;
    tool_calls?: TraceToolCall[]; // agent mode (M5) only; absent in older traces
    otel_trace_id?: string; // set when OpenTelemetry export was on
  };
  notes: { flags: Record<string, string>; pipeline: string[] };
  otel_url: string; // a link to the trace in the OpenTelemetry viewer, when configured
}
