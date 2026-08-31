import { useEffect, useState } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { useTheme } from "../context/ThemeContext";
import { useAuth } from "../hooks/useAuth";
import { saleLiveApi } from "../api/saleLive";
import { CATALOG } from "../types/catalog";
import { ZONES } from "../routes/sale/inventory/registry";
import type { UserRole } from "../types";
import {
  AlertIcon,
  ActivityIcon,
  AuremontLogoIcon,
  BuildingIcon,
  ChartIcon,
  ChatIcon,
  CheckIcon,
  ChevronRightIcon,
  DocumentIcon,
  GlobeIcon,
  HomeIcon,
  LogInIcon,
  LogOutIcon,
  MenuIcon,
  MoonIcon,
  PlusIcon,
  SettingsIcon,
  ShieldCheckIcon,
  SunIcon,
  UsersIcon,
  XIcon,
} from "./Icons";

// How often Sale/Admin poll for the "Khách đang chờ" badge count — same interval as
// LiveInboxPage.tsx's own poll, kept independent since the badge must update even when
// that page isn't open.
const LIVE_INBOX_POLL_MS = 10000;

interface AdminNavEntry {
  to: string;
  label: string;
  icon: (p: { size?: number }) => React.ReactElement;
  roles: UserRole[];
  end?: boolean;
}

// ADMIN manages the document store and AI quality monitoring; no separate inventory menu.
const ADMIN_NAV: AdminNavEntry[] = [
  { to: "/sales", label: "Quản lý Sale", icon: UsersIcon, roles: ["admin"] },
  { to: "/news-workspace", label: "Duyệt tin", icon: GlobeIcon, roles: ["admin"] },
  { to: "/observability", label: "Giám sát hệ thống", icon: ActivityIcon, roles: ["admin"] },
  { to: "/documents", label: "Kho tài liệu", icon: DocumentIcon, roles: ["admin"] },
  { to: "/document-review", label: "Duyệt metadata", icon: CheckIcon, roles: ["admin"] },
  { to: "/eval", label: "Chất lượng trả lời", icon: ChartIcon, roles: ["admin"] },
  { to: "/conflicts", label: "Cảnh báo mâu thuẫn", icon: AlertIcon, roles: ["admin"] },
  { to: "/billing-requests", label: "Đăng ký doanh nghiệp", icon: BuildingIcon, roles: ["admin"] },
  { to: "/settings", label: "Cài đặt chung", icon: SettingsIcon, roles: ["admin"] },
];

// Ocean Park 1 is the only mega-project with real data so far — its product types
// (apartments/villas/shophouses) become the top-level menu, and each dropdown lists
// the actual sub-zones matching the reference site's menu (no longer grouped by
// Studio/1BR/2BR like before).
const OCEAN_PARK_1 = CATALOG[0];

// Zones that own a page at /inventory/<category>/<zone>. The registry is the single
// source of truth, so a zone added there shows up here without touching this file.
const ZONE_BY_SLUG = new Map(ZONES.map((z) => [z.slug, z]));

// Used both by an anonymous visitor's homepage ("/") and a logged-in Sale/Customer's ("/home") —
// same nav either way, so the two paths need to be treated as the same "home" location below.
const HOME_PATHS = new Set(["/", "/home"]);

export function TopNavbar() {
  const { theme, toggleTheme } = useTheme();
  const { isAuthenticated, role, username, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [openDropdown, setOpenDropdown] = useState<string | null>(null);

  // Everyone except Admin gets the catalogue dropdown + Chat link: Sale, a logged-in
  // Customer, and an anonymous visitor all browse the same public catalogue — only the
  // chat *answers* are restricted server-side (see backend/services/agent_pipeline.py).
  const showCatalogNav = role !== "admin";
  const homeHref = isAuthenticated ? "/home" : "/";

  // On the home page and pages with a hero banner (category/project detail), the
  // menu floats transparently over the image instead of sitting as a solid bar.
  // Excludes /inventory/group/* specifically, since that page has no banner and a
  // transparent menu there would sit on a plain background and become unreadable.
  const isOverlay =
    showCatalogNav &&
    (HOME_PATHS.has(location.pathname) ||
      (location.pathname.startsWith("/inventory/") && !location.pathname.startsWith("/inventory/group/")));

  // Dropdown visibility is driven by mouse enter/leave state, not plain CSS :hover —
  // because the cursor stays in the same position after a navigation click (SPA
  // routing doesn't reload the page), so :hover would keep the dropdown open on top
  // of the new page's content. Reset on route change to force it closed.
  useEffect(() => {
    setOpenDropdown(null);
  }, [location.pathname]);

  // Admin now manages the queue from /sales, where sessions can be assigned and
  // re-assigned. The compact live inbox remains the Sale's own work queue.
  const showLiveInboxNav = role === "sale";
  const [waitingCount, setWaitingCount] = useState(0);

  useEffect(() => {
    if (!showLiveInboxNav) return;
    const poll = () => saleLiveApi.listWaiting().then((rows) => setWaitingCount(rows.length)).catch(() => {});
    poll();
    const interval = setInterval(poll, LIVE_INBOX_POLL_MS);
    return () => clearInterval(interval);
  }, [showLiveInboxNav]);

  const handleLogout = () => {
    logout();
    setMobileOpen(false);
    navigate("/login", { replace: true });
  };

  return (
    <header className={`topnav ${isOverlay ? "topnav--overlay" : ""} ${role === "admin" ? "topnav--admin" : ""}`}>
      <NavLink to={homeHref} className="topnav-brand" onClick={() => setMobileOpen(false)}>
        <AuremontLogoIcon size={28} />
        <span>Auremont</span>
      </NavLink>

      <nav className="topnav-links">
        <NavLink to={homeHref} end className={({ isActive }) => `topnav-link ${isActive ? "topnav-link--active" : ""}`}>
          <HomeIcon size={16} />
          Trang chủ
        </NavLink>

        <NavLink to="/news" className={({ isActive }) => `topnav-link ${isActive ? "topnav-link--active" : ""}`}>
          <GlobeIcon size={16} />
          Tin tức
        </NavLink>

        {role === "sale" && (
          <NavLink to="/news-workspace" className={({ isActive }) => `topnav-link ${isActive ? "topnav-link--active" : ""}`}>
            <PlusIcon size={16} />
            Đăng tin
          </NavLink>
        )}

        {showCatalogNav && (
          <>
            {OCEAN_PARK_1.categories.map((c) => (
              <div
                key={c.slug}
                className="topnav-item"
                onMouseEnter={() => setOpenDropdown(c.slug)}
                onMouseLeave={() => setOpenDropdown(null)}
              >
                {/* Each product type now has its own URL (/inventory/chung-cu, /inventory/biet-thu...)
                    so isActive resolves correctly, instead of all three highlighting at once as before. */}
                <NavLink
                  to={`/inventory/${c.slug}`}
                  onClick={(e) => {
                    setOpenDropdown(null);
                    e.currentTarget.blur();
                  }}
                  className={({ isActive }) => `topnav-link ${isActive ? "topnav-link--active" : ""}`}
                >
                  {c.name}
                  {c.groups.length > 0 && <ChevronRightIcon size={12} className="topnav-caret" />}
                </NavLink>
                {c.groups.length > 0 && (
                  <div className={`topnav-dropdown ${openDropdown === c.slug ? "topnav-dropdown--open" : ""}`}>
                    {c.groups.map((g) => {
                      const zone = ZONE_BY_SLUG.get(g.slug);

                      if (zone) {
                        const zoneHref = `/inventory/${zone.categorySlug}/${zone.slug}`;
                        // Sub-zones that still share the zone's page (Metropolitan's towers,
                        // Senique's blocks) keep a #hash; the rest link straight to the page.
                        const subLinks =
                          zone.subAnchors ??
                          (g.projects.length > 1
                            ? g.projects
                                .filter((p) => p.projectId)
                                .map((p) => ({ label: p.name, anchorId: p.projectId as string }))
                            : undefined);

                        if (!subLinks || subLinks.length === 0) {
                          return (
                            <NavLink
                              key={g.slug}
                              to={zoneHref}
                              onClick={(e) => {
                                setOpenDropdown(null);
                                e.currentTarget.blur();
                              }}
                              className="topnav-dropdown-item"
                            >
                              {g.name}
                            </NavLink>
                          );
                        }

                        return (
                          <div key={g.slug} className="topnav-subitem">
                            <NavLink
                              to={zoneHref}
                              onClick={(e) => {
                                setOpenDropdown(null);
                                e.currentTarget.blur();
                              }}
                              className="topnav-dropdown-item"
                            >
                              {g.name}
                            </NavLink>
                            <div className="topnav-submenu">
                              {subLinks.map((s) => (
                                <NavLink
                                  key={s.anchorId}
                                  to={`${zoneHref}#${s.anchorId}`}
                                  onClick={(e) => {
                                    setOpenDropdown(null);
                                    e.currentTarget.blur();
                                  }}
                                  className="topnav-dropdown-item"
                                >
                                  {s.label}
                                </NavLink>
                              ))}
                            </div>
                          </div>
                        );
                      }

                      return g.projects.length > 1 ? (
                        // Group with multiple sub-projects but NO in-page section yet -> opens a
                        // second-level flyout on hover, matching the reference site's menu; clicking
                        // the group name itself still goes to the group listing page.
                        <div key={g.slug} className="topnav-subitem">
                          <NavLink
                            to={`/inventory/group/${g.slug}`}
                            onClick={(e) => {
                              setOpenDropdown(null);
                              e.currentTarget.blur();
                            }}
                            className="topnav-dropdown-item"
                          >
                            {g.name}
                          </NavLink>
                          <div className="topnav-submenu">
                            {g.projects.map((p) =>
                              p.projectId ? (
                                <NavLink
                                  key={p.projectId}
                                  to={`/inventory/project/${p.projectId}`}
                                  onClick={(e) => {
                                    setOpenDropdown(null);
                                    e.currentTarget.blur();
                                  }}
                                  className="topnav-dropdown-item"
                                >
                                  {p.name}
                                </NavLink>
                              ) : (
                                <span key={p.name} className="topnav-dropdown-item topnav-link--disabled">
                                  {p.name}
                                </span>
                              )
                            )}
                          </div>
                        </div>
                      ) : (
                        <NavLink
                          key={g.slug}
                          to={
                            g.projects[0]?.projectId
                              ? `/inventory/project/${g.projects[0].projectId}`
                              : `/inventory/group/${g.slug}`
                          }
                          onClick={(e) => {
                            setOpenDropdown(null);
                            e.currentTarget.blur();
                          }}
                          className="topnav-dropdown-item"
                        >
                          {g.name}
                        </NavLink>
                      );
                    })}
                  </div>
                )}
              </div>
            ))}

            {role === "sale" ? (
              // Sale's own chat is a straight consult flow — there's no "talk to a
              // specialist" concept when Sale IS the specialist, so no dropdown here.
              <NavLink to="/chat" className={({ isActive }) => `topnav-link ${isActive ? "topnav-link--active" : ""}`}>
                <ChatIcon size={16} />
                Chat
              </NavLink>
            ) : (
              <div
                className="topnav-item"
                onMouseEnter={() => setOpenDropdown("chat")}
                onMouseLeave={() => setOpenDropdown(null)}
              >
                <NavLink
                  to="/chat"
                  onClick={() => setOpenDropdown(null)}
                  className={({ isActive }) => `topnav-link ${isActive ? "topnav-link--active" : ""}`}
                >
                  <ChatIcon size={16} />
                  Chat
                  <ChevronRightIcon size={12} className="topnav-caret" />
                </NavLink>
                <div className={`topnav-dropdown ${openDropdown === "chat" ? "topnav-dropdown--open" : ""}`}>
                  <NavLink to="/chat" end onClick={() => setOpenDropdown(null)} className="topnav-dropdown-item">
                    Chat với Auremont AI
                  </NavLink>
                  {/* Its own page (/chat/tu-van), not a prefill into the AI chat: opening it
                      requests the handoff directly. An anonymous visitor still lands on the
                      register gate there, same as before. */}
                  <NavLink
                    to="/chat/tu-van"
                    onClick={() => setOpenDropdown(null)}
                    className="topnav-dropdown-item"
                  >
                    Chat với chuyên viên tư vấn
                  </NavLink>
                </div>
              </div>
            )}
          </>
        )}

        {showLiveInboxNav && (
          <NavLink to="/live-inbox" className={({ isActive }) => `topnav-link ${isActive ? "topnav-link--active" : ""}`}>
            <UsersIcon size={16} />
            Khách đang chờ
            {waitingCount > 0 && <span className="topnav-badge">{waitingCount}</span>}
          </NavLink>
        )}

        {role === "admin" &&
          ADMIN_NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) => `topnav-link ${isActive ? "topnav-link--active" : ""}`}
            >
              <item.icon size={16} />
              {item.label}
            </NavLink>
          ))}
      </nav>

      <div className="topnav-right">
        <button
          className="topnav-util"
          type="button"
          onClick={toggleTheme}
          title={theme === "dark" ? "Chuyển sang giao diện sáng" : "Chuyển sang giao diện tối"}
        >
          {theme === "dark" ? <SunIcon size={15} /> : <MoonIcon size={15} />}
        </button>
        {isAuthenticated ? (
          <div className="topnav-user">
            <div className="topnav-avatar" title={username ?? ""}>
              {username ? username.charAt(0).toUpperCase() : role === "admin" ? <ShieldCheckIcon size={14} /> : <ChatIcon size={14} />}
            </div>
            <div className="topnav-user-info">
              <span className="topnav-user-name">{username ?? "—"}</span>
              <span className="topnav-user-role">
                {role === "admin" ? "Admin" : role === "customer" ? "Khách hàng" : "Sale"}
              </span>
            </div>
            <button className="topnav-logout" type="button" onClick={handleLogout} title="Đăng xuất">
              <LogOutIcon size={14} />
            </button>
          </div>
        ) : (
          <NavLink to="/login" className="btn btn-primary" onClick={() => setMobileOpen(false)}>
            Đăng nhập
            <LogInIcon size={15} />
          </NavLink>
        )}

        <button
          className="topnav-mobile-toggle"
          type="button"
          onClick={() => setMobileOpen((v) => !v)}
          aria-label={mobileOpen ? "Đóng menu" : "Mở menu"}
        >
          {mobileOpen ? <XIcon size={20} /> : <MenuIcon size={20} />}
        </button>
      </div>

      {mobileOpen && (
        <div className="topnav-mobile-menu">
          <NavLink
            to={homeHref}
            end
            onClick={() => setMobileOpen(false)}
            className={({ isActive }) => `topnav-link ${isActive ? "topnav-link--active" : ""}`}
          >
            <HomeIcon size={16} />
            Trang chủ
          </NavLink>

          <NavLink
            to="/news"
            onClick={() => setMobileOpen(false)}
            className={({ isActive }) => `topnav-link ${isActive ? "topnav-link--active" : ""}`}
          >
            <GlobeIcon size={16} />
            Tin tức
          </NavLink>

          {role === "sale" && (
            <NavLink
              to="/news-workspace"
              onClick={() => setMobileOpen(false)}
              className={({ isActive }) => `topnav-link ${isActive ? "topnav-link--active" : ""}`}
            >
              <PlusIcon size={16} />
              Đăng tin
            </NavLink>
          )}

          {showCatalogNav && (
            <>
              {OCEAN_PARK_1.categories.map((c) => (
                <div key={c.slug} className="topnav-mobile-group">
                  <NavLink
                    to={`/inventory/${c.slug}`}
                    onClick={() => setMobileOpen(false)}
                    className={({ isActive }) => `topnav-link ${isActive ? "topnav-link--active" : ""}`}
                  >
                    {c.name}
                  </NavLink>
                  {c.groups.map((g) => (
                    <NavLink
                      key={g.slug}
                      to={
                        ZONE_BY_SLUG.has(g.slug)
                          ? `/inventory/${ZONE_BY_SLUG.get(g.slug)!.categorySlug}/${g.slug}`
                          : g.projects.length === 1 && g.projects[0].projectId
                            ? `/inventory/project/${g.projects[0].projectId}`
                            : `/inventory/group/${g.slug}`
                      }
                      onClick={() => setMobileOpen(false)}
                      className={({ isActive }) =>
                        `topnav-link topnav-mobile-sublink ${isActive ? "topnav-link--active" : ""}`
                      }
                    >
                      {g.name}
                    </NavLink>
                  ))}
                </div>
              ))}
              {role === "sale" ? (
                <NavLink
                  to="/chat"
                  onClick={() => setMobileOpen(false)}
                  className={({ isActive }) => `topnav-link ${isActive ? "topnav-link--active" : ""}`}
                >
                  <ChatIcon size={16} />
                  Chat
                </NavLink>
              ) : (
                <div className="topnav-mobile-group">
                  <span className="topnav-link">
                    <ChatIcon size={16} />
                    Chat
                  </span>
                  <NavLink
                    to="/chat"
                    end
                    onClick={() => setMobileOpen(false)}
                    className={({ isActive }) =>
                      `topnav-link topnav-mobile-sublink ${isActive ? "topnav-link--active" : ""}`
                    }
                  >
                    Chat với Auremont AI
                  </NavLink>
                  <NavLink
                    to="/chat/tu-van"
                    onClick={() => setMobileOpen(false)}
                    className={({ isActive }) =>
                      `topnav-link topnav-mobile-sublink ${isActive ? "topnav-link--active" : ""}`
                    }
                  >
                    Chat với chuyên viên tư vấn
                  </NavLink>
                </div>
              )}
            </>
          )}

          {showLiveInboxNav && (
            <NavLink
              to="/live-inbox"
              onClick={() => setMobileOpen(false)}
              className={({ isActive }) => `topnav-link ${isActive ? "topnav-link--active" : ""}`}
            >
              <UsersIcon size={16} />
              Khách đang chờ
              {waitingCount > 0 && <span className="topnav-badge">{waitingCount}</span>}
            </NavLink>
          )}

          {role === "admin" &&
            ADMIN_NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                onClick={() => setMobileOpen(false)}
                className={({ isActive }) => `topnav-link ${isActive ? "topnav-link--active" : ""}`}
              >
                <item.icon size={16} />
                {item.label}
              </NavLink>
            ))}

          <div className="topnav-mobile-sep" />
          <button className="topnav-link" type="button" onClick={toggleTheme}>
            {theme === "dark" ? <SunIcon size={16} /> : <MoonIcon size={16} />}
            {theme === "dark" ? "Giao diện sáng" : "Giao diện tối"}
          </button>
          {isAuthenticated ? (
            <button className="topnav-link" type="button" onClick={handleLogout}>
              <LogOutIcon size={16} />
              Đăng xuất
            </button>
          ) : (
            <NavLink to="/login" className="topnav-link" onClick={() => setMobileOpen(false)}>
              <LogInIcon size={16} />
              Đăng nhập
            </NavLink>
          )}
        </div>
      )}
    </header>
  );
}
