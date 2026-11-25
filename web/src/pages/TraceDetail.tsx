import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import TraceGate from "../components/TraceGate";
import type { TracePassage, TraceStep } from "../types";
import { Flags, when } from "./Traces";

const STAGES = [
  "guard", "router", "planner", "tools", "retrieval", "generate", "verify", "output_check", "critic",
];

function rank(n: number | null): string {
  return n === null ? "–" : String(n);
}

function Passages({ passages, full }: { passages: TracePassage[]; full: boolean }) {
  if (!passages.length) return <p className="note">No passages were retrieved.</p>;
  return (
    <div className="trace-scroll">
      <table className="trace-table">
        <thead>
          <tr>
            <th>#</th><th>BM25</th><th>Meaning</th><th>Rerank</th><th>Score</th>
            <th>Position</th><th>Source</th>{full && <th>Text</th>}
          </tr>
        </thead>
        <tbody>
          {passages.map((p, i) => (
            <tr key={`${p.chunk_id}-${i}`}>
              <td>{i + 1}</td>
              <td>{rank(p.bm25_rank)}</td>
              <td>{rank(p.dense_rank)}</td>
              <td>{rank(p.rerank_rank)}</td>
              <td>{(p.rerank_score ?? p.score).toFixed(3)}</td>
              {/* chapter and part the passage came from: all must be at or before the child */}
              <td>ch {p.chapter + 1}, part {p.beat + 1}, #{p.idx}</td>
              <td>{p.source === "entity" ? "card" : "book"}</td>
              {full && <td className="trace-text">{p.text}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Step({ step }: { step: TraceStep }) {
  return (
    <details className="trace-step">
      <summary>
        <b>{step.name}</b>
        <span> · {step.latency_s.toFixed(2)} s{step.cached ? " (replayed from cache)" : ""}</span>
        <span> · {step.prompt_tokens} in / {step.completion_tokens} out</span>
        {step.model && <span> · {step.model}</span>}
        {step.finish_reason && step.finish_reason !== "stop" && (
          <span className="trace-flag"> finish: {step.finish_reason}</span>
        )}
      </summary>
      {step.messages ? (
        <>
          {step.messages.map((m, i) => (
            <div key={i}>
              <h4>{m.role}</h4>
              <pre>{m.content}</pre>
            </div>
          ))}
          <h4>model output</h4>
          <pre>{step.output}</pre>
        </>
      ) : (
        <p className="note">Prompt and output were not stored (TRACE_STORE=summary).</p>
      )}
    </details>
  );
}

export default function TraceDetail() {
  const { traceId } = useParams();
  const id = Number(traceId);
  const q = useQuery({ queryKey: ["traces", "one", id], queryFn: () => api.trace(id) });

  if (q.error) {
    return <section className="traces"><TraceGate error={q.error} /></section>;
  }
  if (!q.data) return <p className="note">Loading...</p>;
  const { trace, notes } = q.data;
  const full = q.data.stored === "full";
  const stages = STAGES.filter((s) => s in trace.timings);
  const flagNotes = trace.flags.map((f) => [f, notes.flags[f]] as const);

  return (
    <section className="traces trace-detail">
      <p><Link to="/traces">← All traces</Link></p>
      <h2>Trace {q.data.id}</h2>
      <p className="note">
        {when(q.data.created_at)} · mode {trace.mode} · {trace.total_latency_s.toFixed(2)} s ·{" "}
        {q.data.prompt_tokens + q.data.completion_tokens} tokens · stored as {q.data.stored}
      </p>
      {trace.otel_trace_id && (
        <p className="note">
          OpenTelemetry trace <code>{trace.otel_trace_id}</code>
          {q.data.otel_url && <> · <a href={q.data.otel_url} target="_blank" rel="noreferrer">open in Jaeger</a></>}
        </p>
      )}

      <div className="card">
        <h3>1. Question and route</h3>
        <p><b>Question:</b> {q.data.question || "(not available)"}</p>
        <p><b>Route:</b> {trace.route}</p>
        {stages.length > 0 && (
          <p className="note">
            Time per stage:{" "}
            {stages.map((s) => `${s} ${trace.timings[s].toFixed(2)} s`).join(" · ")}
          </p>
        )}
      </div>

      {trace.tool_calls && trace.tool_calls.length > 0 && (
        <div className="card">
          <h3>Tools the agent ran</h3>
          <table>
            <thead>
              <tr><th>Tool</th><th>Asked for</th><th>Passages found</th><th>Time</th></tr>
            </thead>
            <tbody>
              {trace.tool_calls.map((t, i) => (
                <tr key={`${t.tool}-${i}`}>
                  <td><code>{t.tool}</code></td>
                  <td>{t.argument || "–"}</td>
                  <td>{t.error ? `failed: ${t.error}` : t.found}</td>
                  <td>{t.latency_s.toFixed(2)} s</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="note">
            The planner chooses these. The child's position is set by code, so a tool only
            returns text the child has already read. The passages below are what the tools found.
          </p>
        </div>
      )}

      <div className="card">
        <h3>2. Retrieval</h3>
        <Passages passages={trace.passages} full={full} />
        <p className="note">
          Ranks are 1 = best. A "–" means that search did not return the passage. Position is
          where in the book it sits; the spoiler filter only lets through passages the child
          had already reached.
        </p>
      </div>

      <div className="card">
        <h3>3. Model calls</h3>
        {trace.steps.length === 0 && <p className="note">No model was called for this turn.</p>}
        {trace.steps.map((s, i) => <Step key={`${s.name}-${i}`} step={s} />)}
        {trace.steps.some((s) => s.cached) && (
          <p className="note">
            A replayed step shows the latency of the original call, not the time it took now.
          </p>
        )}
      </div>

      <div className="card">
        <h3>4. Grounding evidence</h3>
        {trace.evidence
          ? <blockquote className="trace-evidence">{trace.evidence}</blockquote>
          : <p className="note">This mode did not ask the model for evidence, or none was given.</p>}
      </div>

      <div className="card">
        <h3>5. Checks and final reply</h3>
        <p><b>Flags:</b> <Flags flags={trace.flags} /></p>
        {flagNotes.length > 0 && (
          <ul className="trace-notes">
            {flagNotes.map(([f, text]) => <li key={f}><code>{f}</code>: {text}</li>)}
          </ul>
        )}
        <p><b>Reply the child saw:</b></p>
        <blockquote className="trace-evidence">{q.data.reply}</blockquote>
      </div>

      {notes.pipeline.length > 0 && (
        <details className="card">
          <summary>How mode {trace.mode} works</summary>
          <ol>{notes.pipeline.map((p) => <li key={p}>{p}</li>)}</ol>
        </details>
      )}
    </section>
  );
}
