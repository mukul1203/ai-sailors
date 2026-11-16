import type {
  AddBookBody,
  ApproveBody,
  ApproveResult,
  AskResult,
  LibraryBook,
  Mission,
  PublishResult,
  ReviewView,
  SessionView,
} from "./types";

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const init: RequestInit = { method };
  if (body !== undefined) {
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(body);
  }
  let response: Response;
  try {
    response = await fetch(path, init);
  } catch {
    throw new ApiError("Cannot reach the story server. Is it running?", 0);
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = data?.error?.message ?? "Something went wrong. Try again!";
    throw new ApiError(message, response.status);
  }
  return data as T;
}

export const api = {
  missions: () => request<Mission[]>("/api/missions"),
  library: () => request<LibraryBook[]>("/api/library"),
  prepare: (bookId: number, chapterIdx: number) =>
    request<{ job: unknown }>(`/api/library/${bookId}/chapters/${chapterIdx}/prepare`, "POST"),
  addBook: (body: AddBookBody) =>
    request<{ title: string }>("/api/admin/books", "POST", body),
  review: (bookId: number) => request<ReviewView>(`/api/admin/books/${bookId}/review`),
  approve: (bookId: number, body: ApproveBody) =>
    request<ApproveResult>(`/api/admin/books/${bookId}/approve`, "POST", body),
  publish: (bookId: number) =>
    request<PublishResult>(`/api/admin/books/${bookId}/publish`, "POST"),
  startSession: (bookId: number, chapterIdx: number) =>
    request<SessionView>("/api/sessions", "POST", { book_id: bookId, chapter_idx: chapterIdx }),
  session: (id: string) => request<SessionView>(`/api/sessions/${id}`),
  choose: (id: string, cardId: string) =>
    request<SessionView>(`/api/sessions/${id}/choice`, "POST", { card_id: cardId }),
  ask: (id: string, text: string) =>
    request<AskResult>(`/api/sessions/${id}/ask`, "POST", { text }),
};
