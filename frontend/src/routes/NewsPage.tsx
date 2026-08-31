import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Link } from "react-router-dom";
import { fetchNews, type NewsArticle, type NewsTopic } from "../api/news";
import {
  BuildingHomeIcon,
  ClockIcon,
  ExternalLinkIcon,
  GlobeIcon,
  PlusIcon,
  RefreshIcon,
  SearchIcon,
} from "../components/Icons";
import { useAuth } from "../hooks/useAuth";

const PAGE_SIZE = 12;

const TOPICS: Array<{ value: NewsTopic | ""; label: string }> = [
  { value: "", label: "Tất cả" },
  { value: "official_update", label: "Thông tin chính thức" },
  { value: "project_progress", label: "Tiến độ dự án" },
  { value: "infrastructure", label: "Hạ tầng" },
  { value: "market_potential", label: "Tiềm năng phát triển" },
  { value: "promotion", label: "Ưu đãi" },
];

const TOPIC_LABELS = Object.fromEntries(TOPICS.filter((item) => item.value).map((item) => [item.value, item.label]));

function formatDate(value: string | null, fallback: string): string {
  return new Intl.DateTimeFormat("vi-VN", { day: "2-digit", month: "2-digit", year: "numeric" }).format(
    new Date(value ?? fallback),
  );
}

function ArticleImage({ article, featured = false }: { article: NewsArticle; featured?: boolean }) {
  const [failed, setFailed] = useState(false);
  if (!article.imageUrl || failed) {
    return (
      <div className={`news-image news-image--fallback ${featured ? "news-image--featured" : ""}`}>
        <BuildingHomeIcon size={featured ? 54 : 38} />
        <span>Tin đã kiểm duyệt</span>
      </div>
    );
  }
  return (
    <div className={`news-image ${featured ? "news-image--featured" : ""}`}>
      <img src={article.imageUrl} alt="" loading="lazy" referrerPolicy="no-referrer" onError={() => setFailed(true)} />
    </div>
  );
}

function NewsMeta({ article }: { article: NewsArticle }) {
  return (
    <div className="news-card-meta">
      <span className="news-source"><GlobeIcon size={13} />Sale Auremont đăng</span>
      <span><ClockIcon size={13} />{formatDate(article.publishedAt, article.fetchedAt)}</span>
    </div>
  );
}

function NewsCard({ article }: { article: NewsArticle }) {
  return (
    <Link className="news-card" to={`/news/${article.id}`}>
      <ArticleImage article={article} />
      <div className="news-card-body">
        <NewsMeta article={article} />
        <span className="news-topic">{TOPIC_LABELS[article.topic]}</span>
        <h2>{article.title}</h2>
        {article.summary && <p>{article.summary}</p>}
        {article.projectNames.length > 0 && (
          <div className="news-projects">
            {article.projectNames.slice(0, 3).map((project) => <span key={project}>{project}</span>)}
          </div>
        )}
        <span className="news-read-more">Đọc bài viết <ExternalLinkIcon size={14} /></span>
      </div>
    </Link>
  );
}

export function NewsPage() {
  const { isAuthenticated, role } = useAuth();
  const [items, setItems] = useState<NewsArticle[]>([]);
  const [total, setTotal] = useState(0);
  const [topic, setTopic] = useState<NewsTopic | "">("");
  const [queryInput, setQueryInput] = useState("");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async (offset = 0) => {
    if (offset === 0) setLoading(true);
    else setLoadingMore(true);
    setError(null);
    try {
      const result = await fetchNews({ offset, limit: PAGE_SIZE, topic: topic || undefined, query });
      setItems((current) => offset === 0 ? result.items : [...current, ...result.items]);
      setTotal(result.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Không thể tải tin tức lúc này.");
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
  };

  useEffect(() => {
    void load(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [topic, query]);

  const submitSearch = (event: FormEvent) => {
    event.preventDefault();
    setQuery(queryInput.trim());
  };

  const featured = items[0];
  const remaining = items.slice(1);

  return (
    <main className="news-page">
      <section className="news-hero">
        <div>
          <span className="news-eyebrow"><GlobeIcon size={15} /> Trung tâm tin tức Auremont</span>
          <h1>Tin tức bất động sản<br /><em>đã được kiểm duyệt</em></h1>
          <p>Cập nhật dự án Vinhomes, hạ tầng, chính sách và tiềm năng phát triển. Nội dung do đội ngũ Sale biên soạn và được Admin kiểm tra trước khi xuất bản.</p>
          {isAuthenticated && (role === "sale" || role === "admin") && (
            <Link className="news-manage-cta" to="/news-workspace"><PlusIcon size={16} />{role === "admin" ? "Mở hàng đợi duyệt" : "Đăng tin mới"}</Link>
          )}
        </div>
        <div className="news-trust-card">
          <span>QUY TRÌNH XÁC MINH</span>
          <strong>Sale biên soạn · Admin phê duyệt</strong>
          <p>Bản nháp và bài đang chờ duyệt không xuất hiện trên website.</p>
        </div>
      </section>

      <section className="news-toolbar" aria-label="Bộ lọc tin tức">
        <div className="news-topic-list">
          {TOPICS.map((item) => (
            <button type="button" key={item.value || "all"} className={topic === item.value ? "is-active" : ""} onClick={() => setTopic(item.value)}>{item.label}</button>
          ))}
        </div>
        <form className="news-search" onSubmit={submitSearch}>
          <SearchIcon size={16} />
          <input value={queryInput} onChange={(event) => setQueryInput(event.target.value)} placeholder="Tìm dự án, chủ đề…" aria-label="Tìm tin tức" />
          <button type="submit">Tìm</button>
        </form>
      </section>

      {error && <div className="news-state news-state--error"><p>{error}</p><button type="button" onClick={() => void load(0)}><RefreshIcon size={15} /> Thử lại</button></div>}
      {loading && <div className="news-grid" aria-label="Đang tải tin tức">{Array.from({ length: 6 }).map((_, index) => <div className="news-skeleton" key={index} />)}</div>}
      {!loading && !error && !featured && <div className="news-state"><GlobeIcon size={42} /><h2>Chưa có tin phù hợp</h2><p>Chưa có bài viết đã duyệt cho bộ lọc này.</p></div>}

      {!loading && !error && featured && (
        <>
          <Link className="news-featured" to={`/news/${featured.id}`}>
            <ArticleImage article={featured} featured />
            <div className="news-featured-body">
              <span className="news-featured-label">TIN MỚI NHẤT</span>
              <NewsMeta article={featured} />
              <h2>{featured.title}</h2>
              {featured.summary && <p>{featured.summary}</p>}
              <span className="news-read-more">Đọc bài viết <ExternalLinkIcon size={15} /></span>
            </div>
          </Link>
          <div className="news-section-heading"><div><span>MỚI CẬP NHẬT</span><h2>Các tin tức khác</h2></div><strong>{total} bản tin</strong></div>
          <div className="news-grid">{remaining.map((article) => <NewsCard key={article.id} article={article} />)}</div>
          {items.length < total && <button className="news-load-more" type="button" disabled={loadingMore} onClick={() => void load(items.length)}>{loadingMore ? "Đang tải…" : "Xem thêm tin tức"}</button>}
        </>
      )}
    </main>
  );
}
