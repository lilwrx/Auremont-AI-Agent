import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { fetchNewsArticle, type NewsArticle } from "../api/news";
import { ClockIcon, GlobeIcon } from "../components/Icons";

const TOPIC_LABELS: Record<string, string> = {
  official_update: "Thông tin chính thức",
  project_progress: "Tiến độ dự án",
  infrastructure: "Hạ tầng",
  market_potential: "Tiềm năng phát triển",
  promotion: "Ưu đãi",
};

function formatDate(value: string | null, fallback: string): string {
  return new Intl.DateTimeFormat("vi-VN", { day: "2-digit", month: "2-digit", year: "numeric" }).format(
    new Date(value ?? fallback),
  );
}

export function NewsDetailPage() {
  const { articleId } = useParams();
  const [article, setArticle] = useState<NewsArticle | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const id = Number(articleId);
    if (!Number.isInteger(id) || id <= 0) {
      setError("Đường dẫn bài viết không hợp lệ.");
      setLoading(false);
      return;
    }
    fetchNewsArticle(id)
      .then(setArticle)
      .catch((err) => setError(err instanceof Error ? err.message : "Không thể tải bài viết."))
      .finally(() => setLoading(false));
  }, [articleId]);

  if (loading) return <main className="news-detail-page"><div className="news-state">Đang tải bài viết…</div></main>;
  if (error || !article) return <main className="news-detail-page"><div className="news-state news-state--error"><p>{error || "Không tìm thấy bài viết."}</p><Link to="/news">Quay lại Tin tức</Link></div></main>;

  return (
    <main className="news-detail-page">
      <Link className="news-detail-back" to="/news">← Quay lại Tin tức</Link>
      <article className="news-detail-article">
        <header>
          <span className="news-topic">{TOPIC_LABELS[article.topic]}</span>
          <h1>{article.title}</h1>
          <div className="news-card-meta">
            <span className="news-source"><GlobeIcon size={14} />Sale Auremont đăng</span>
            <span><ClockIcon size={14} />{formatDate(article.publishedAt, article.fetchedAt)}</span>
          </div>
          {article.projectNames.length > 0 && <div className="news-projects">{article.projectNames.map((project) => <span key={project}>{project}</span>)}</div>}
        </header>
        {article.imageUrl && <img className="news-detail-cover" src={article.imageUrl} alt="" />}
        {article.summary && <p className="news-detail-summary">{article.summary}</p>}
        <div className="news-detail-content">{article.content}</div>
      </article>
    </main>
  );
}
