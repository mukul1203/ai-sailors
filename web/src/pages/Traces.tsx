import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import TraceGate from "../components/TraceGate";
import type { TraceFilters } from "../types";

const PAGE = 25;
const ROUTES = [
  "story_question", "feelings", "off_topic", "unsafe", "injection", "personal",
  "empty", "too_long", "error",
];
const MODES = ["M0", "M1", "M1S", "M2", "M2S", "M2S-FS", "M2S-COT", "M2S-DEC", "M3", "M3S", "M4", "M4S", "M5", "M5-FS", "M5-COT"];

export function when(epoch: number): string {
  return new Date(epoch * 1000).toLocaleString();
}

export function Flags({ flags }: { flags: string[] }) {
  if (!flags.length) return <span className="note">none</span>;
  return (
    <span className="trace-flags">
      {flags.map((f) => <span key={f} className="trace-flag">{f}</span>)}
    </span>
  );
}

interface Form {
  mode: string; route: string; flag: string; minLatency: string; cached: string;
  from: string; to: string; otel: string;
}
const EMPTY: Form = {
  mode: "", route: "", flag: "", minLatency: "", cached: "", from: "", to: "", otel: "",
};

function toFilters(f: Form): TraceFilters {
  const day = 86400;
  const start = f.from ? new Date(`${f.from}T00:00:00`).getTime() / 1000 : undefined;
  const end = f.to ? new Date(`${f.to}T00:00:00`).getTime() / 1000 + day : undefined;
  return {
    mode: f.mode || undefined,
    route: f.route || undefined,
    flag: f.flag.trim() || undefined,
    min_latency: f.minLatency && Number(f.minLatency) >= 0 ? Number(f.minLatency) : undefined,
    cached: f.cached === "" ? undefined : f.cached === "yes",
    since: start,
    until: end,
    otel_trace: f.otel.trim() || undefined,
  };
}

function Tile({ label, value }: { label: string; value: string }) {
  return (
    <div className="trace-tile">
      <b>{value}</b>
      <span>{label}</span>
    </div>
  );
}

// Grown-ups: what really happened on the children's questions.
export default function Traces() {
  const [form, setForm] = useState<Form>(EMPTY);
  const [page, setPage] = useState(0);
  const filters = toFilters(form);
  const key = JSON.stringify(filters);
  const set = (patch: Partial<Form>) => {
    setForm({ ...form, ...patch });
    setPage(0);
  };

  const list = useQuery({
    queryKey: ["traces", "list", key, page],
    queryFn: () => api.traces(filters, PAGE, page * PAGE),
  });
  const stats = useQuery({
    queryKey: ["traces", "stats", key],
    queryFn: () => api.traceStats(filters),
    enabled: !list.error,
  });

  if (list.error) return <section className="traces"><TraceGate error={list.error} /></section>;

  const total = list.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE));
  const s = stats.data;
  return (
    <section className="traces">
      <h2>Traces</h2>
      <p className="callout" role="note">
        These records contain children's questions. Keep this page to grown-ups, and do not
        share screenshots of it.
      </p>

      {s && (
        <div className="trace-tiles">
          <Tile label="questions" value={String(s.total)} />
          <Tile label="mean latency" value={`${s.latency_mean_s.toFixed(2)} s`} />
          <Tile label="p95 latency" value={`${s.latency_p95_s.toFixed(2)} s`} />
          <Tile label="tokens per turn" value={s.tokens_per_turn.toFixed(0)} />
          <Tile label="retrieval misses" value={`${(s.retrieval_miss_rate * 100).toFixed(0)}%`} />
        </div>
      )}
      {s && s.total > 0 && (
        <p className="note">
          Routes: {Object.entries(s.by_route).map(([r, n]) => `${r} ${n}`).join(", ")}
          {s.top_flags.length > 0 && (
            <> · Top flags: {s.top_flags.map((f) => `${f.flag} ${f.count}`).join(", ")}</>
          )}
        </p>
      )}

      <form className="trace-filters" onSubmit={(e) => e.preventDefault()} aria-label="Filters">
        <label>Mode
          <select value={form.mode} onChange={(e) => set({ mode: e.target.value })}>
            <option value="">Any</option>
            {MODES.map((m) => <option key={m}>{m}</option>)}
          </select>
        </label>
        <label>Route
          <select value={form.route} onChange={(e) => set({ route: e.target.value })}>
            <option value="">Any</option>
            {ROUTES.map((r) => <option key={r}>{r}</option>)}
          </select>
        </label>
        <label>Flag
          <input value={form.flag} placeholder="e.g. no_hits" onChange={(e) => set({ flag: e.target.value })} />
        </label>
        <label>OpenTelemetry trace id
          <input value={form.otel} placeholder="e.g. 77d0845" onChange={(e) => set({ otel: e.target.value })} />
        </label>
        <label>Slower than (s)
          <input type="number" min="0" step="0.5" value={form.minLatency}
            onChange={(e) => set({ minLatency: e.target.value })} />
        </label>
        <label>Replayed
          <select value={form.cached} onChange={(e) => set({ cached: e.target.value })}>
            <option value="">Any</option>
            <option value="yes">Has replayed steps</option>
            <option value="no">All live</option>
          </select>
        </label>
        <label>From
          <input type="date" value={form.from} onChange={(e) => set({ from: e.target.value })} />
        </label>
        <label>To
          <input type="date" value={form.to} onChange={(e) => set({ to: e.target.value })} />
        </label>
        <button type="button" className="secondary" onClick={() => { setForm(EMPTY); setPage(0); }}>
          Clear
        </button>
      </form>

      {list.isPending ? (
        <p className="note">Loading...</p>
      ) : list.data.items.length === 0 ? (
        <p className="note">No traces match. Ask a question in a quest and it will show up here.</p>
      ) : (
        <div className="trace-scroll">
          <table className="trace-table">
            <thead>
              <tr>
                <th>When</th><th>Mode</th><th>Route</th><th>Question</th>
                <th>Latency</th><th>Tokens</th><th>Flags</th>
              </tr>
            </thead>
            <tbody>
              {list.data.items.map((t) => (
                <tr key={t.id}>
                  <td><Link to={`/traces/${t.id}`}>{when(t.created_at)}</Link></td>
                  <td>{t.mode}</td>
                  <td>{t.route}</td>
                  <td className="trace-q" title={t.question}>{t.question}</td>
                  <td>{t.total_latency_s.toFixed(2)} s{t.cached && " ⟲"}</td>
                  <td>{t.prompt_tokens + t.completion_tokens}</td>
                  <td><Flags flags={t.flags} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="trace-pager">
        <button type="button" className="secondary" disabled={page === 0} onClick={() => setPage(page - 1)}>
          Newer
        </button>
        <span>Page {page + 1} of {pages} · {total} traces</span>
        <button type="button" className="secondary" disabled={page + 1 >= pages} onClick={() => setPage(page + 1)}>
          Older
        </button>
      </div>
    </section>
  );
}
