import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { CategoryCard } from "../components/CategoryCard";
import { PricingSection } from "../components/PricingSection";
import { FloorPlanTabs } from "./sale/inventory/shared";
import { fetchCategories, fetchProjectOverview } from "../api/projects";
import type { ProjectOverview } from "../api/projects";
import type { CategorySummary } from "../types/project";
import {
  ArrowRightIcon,
  ChatIcon,
  DatabaseIcon,
  LayersIcon,
  SearchIcon,
  ShieldCheckIcon,
  SparklesIcon,
} from "../components/Icons";

const HERO_IMAGE_URL =
  "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/vinhomes-ocean-park/masteri-grand-coast-bg-homepage.jpg";

const OVERVIEW_IMAGE_URL =
  "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/vinhomes-ocean-park/masterise-vinhomes-ocean-park-night.jpg";

const PROJECT_IMG = "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/vinhomes-ocean-park";

const MASTER_PLAN_TABS = [
  { label: "Mặt bằng phân khu", src: `${PROJECT_IMG}/mat-bang-phan-khu-vinhomes-ocean-park.jpg` },
  { label: "Mặt bằng tiện ích", src: `${PROJECT_IMG}/mat-bang-tien-ich-ocean-park-2048x1024.jpg` },
  { label: "Phân khu chung cư", src: `${PROJECT_IMG}/cac-phan-khu-chung-cu-vinhomes-ocean-park.jpg` },
  { label: "Tổng thể dự án", src: `${PROJECT_IMG}/tong-the-vinhomes-ocean-park.jpg` },
  { label: "Vị trí dự án", src: `${PROJECT_IMG}/vi-tri-vinhomes-ocean-park-moi.jpg` },
  { label: "Kết nối vùng", src: `${PROJECT_IMG}/ket-noi-vung-vinhomes-ocean-park-1.jpg` },
];

const MAP_EMBED_SRC = "https://www.google.com/maps?q=Vinhomes+Ocean+Park,+Gia+L%C3%A2m,+H%C3%A0+N%E1%BB%99i&output=embed";

const STATS = [
  { label: "Luôn sẵn sàng trả lời 24/7", icon: <ChatIcon size={18} /> },
  { label: "Tồn kho cập nhật tức thời", icon: <DatabaseIcon size={18} /> },
  { label: "Luôn có nguồn trích dẫn", icon: <LayersIcon size={18} /> },
  { label: "Kiểm chứng trước khi gửi khách", icon: <ShieldCheckIcon size={18} /> },
];

const FEATURES = [
  {
    title: "Tìm đúng thông tin trong kho tài liệu",
    desc: "Auremont hiểu ngữ cảnh câu hỏi và tìm đúng đoạn thông tin liên quan nhất trong bảng giá, mặt bằng, chính sách bán hàng — không cần nhớ chính xác từ khoá.",
    iconClass: "fi-emerald",
    icon: <SearchIcon size={22} />,
  },
  {
    title: "Tồn kho cập nhật theo thời gian thực",
    desc: "Mọi câu trả lời về tình trạng căn đều lấy trực tiếp từ hệ thống tồn kho tại thời điểm hỏi, không dùng dữ liệu cũ đã lưu sẵn.",
    iconClass: "fi-accent-2",
    icon: <LayersIcon size={22} />,
  },
  {
    title: "Trả lời tức thì, kèm nguồn trích dẫn",
    desc: "AI tổng hợp câu trả lời rõ ràng và luôn dẫn tới đúng tài liệu gốc, giúp bạn kiểm tra lại nhanh chóng khi cần.",
    iconClass: "fi-accent",
    icon: <SparklesIcon size={22} />,
  },
  {
    title: "Kiểm chứng trước khi gửi khách",
    desc: "Câu trả lời liên quan tới giá hoặc cam kết sẽ được hệ thống tự kiểm tra và yêu cầu bạn xác nhận trước khi gửi, tránh sai sót đáng tiếc.",
    iconClass: "fi-teal",
    icon: <ShieldCheckIcon size={22} />,
  },
];

// Home page for SALE only — ADMIN uses AdminHome (the admin dashboard) instead.
export function Home() {
  const { username } = useAuth();
  const location = useLocation();
  const [categories, setCategories] = useState<CategorySummary[]>([]);
  const [overview, setOverview] = useState<ProjectOverview | null>(null);

  useEffect(() => {
    fetchCategories().then(setCategories).catch(() => setCategories([]));
    fetchProjectOverview().then(setOverview).catch(() => setOverview(null));
  }, []);

  // Arriving here fresh with a hash (e.g. from Footer's "Tra cứu dự án" link on another
  // page) is a full client-side navigation, not a same-page click — the browser's native
  // "jump to #id" behavior only fires on a real page load, so React Router landing here
  // needs its own scroll-into-view once the section exists in the DOM.
  useEffect(() => {
    if (!location.hash) return;
    const id = location.hash.slice(1);
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [location.hash]);

  const actions = [
    {
      to: "/chat",
      icon: <ChatIcon size={22} />,
      title: "Chat với Auremont AI",
      desc: "Hỏi nhanh về bảng giá, mặt bằng và tồn kho",
      primary: true,
    },
    {
      // Scrolls straight to the "Project lookup" section on this same page instead
      // of navigating away, since that section already lives here (see onClick below).
      to: "#tra-cuu-du-an",
      icon: <SearchIcon size={22} />,
      title: "Tra cứu dự án",
      desc: "Xem danh sách phân khu, mặt bằng và bảng giá từng loại hình",
      primary: false,
    },
  ];

  const scrollToProjectLookup = (e: React.MouseEvent) => {
    e.preventDefault();
    document.getElementById("tra-cuu-du-an")?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  return (
    <div className="home home-compact">
      <section className="hero home-hero">
        <div
          className="hero-media"
          style={{ "--hero-image-url": `url(${HERO_IMAGE_URL})` } as React.CSSProperties}
        />
        <div className="hero-grid" />

        <div className="container hero-inner">
          <h1 className="hero-title">
            Mọi thông tin,
            <br />
            một chạm
          </h1>

          <p className="hero-subtitle">
            Chào {username ?? "bạn"}, giá bán, mặt bằng, tồn kho — không cần lục nhiều nguồn, mọi thứ ở ngay đây.
          </p>

          <div className="hero-nav-cards home-action-grid">
            {actions.map((a) => (
              <Link
                key={a.to}
                to={a.to}
                onClick={a.to.startsWith("#") ? scrollToProjectLookup : undefined}
                className={`hero-nav-card ${a.primary ? "hero-nav-card--primary" : ""}`}
              >
                <div className="hero-nav-card-icon">{a.icon}</div>
                <div>
                  <p className="hero-nav-card-title">{a.title}</p>
                  <p className="hero-nav-card-desc">{a.desc}</p>
                </div>
                <ArrowRightIcon size={16} className="hero-nav-card-arrow" />
              </Link>
            ))}
          </div>
        </div>
      </section>

      <PricingSection />

      {overview && (
        <section className="home-intro">
          <div className="container home-intro-grid">
            <div className="home-intro-text">
              <h2 className="home-intro-title">{overview.name.toUpperCase()}</h2>
              <p className="home-intro-desc">{overview.description}</p>

              {overview.highlights.length > 0 && (
                <ul className="home-intro-list">
                  {overview.highlights.slice(0, 6).map((h) => {
                    const [lead, ...rest] = h.split(" - ");
                    const restText = rest.join(" - ");
                    return (
                      <li key={h}>
                        <strong>{lead}</strong>
                        {restText ? ` - ${restText}` : ""}
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>

            <div className="home-intro-media">
              <img
                src={OVERVIEW_IMAGE_URL}
                alt={overview.name}
                onError={(e) => {
                  e.currentTarget.style.display = "none";
                  e.currentTarget.parentElement?.classList.add("home-intro-media--fallback");
                }}
              />
            </div>
          </div>
        </section>
      )}

      <section className="home-plan">
        <div className="container">
          <h2 className="home-intro-title">Tổng mặt bằng dự án</h2>
          <p className="home-intro-desc">
            Với quy mô diện tích 420 ha, Vinhomes Ocean Park được quy hoạch thành 2 phân khu chức năng chính:
          </p>
          <ul className="home-intro-list home-plan-list">
            <li>
              <strong>Khu chung cư:</strong> khoảng 66 tòa căn hộ, chia thành nhiều phân khu theo từng giai đoạn.
            </li>
            <li>
              <strong>Khu thấp tầng:</strong> khoảng gần 3.000 căn biệt thự, liền kề, shophouse và shop thương mại
              dịch vụ.
            </li>
          </ul>
          <FloorPlanTabs title="Quy hoạch & Vị trí" tabs={MASTER_PLAN_TABS} />
        </div>
      </section>

      <section className="home-map">
        <div className="home-map-banner">
          <p className="home-map-title">Bản đồ giao thông Vinhomes Ocean Park</p>
        </div>
        <div className="container">
          <div className="home-map-frame">
            <iframe
              src={MAP_EMBED_SRC}
              title="Bản đồ vị trí Vinhomes Ocean Park"
              loading="lazy"
              referrerPolicy="no-referrer-when-downgrade"
            />
          </div>
        </div>
      </section>

      <section className="home-featured" id="tra-cuu-du-an">
        <div className="container">
          <div className="home-featured-head">
            <div>
              <p className="section-eyebrow">Tra cứu dự án</p>
              <h2 className="home-section-title">Loại hình sản phẩm</h2>
            </div>
            <Link to="/inventory/chung-cu" className="home-featured-viewall">
              Xem toàn bộ danh sách
              <ArrowRightIcon size={14} />
            </Link>
          </div>
          <div className="inv-grid">
            {categories.map((c) => (
              <CategoryCard key={c.slug} category={c} />
            ))}
          </div>
        </div>
      </section>

      <section className="home-summary">
        <div className="container home-summary-inner">
          <div className="home-stats-row">
            {STATS.map((s) => (
              <div key={s.label} className="home-stat-pill">
                <span className="home-stat-icon">{s.icon}</span>
                <span>{s.label}</span>
              </div>
            ))}
          </div>

          <div className="home-feature-panel">
            <div className="home-feature-head">
              <p className="section-eyebrow">Cách Auremont hỗ trợ bạn</p>
              <h2 className="home-section-title">Bốn điều Auremont làm cho bạn</h2>
              <p className="section-subtitle">
                Không chỉ tìm theo từ khoá — Auremont hiểu ngữ cảnh câu hỏi, đối chiếu tồn kho thực tế và tự kiểm
                chứng câu trả lời trước khi đưa tới bạn.
              </p>
            </div>

            <div className="home-feature-grid">
              {FEATURES.map((f) => (
                <article key={f.title} className="home-feature-item">
                  <div className={`feature-icon-wrap ${f.iconClass}`}>{f.icon}</div>
                  <div>
                    <h3 className="feature-title">{f.title}</h3>
                    <p className="feature-desc">{f.desc}</p>
                  </div>
                </article>
              ))}
            </div>
          </div>
        </div>
      </section>

      <section className="home-cta">
        <div className="container home-cta-inner">
          <div>
            <p className="section-eyebrow">Bắt đầu ngay</p>
            <h2 className="home-cta-title">Chưa biết bắt đầu từ đâu? Hỏi Auremont AI</h2>
            <p className="home-cta-desc">
              Mô tả nhu cầu khách hàng, Auremont gợi ý dự án phù hợp và tra cứu tồn kho tức thời cho bạn.
            </p>
          </div>
          <Link to="/chat" className="btn btn-primary home-cta-btn">
            Mở trợ lý AI
          </Link>
        </div>
      </section>
    </div>
  );
}
