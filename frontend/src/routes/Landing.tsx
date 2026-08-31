import { Navigate } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { TopNavbar } from "../components/TopNavbar";
import { Footer } from "../components/Footer";
import { ChatWidget } from "../components/ChatWidget";
import { Home } from "./Home";

/** Public homepage — reachable with no account. Deliberately the exact same page (and the
 * exact same TopNavbar — catalogue dropdown, Chat link, everything) as what a logged-in
 * Sale/Customer sees at `/home`: a visitor browses identically to Sale. Data stays split
 * at the API layer, not the page layer — the catalogue/project pages this links to are
 * already public-safe, and chat answers are capped at PUBLIC clearance server-side (see
 * backend/services/agent_pipeline.py). */
export function Landing() {
  const { isAuthenticated } = useAuth();
  if (isAuthenticated) return <Navigate to="/home" replace />;

  return (
    <div className="app-shell">
      <TopNavbar />
      <div className="app-content">
        <Home />
      </div>
      <Footer />
      <ChatWidget />
    </div>
  );
}
