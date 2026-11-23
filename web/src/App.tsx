import { useQuery } from "@tanstack/react-query";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { api } from "./api";
import { useFlash } from "./flash";
import Books from "./pages/Books";
import Library from "./pages/Library";
import Quest from "./pages/Quest";
import Review from "./pages/Review";
import TraceDetail from "./pages/TraceDetail";
import Traces from "./pages/Traces";

const tab = ({ isActive }: { isActive: boolean }) => `tab${isActive ? " active" : ""}`;

export default function App() {
  const { notice, error } = useFlash();
  // The Traces tab only shows when the server has the dashboard switched on.
  const health = useQuery({ queryKey: ["health"], queryFn: api.health });
  return (
    <>
      <header>
        <h1>StoryQuest</h1>
        <nav aria-label="Sections">
          <NavLink to="/" end className={tab}>Play</NavLink>
          <NavLink to="/books" className={tab}>Books</NavLink>
          <NavLink to="/review" className={tab}>Review</NavLink>
          {health.data?.traces && <NavLink to="/traces" className={tab}>Traces</NavLink>}
        </nav>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<Library />} />
          <Route path="/quest/:bookId/:chapterIdx" element={<Quest />} />
          <Route path="/books" element={<Books />} />
          <Route path="/review" element={<Review />} />
          <Route path="/review/:bookId" element={<Review />} />
          <Route path="/traces" element={<Traces />} />
          <Route path="/traces/:traceId" element={<TraceDetail />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
        {notice && <p className="notice" role="status">{notice}</p>}
        {error && <p className="error" role="alert">{error}</p>}
      </main>
    </>
  );
}
