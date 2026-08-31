import { Link } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { AuremontLogoIcon } from "./Icons";

export function Footer() {
  // Shared between the public homepage (Landing.tsx, no account) and the authenticated
  // shell (AppShell) — "/home" 404s into a login redirect for an anonymous visitor, same
  // reasoning as TopNavbar's homeHref.
  const { isAuthenticated } = useAuth();
  const homeHref = isAuthenticated ? "/home" : "/";

  return (
    <footer className="site-footer">
      <div className="container site-footer-grid">
        <div className="site-footer-brand">
          <div className="site-footer-logo">
            <AuremontLogoIcon size={30} />
            <span>Auremont</span>
          </div>
          <p className="site-footer-tagline">
            Trợ lý AI tra cứu dự án và tư vấn khách hàng cho đội Sale bất động sản.
          </p>
        </div>

        <div className="site-footer-col">
          <h4>Công cụ</h4>
          {/* Same section Home.tsx's own "Tra cứu dự án" hero button scrolls to — the hash
              makes it land there directly instead of just the top of the homepage, handled
              by the scroll-to-hash effect in Home.tsx (needed because this is a full
              cross-page navigation, not a same-page click). */}
          <Link to={`${homeHref}#tra-cuu-du-an`}>Tra cứu dự án</Link>
          <Link to="/chat">Chat với Auremont AI</Link>
          <Link to="/chat/tu-van">Nhắn tin với chuyên viên tư vấn</Link>
        </div>

        <div className="site-footer-col">
          <h4>Tài nguyên</h4>
          <Link to={homeHref}>Về Auremont</Link>
          <Link to="/inventory/chung-cu">Danh sách dự án</Link>
        </div>

        <div className="site-footer-col site-footer-contact">
          <h4>Liên hệ</h4>
          <p className="site-footer-note">Thông tin bên dưới là placeholder — cập nhật khi có dữ liệu thật.</p>
          <div className="site-footer-fact">
            <span>Hotline / Zalo</span>
            <strong>Đang cập nhật</strong>
          </div>
          <div className="site-footer-fact">
            <span>Email hỗ trợ</span>
            <strong>support@auremont.vn</strong>
          </div>
          <div className="site-footer-fact">
            <span>Giờ hỗ trợ</span>
            <strong>08:30 – 21:00 hằng ngày</strong>
          </div>
        </div>
      </div>

      <div className="site-footer-bottom">
        <div className="container site-footer-bottom-inner">
          <span>© 2026 Auremont.</span>
        </div>
      </div>
    </footer>
  );
}
