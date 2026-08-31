import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { TopNavbar } from "./components/TopNavbar";
import { ChatWidget } from "./components/ChatWidget";
import { BackToChatButton } from "./components/BackToChatButton";
import { Footer } from "./components/Footer";
import { ProtectedRoute } from "./components/ProtectedRoute";
import { useAuth } from "./hooks/useAuth";
import { Landing } from "./routes/Landing";
import { Home } from "./routes/Home";
import { Login } from "./routes/sale/Login";
import { Register } from "./routes/Register";
import { RegisterBusiness } from "./routes/RegisterBusiness";
import { SalePage } from "./routes/sale/SalePage";
import { CustomerChatPage } from "./routes/CustomerChatPage";
import { CategoryDetailPage } from "./routes/sale/CategoryDetailPage";
import { ZoneDetailPage } from "./routes/sale/ZoneDetailPage";
import { CatalogGroupPage } from "./routes/sale/CatalogGroupPage";
import { ProjectOverviewPage } from "./routes/sale/ProjectOverviewPage";
import { LiveInboxPage } from "./routes/sale/LiveInboxPage";
import { LiveChatPage } from "./routes/sale/LiveChatPage";
import { AdminHome } from "./routes/admin/AdminHome";
import { DocumentsTab } from "./routes/admin/DocumentsTab";
import { DocumentReviewTab } from "./routes/admin/DocumentReviewTab";
import { DocumentRelationsTab } from "./routes/admin/DocumentRelationsTab";
import { EvalTab } from "./routes/admin/EvalTab";
import { ConflictsTab } from "./routes/admin/ConflictsTab";
import { BillingRequestsTab } from "./routes/admin/BillingRequestsTab";
import { SettingsTab } from "./routes/admin/SettingsTab";
import { SalesManagementPage } from "./routes/admin/SalesManagementPage";
import { ObservabilityPage } from "./routes/admin/ObservabilityPage";
import { NotFound } from "./routes/NotFound";
import { NewsPage } from "./routes/NewsPage";
import { NewsDetailPage } from "./routes/NewsDetailPage";
import { NewsWorkspacePage } from "./routes/NewsWorkspacePage";

/** Admin gets its own dashboard; Sale and Customer see the chat-oriented home page. */
function HomeRoute() {
  const { role } = useAuth();
  return role === "admin" ? <AdminHome /> : <Home />;
}

/** `/chat` is reachable by everyone — anonymous visitors and Customer accounts get the
 * public chat flow (PUBLIC-tier retrieval only, enforced server-side, see
 * backend/routers/customer_chat.py); Sale keeps the existing consultation chat; Admin
 * doesn't consult customers directly, so it redirects home like before. Deliberately a
 * top-level route rather than nested under the authenticated AppShell below, since an
 * anonymous visitor must reach it without ever hitting a login redirect. */
function ChatRoute() {
  const { isAuthenticated, role } = useAuth();
  const { pathname } = useLocation();

  if (isAuthenticated && role === "admin") return <Navigate to="/home" replace />;

  // Two separate pages rather than one page with a toggle: /chat is the AI assistant and
  // /chat/tu-van is the live consultant, matching the two nav dropdown items. Sale keeps
  // its own consultation UI on /chat regardless of the sub-path.
  const isHumanChat = pathname.startsWith("/chat/tu-van");

  return (
    <div className="app-shell">
      <TopNavbar />
      <div className="app-content">
        {role === "sale" ? <SalePage /> : <CustomerChatPage mode={isHumanChat ? "human" : "ai"} />}
      </div>
    </div>
  );
}

/** Shared shell: top nav bar plus content area.
 *
 * Reachable without an account: /inventory/* is public catalogue/pricing browsing (the
 * same information a real showroom shows openly — see backend/routers/projects.py), and the
 * public homepage links straight into it. /home and every admin route stay gated by their
 * own <ProtectedRoute> below; the shell itself no longer blanket-requires login. */
function AppShell() {
  const { role } = useAuth();
  const location = useLocation();
  // LiveChatPage (a claimed live-handoff session) is full-height/no-scroll like /chat's
  // pages, so the Footer/ChatWidget below must stay off it for the same reason those are
  // already off /chat: "adding the Footer would push the height past 100vh". The bare
  // /live-inbox list page is a normal scrolling page and keeps both.
  const isLiveChatPage = /^\/live-inbox\/.+/.test(location.pathname);

  return (
    <div className="app-shell">
      <TopNavbar />
      <div className="app-content">
        <Routes>
          <Route
            path="/home"
            element={
              <ProtectedRoute>
                <HomeRoute />
              </ProtectedRoute>
            }
          />

          {/* Project lookup by product type — reached directly via the TopNavbar dropdown;
              there is no separate /inventory index page anymore (it duplicated the menu).
              Public: same catalogue/pricing an anonymous visitor sees on the homepage. */}
          <Route path="/inventory/:categorySlug" element={<CategoryDetailPage />} />
          {/* One zone (phân khu) per page. Static segments above/below ("group", "project")
              are more specific, so React Router still matches those first. */}
          <Route path="/inventory/:categorySlug/:zoneSlug" element={<ZoneDetailPage />} />
          {/* Group/sub-zone within the multi-project catalog (e.g. "The Metropolitan" = Beverly/London/Paris/Zurich). */}
          <Route path="/inventory/group/:groupSlug" element={<CatalogGroupPage />} />
          {/* Detail page for one real sub-project (The Beverly, The Sapphire...), distinct from
              CategoryDetailPage above, which only shows Vinhomes Ocean Park's overview by product type. */}
          <Route path="/inventory/project/:projectId" element={<ProjectOverviewPage />} />
          {/* Public official-news feed: anonymous, Customer, Sale and Admin share it. */}
          <Route path="/news" element={<NewsPage />} />
          <Route path="/news/:articleId" element={<NewsDetailPage />} />
          <Route
            path="/news-workspace"
            element={
              <ProtectedRoute allowedRole={["sale", "admin"]}>
                <NewsWorkspacePage />
              </ProtectedRoute>
            }
          />

          {/* AI -> Sale live handoff queue — Sale and Admin both work it, no per-region
              assignment (see the plan's scope decisions). */}
          <Route
            path="/live-inbox"
            element={
              <ProtectedRoute allowedRole={["sale", "admin"]}>
                <LiveInboxPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/live-inbox/:sessionId"
            element={
              <ProtectedRoute allowedRole={["sale", "admin"]}>
                <LiveChatPage />
              </ProtectedRoute>
            }
          />

          {/* ADMIN-only area */}
          <Route
            path="/sales"
            element={
              <ProtectedRoute allowedRole="admin">
                <SalesManagementPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/observability"
            element={
              <ProtectedRoute allowedRole="admin">
                <ObservabilityPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/documents"
            element={
              <ProtectedRoute allowedRole="admin">
                <DocumentsTab />
              </ProtectedRoute>
            }
          />
          <Route
            path="/document-review"
            element={
              <ProtectedRoute allowedRole="admin">
                <DocumentReviewTab />
              </ProtectedRoute>
            }
          />
          <Route
            path="/document-relations"
            element={
              <ProtectedRoute allowedRole="admin">
                <DocumentRelationsTab />
              </ProtectedRoute>
            }
          />
          <Route
            path="/eval"
            element={
              <ProtectedRoute allowedRole="admin">
                <EvalTab />
              </ProtectedRoute>
            }
          />
          <Route
            path="/conflicts"
            element={
              <ProtectedRoute allowedRole="admin">
                <ConflictsTab />
              </ProtectedRoute>
            }
          />
          <Route
            path="/billing-requests"
            element={
              <ProtectedRoute allowedRole="admin">
                <BillingRequestsTab />
              </ProtectedRoute>
            }
          />
          <Route
            path="/settings"
            element={
              <ProtectedRoute allowedRole="admin">
                <SettingsTab />
              </ProtectedRoute>
            }
          />

          <Route path="*" element={<NotFound />} />
        </Routes>
      </div>

      {!isLiveChatPage && <Footer />}
      {role !== "admin" && !isLiveChatPage && <ChatWidget />}
      {role !== "admin" && !isLiveChatPage && <BackToChatButton />}
    </div>
  );
}

// Single entry point. `/`, `/chat` and `/inventory/*` are public; `/home` and the admin
// pages require login and route after that by role (SALE / ADMIN / CUSTOMER) — each one
// guarded individually inside AppShell/ChatRoute rather than with one blanket wrapper here.
function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />
      {/* Business sign-up files a subscription request; /register still creates CUSTOMER accounts. */}
      <Route path="/register-business" element={<RegisterBusiness />} />
      <Route path="/chat/*" element={<ChatRoute />} />
      <Route path="*" element={<AppShell />} />
    </Routes>
  );
}

export default App;
