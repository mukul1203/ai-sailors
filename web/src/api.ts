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
  TraceDetail,
  TraceFilters,
  TraceList,
  TraceStats,
} from "./types";

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

// The trace dashboard's admin token lives only for this browser tab (sessionStorage).
const TOKEN_KEY = "storyquest.adminToken";

export function getAdminToken(): string {
  try {
    return sessionStorage.getItem(TOKEN_KEY) ?? "";
  } catch {
    return "";
  }
}

export function setAdminToken(token: string): void {
  try {
    if (token) sessionStorage.setItem(TOKEN_KEY, token);
    else sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    // storage blocked: the token just has to be typed again
  }
}

function query(params: object): string {
  const q = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "" && value !== null) q.set(key, String(value));
  }
  const text = q.toString();
  return text ? `?${text}` : "";
}

async function request<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const init: RequestInit = { method };
  const headers: Record<string, string> = {};
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  if (path.startsWith("/api/admin/traces")) headers["X-Admin-Token"] = getAdminToken();
  init.headers = headers;
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
  health: () => request<{ traces: boolean }>("/api/health"),
  traces: (filters: TraceFilters, limit: number, offset: number) =>
    request<TraceList>(`/api/admin/traces${query({ ...filters, limit, offset })}`),
  traceStats: (filters: TraceFilters) =>
    request<TraceStats>(`/api/admin/traces/stats${query(filters)}`),
  trace: (id: number) => request<TraceDetail>(`/api/admin/traces/${id}`),
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
