// One zone (phân khu) per page, at /inventory/<category>/<zone>.
//
// Previously every zone of a category was stacked into a single scrolling page and
// the navbar jumped between anchors. That made the apartment page load ~10 zones'
// worth of images and API calls just to read one of them, and "back" never
// returned to where the Sale rep was. Each zone now owns a URL, so it loads only
// its own content and can be shared with a customer directly.
import { useEffect } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { findZone, zonesInCategory } from "./inventory/registry";
import { ArrowLeftIcon, SearchIcon } from "../../components/Icons";

export function ZoneDetailPage() {
  const { categorySlug, zoneSlug } = useParams();
  const location = useLocation();
  const zone = categorySlug && zoneSlug ? findZone(categorySlug, zoneSlug) : undefined;

  // Sub-zones (Metropolitan's towers, Senique's blocks) still live on one page and
  // are reached by #hash. Content below renders progressively as each block's API
  // call resolves, so a single scroll lands short — re-scroll over ~1.6s, backing
  // off as soon as the user takes over.
  useEffect(() => {
    if (!zone || !location.hash) return;
    const id = location.hash.slice(1);
    let cancelled = false;

    const scrollToAnchor = () => {
      if (cancelled) return;
      document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
    };

    const cancel = () => {
      cancelled = true;
    };
    window.addEventListener("wheel", cancel, { once: true, passive: true });
    window.addEventListener("touchmove", cancel, { once: true, passive: true });

    const timers = [0, 150, 450, 900, 1600].map((delay) => window.setTimeout(scrollToAnchor, delay));

    return () => {
      cancelled = true;
      timers.forEach(window.clearTimeout);
      window.removeEventListener("wheel", cancel);
      window.removeEventListener("touchmove", cancel);
    };
  }, [zone, location.hash]);

  // Landing on a fresh zone should start at the top, otherwise the scroll position
  // carries over from the zone the user just left.
  useEffect(() => {
    if (location.hash) return;
    window.scrollTo({ top: 0 });
  }, [zoneSlug, location.hash]);

  if (!zone) {
    return (
      <div className="page">
        <div className="empty-state">
          <div className="empty-state-icon">
            <SearchIcon size={26} />
          </div>
          <p className="empty-state-title">Không tìm thấy phân khu này</p>
          <p className="empty-state-text">Đường dẫn có thể không đúng.</p>
          <Link to="/home" className="btn btn-primary" style={{ marginTop: 16 }}>
            Về trang chủ
          </Link>
        </div>
      </div>
    );
  }

  const siblings = zonesInCategory(zone.categorySlug);

  return (
    <div className="page inv-page">
      <div className="detail-banner">
        <div
          className="detail-banner-slide detail-banner-slide--active"
          style={{ backgroundImage: `url(${zone.cover})` }}
        />
        <div className="detail-banner-scrim" />
        <div className="detail-banner-content">
          <h1 className="detail-banner-title">{zone.name}</h1>
          <p className="detail-banner-subtitle">{zone.tagline}</p>
        </div>
      </div>

      <Link to={`/inventory/${zone.categorySlug}`} className="detail-back">
        <ArrowLeftIcon size={15} />
        Tất cả phân khu
      </Link>

      {/* Sibling zones stay one click away, so moving between phân khu doesn't
          require going back to the category page first. */}
      {siblings.length > 1 && (
        <nav className="zone-switcher">
          {siblings.map((s) => (
            <Link
              key={s.slug}
              to={`/inventory/${s.categorySlug}/${s.slug}`}
              className={`zone-switcher-item ${s.slug === zone.slug ? "zone-switcher-item--active" : ""}`}
            >
              {s.name}
            </Link>
          ))}
        </nav>
      )}

      <div className="inv-main">{zone.render()}</div>
    </div>
  );
}
