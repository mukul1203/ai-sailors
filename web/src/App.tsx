import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { useFlash } from "./flash";
import Books from "./pages/Books";
import Library from "./pages/Library";
import Quest from "./pages/Quest";
import Review from "./pages/Review";

const tab = ({ isActive }: { isActive: boolean }) => `tab${isActive ? " active" : ""}`;

export default function App() {
  const { notice, error } = useFlash();
  return (
    <>
      <header>
        <h1>StoryQuest</h1>
        <nav aria-label="Sections">
          <NavLink to="/" end className={tab}>Play</NavLink>
          <NavLink to="/books" className={tab}>Books</NavLink>
          <NavLink to="/review" className={tab}>Review</NavLink>
        </nav>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<Library />} />
          <Route path="/quest/:bookId/:chapterIdx" element={<Quest />} />
          <Route path="/books" element={<Books />} />
          <Route path="/review" element={<Review />} />
          <Route path="/review/:bookId" element={<Review />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
        {notice && <p className="notice" role="status">{notice}</p>}
        {error && <p className="error" role="alert">{error}</p>}
      </main>
    </>
  );
}
