import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import TraceGate from "../components/TraceGate";
import type { TraceDetail, TraceFilters } from "../types";

const PAGE = 25;
const ROUTES = [
  "story_question", "feelings", "off_topic", "unsafe", "injection", "personal",
  "empty", "too_long", "error",
];
const MODES = ["M0", "M1", "M1S", "M2", "M2S", "M3", "M3S", "M4", "M4S"];

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
  from: string; to: string;
}
const EMPTY: Form = { mode: "", route: "", flag: "", minLatency: "", cached: "", from: "", to: "" };

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

interface ModelCall {
  name: string;
  costTokens: number;
  latencyS: number;
  completionTokens: number;
}

interface ModelSummary {
  model: string;
  calls: ModelCall[];
  totalTokens: number;
  averageTokens: number | null;
  averageLatencyS: number | null;
  generationSpeed: number | null;
  scores: { cost: number | null; latency: number | null; speed: number | null };
}

function modelColor(model: string): string {
  let hash = 0;
  for (const char of model) hash = (hash * 31 + char.charCodeAt(0)) | 0;
  return `hsl(${Math.abs(hash) % 360} 58% 40%)`;
}

function score(value: number | null, samples: number[], lowerIsBetter: boolean): number | null {
  if (value === null || samples.length === 0) return null;
  const low = Math.min(...samples);
  const high = Math.max(...samples);
  if (high === low) return null;
  const normalized = lowerIsBetter
    ? ((high - value) / (high - low)) * 100
    : ((value - low) / (high - low)) * 100;
  return Math.round(Math.max(0, Math.min(100, normalized)));
}

function summarizeModel(details: TraceDetail[], model: string): ModelSummary {
  const calls = details.flatMap((detail) =>
    detail.trace.steps
      .filter((step) => step.model === model && !step.cached)
      .map((step) => ({
        name: step.name,
        costTokens: step.prompt_tokens + step.completion_tokens,
        latencyS: step.latency_s,
        completionTokens: step.completion_tokens,
      })),
  );
  const latencySamples = calls.filter((call) => call.latencyS > 0).map((call) => call.latencyS);
  const generationCalls = calls.filter((call) => call.name === "generate" && call.latencyS > 0);
  const totalLatency = latencySamples.reduce((sum, latency) => sum + latency, 0);
  const generatedTokens = generationCalls.reduce((sum, call) => sum + call.completionTokens, 0);
  const generationLatency = totalLatencyFor(generationCalls);
  const totalTokens = calls.reduce((sum, call) => sum + call.costTokens, 0);
  const averageTokens = calls.length ? totalTokens / calls.length : null;
  const averageLatencyS = latencySamples.length
    ? totalLatency / latencySamples.length
    : null;
  const generationSpeed = generationLatency > 0
    ? generatedTokens / generationLatency
    : null;
  const speedSamples = generationCalls.map((call) => call.completionTokens / call.latencyS);

  return {
    model,
    calls,
    totalTokens,
    averageTokens,
    averageLatencyS,
    generationSpeed,
    scores: {
      cost: score(averageTokens, calls.map((call) => call.costTokens), true),
      latency: score(averageLatencyS, latencySamples, true),
      speed: score(generationSpeed, speedSamples, false),
    },
  };
}

function totalLatencyFor(calls: ModelCall[]): number {
  return calls.reduce((sum, call) => sum + call.latencyS, 0);
}

function formatTokens(value: number): string {
  return Math.round(value).toLocaleString();
}

function RadarChart({ summary }: { summary: ModelSummary }) {
  const axes = [
    {
      label: "Cost efficiency",
      score: summary.scores.cost,
      actual: summary.averageTokens === null
        ? "not available"
        : `${summary.averageTokens.toFixed(0)} tokens per live model call`,
      direction: "Lower token use is better",
    },
    {
      label: "Latency",
      score: summary.scores.latency,
      actual: summary.averageLatencyS === null
        ? "not available"
        : `${summary.averageLatencyS.toFixed(2)} seconds per live model call`,
      direction: "Lower latency is better",
    },
    {
      label: "Generation speed",
      score: summary.scores.speed,
      actual: summary.generationSpeed === null
        ? "not available"
        : `${summary.generationSpeed.toFixed(1)} output tokens per second`,
      direction: "Higher throughput is better",
    },
  ];
  const centerX = 220;
  const centerY = 160;
  const radius = 104;
  const angles = axes.map((_, index) => -Math.PI / 2 + (index * Math.PI * 2) / axes.length);
  const point = (index: number, fraction: number) => ({
    x: centerX + Math.cos(angles[index]) * radius * fraction,
    y: centerY + Math.sin(angles[index]) * radius * fraction,
  });
  const polygon = (fraction: number) =>
    axes.map((_, index) => {
      const p = point(index, fraction);
      return `${p.x},${p.y}`;
    }).join(" ");
  const dataPolygon = axes.map((axis, index) => {
    const p = point(index, (axis.score ?? 0) / 100);
    return `${p.x},${p.y}`;
  }).join(" ");
  const hasCompleteScores = axes.every((axis) => axis.score !== null);
  const color = modelColor(summary.model);

  return (
    <figure className="benchmark-card">
      <figcaption>
        Overall performance · normalized within the visible sample
        {!hasCompleteScores && <span> · unavailable or flat metrics are marked N/A</span>}
      </figcaption>
      <svg viewBox="0 0 440 330" role="img" aria-label={`Performance radar for ${summary.model}`}>
        {[0.2, 0.4, 0.6, 0.8, 1].map((fraction) => (
          <polygon
            key={fraction}
            points={polygon(fraction)}
            fill="none"
            className="benchmark-radar-grid"
          />
        ))}
        {axes.map((axis, index) => {
          const outer = point(index, 1);
          const label = point(index, 1.28);
          const anchor = Math.cos(angles[index]) > 0.4
            ? "start"
            : Math.cos(angles[index]) < -0.4 ? "end" : "middle";
          return (
            <g key={axis.label}>
              <line
                x1={centerX}
                y1={centerY}
                x2={outer.x}
                y2={outer.y}
                className="benchmark-radar-axis"
              />
              <text x={label.x} y={label.y} textAnchor={anchor} className="benchmark-axis-label">
                <tspan x={label.x}>{axis.label}</tspan>
                <tspan x={label.x} dy="15">{axis.score === null ? "N/A" : `${axis.score}/100`}</tspan>
              </text>
            </g>
          );
        })}
        {hasCompleteScores && (
          <polygon points={dataPolygon} fill={color} fillOpacity="0.2" stroke={color} strokeWidth="3">
            <title>{summary.model}</title>
          </polygon>
        )}
        {axes.map((axis, index) => {
          if (axis.score === null) return null;
          const p = point(index, axis.score / 100);
          return (
            <circle key={axis.label} cx={p.x} cy={p.y} r="5" fill={color} tabIndex={0}>
              <title>{`${axis.label}: ${axis.score}/100 · ${axis.actual} · ${axis.direction}`}</title>
            </circle>
          );
        })}
      </svg>
      <div className="benchmark-model-legend">
        <span className="benchmark-swatch" style={{ backgroundColor: color }} />
        {summary.model}
      </div>
    </figure>
  );
}

function MetricBars({ summary }: { summary: ModelSummary }) {
  const rows = [
    {
      label: "Average token-based cost proxy",
      value: summary.averageTokens,
      unit: "tokens / live model call",
      scale: summary.calls.map((call) => call.costTokens),
    },
    {
      label: "Average model-call latency",
      value: summary.averageLatencyS,
      unit: "seconds / live model call",
      scale: summary.calls.filter((call) => call.latencyS > 0).map((call) => call.latencyS),
    },
    {
      label: "Generation throughput",
      value: summary.generationSpeed,
      unit: "output tokens / second",
      scale: summary.calls
        .filter((call) => call.name === "generate" && call.latencyS > 0)
        .map((call) => call.completionTokens / call.latencyS),
    },
  ];

  return (
    <figure className="benchmark-card">
      <figcaption>Metric breakdown · each bar uses its own observed scale</figcaption>
      <div className="benchmark-bars">
        {rows.map((row) => {
          const maximum = Math.max(...row.scale, 0);
          const width = row.value === null || maximum === 0
            ? 0
            : Math.min(100, (row.value / maximum) * 100);
          const display = row.value === null
            ? "N/A"
            : `${row.value.toFixed(row.unit.startsWith("seconds") ? 2 : 1)} ${row.unit}`;
          return (
            <div className="benchmark-bar-row" key={row.label}>
              <div className="benchmark-bar-heading">
                <b>{row.label}</b>
                <span>{display}</span>
              </div>
              <div className="benchmark-bar-track" role="img" aria-label={`${row.label}: ${display}`}>
                <div
                  className="benchmark-bar-fill"
                  style={{ width: `${width}%`, backgroundColor: modelColor(summary.model) }}
                  title={`${row.label}: ${display}`}
                />
              </div>
            </div>
          );
        })}
      </div>
    </figure>
  );
}

function PerformanceDashboard({
  details,
  models,
  model,
  onModelChange,
}: {
  details: TraceDetail[];
  models: string[];
  model: string;
  onModelChange: (model: string) => void;
}) {
  const summary = summarizeModel(details, model);
  const generatedCalls = summary.calls.filter(
    (call) => call.name === "generate" && call.latencyS > 0,
  );

  return (
    <section className="model-dashboard" aria-label="LLM performance dashboard">
      <div className="model-dashboard-heading">
        <div>
          <h3>LLM performance</h3>
          <p className="note">
            One model at a time · {summary.calls.length} live model calls in this trace page.
            Cached calls are excluded.
          </p>
        </div>
        {models.length > 1 && (
          <label>
            Selected model
            <select value={model} onChange={(event) => onModelChange(event.target.value)}>
              {models.map((name) => <option key={name}>{name}</option>)}
            </select>
          </label>
        )}
      </div>

      <p className="benchmark-disclaimer">
        Token count is a usage-based cost proxy, not a currency amount; no provider pricing is
        available in the existing trace data. Radar scores are relative to the selected model's
        visible call sample, not an external benchmark.
      </p>

      <div className="benchmark-kpis">
        <Tile
          label="cost proxy · total / average tokens"
          value={summary.averageTokens === null
            ? "N/A"
            : `${formatTokens(summary.totalTokens)} / ${summary.averageTokens.toFixed(0)}`}
        />
        <Tile
          label="average model-call latency"
          value={summary.averageLatencyS === null ? "N/A" : `${summary.averageLatencyS.toFixed(2)} s`}
        />
        <Tile
          label={`generation speed · ${generatedCalls.length} calls`}
          value={summary.generationSpeed === null
            ? "N/A"
            : `${summary.generationSpeed.toFixed(1)} tok/s`}
        />
      </div>

      <div className="benchmark-grid">
        <RadarChart summary={summary} />
        <MetricBars summary={summary} />
      </div>
    </section>
  );
}

async function loadTraceDetails(ids: number[]): Promise<TraceDetail[]> {
  const details: TraceDetail[] = [];
  for (let index = 0; index < ids.length; index += 5) {
    const batch = ids.slice(index, index + 5);
    details.push(...await Promise.all(batch.map((id) => api.trace(id))));
  }
  return details;
}

// Grown-ups: what really happened on the children's questions.
export default function Traces() {
  const [form, setForm] = useState<Form>(EMPTY);
  const [page, setPage] = useState(0);
  const [selectedModel, setSelectedModel] = useState("");
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
  const modelCalls = useQuery({
    queryKey: ["traces", "model-calls", key, page],
    queryFn: () => loadTraceDetails((list.data?.items ?? []).map((trace) => trace.id)),
    enabled: Boolean(list.data?.items.length),
  });

  if (list.error) return <section className="traces"><TraceGate error={list.error} /></section>;

  const total = list.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE));
  const s = stats.data;
  const models = Array.from(new Set(
    (modelCalls.data ?? []).flatMap((detail) =>
      detail.trace.steps.map((step) => step.model).filter(Boolean),
    ),
  )).sort();
  const activeModel = models.includes(selectedModel) ? selectedModel : models[0] ?? "";
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

      {modelCalls.isPending && list.data?.items.length ? (
        <p className="note">Loading model performance...</p>
      ) : null}
      {modelCalls.error && <p className="error" role="alert">{modelCalls.error.message}</p>}
      {modelCalls.data && activeModel && (
        <PerformanceDashboard
          details={modelCalls.data}
          models={models}
          model={activeModel}
          onModelChange={setSelectedModel}
        />
      )}
      {modelCalls.data && !activeModel && (
        <p className="note">No model-call metrics are available for these traces.</p>
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
