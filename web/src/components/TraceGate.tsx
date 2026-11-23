import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import type { FormEvent } from "react";
import { ApiError, setAdminToken } from "../api";

// Shown instead of a trace page when the server says no: the admin token is missing or wrong
// (401), or the dashboard is switched off (404 on the list).
export default function TraceGate({ error }: { error: Error }) {
  const queryClient = useQueryClient();
  const [token, setToken] = useState("");
  const status = error instanceof ApiError ? error.status : 0;

  if (status === 404 && error.message === "Not found.") {
    return (
      <p className="note">
        The trace dashboard is switched off. Set <code>TRACE_DASHBOARD=true</code> and
        <code> ADMIN_TOKEN</code> on the server, then restart it.
      </p>
    );
  }
  if (status !== 401) return <p className="error" role="alert">{error.message}</p>;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setAdminToken(token.trim());
    setToken("");
    queryClient.invalidateQueries({ queryKey: ["traces"] });
  };
  return (
    <form className="card trace-token" onSubmit={submit}>
      <h3>Admin token</h3>
      <p className="note">Traces contain children's questions, so they need the admin token.</p>
      <label>
        Token
        <input
          type="password" value={token} autoComplete="off"
          onChange={(e) => setToken(e.target.value)}
        />
      </label>
      <button type="submit" disabled={!token.trim()}>Open traces</button>
    </form>
  );
}
