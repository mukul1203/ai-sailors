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
