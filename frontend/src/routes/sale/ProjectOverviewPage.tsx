import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../../api/client";
import { fetchProjectDetail, type ProjectFullDetail } from "../../api/projects";
import { useAuth } from "../../hooks/useAuth";
import type { ChatSessionResponse } from "../../types";
import {
  ArrowLeftIcon,
  BuildingHomeIcon,
  ChatIcon,
  CheckIcon,
  LoaderIcon,
  SearchIcon,
  SparkleIcon,
} from "../../components/Icons";

function ProjectBanner({ project }: { project: ProjectFullDetail }) {
  const image = project.coverImage ?? project.gallery[0] ?? null;

  return (
    <div className="detail-banner">
      {image ? (
        <div className="detail-banner-slide detail-banner-slide--active" style={{ backgroundImage: `url(${image})` }} />
      ) : null}
      <div className="detail-banner-scrim" />

      <BuildingHomeIcon size={40} className="detail-banner-icon" />
      <div className="detail-banner-meta">
        <span className="project-card-type">{project.type}</span>
        {project.location && <span className="project-card-location">{project.location}</span>}
      </div>
      <h1 className="detail-banner-title">{project.name}</h1>
    </div>
  );
}

export function ProjectOverviewPage() {
  const { projectId } = useParams();
  const navigate = useNavigate();
  const { role } = useAuth();
  const [project, setProject] = useState<ProjectFullDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [booking, setBooking] = useState(false);

  useEffect(() => {
    if (!projectId) return;
    setLoading(true);
    fetchProjectDetail(projectId)
      .then(setProject)
      .catch(() => setProject(null))
      .finally(() => setLoading(false));
  }, [projectId]);

  const bookViewing = async () => {
    if (!project || booking) return;
    const prefill = `Tôi muốn đặt lịch xem nhà cho ${project.name}.`;

    // Anonymous visitors and Customer accounts have no /sale/sessions access (that
    // endpoint is SALE/ADMIN-only) — they go through the public chat page instead,
    // which lazily creates its own session on the first message. A Sale keeps the
    // existing behaviour of jumping straight into a fresh consultation session.
    if (role !== "sale") {
      navigate("/chat", { state: { prefill } });
      return;
    }

    setBooking(true);
    try {
      const session = await api.post<ChatSessionResponse>("/sale/sessions", {});
      navigate(`/chat/sessions/${session.id}`, { state: { prefill } });
    } finally {
      setBooking(false);
    }
  };

  if (loading) {
    return (
      <div className="page">
        <div className="empty-state">
          <LoaderIcon size={26} className="icon-spin" />
          <p className="empty-state-text empty-state-text--spaced">Đang tải thông tin dự án...</p>
        </div>
      </div>
    );
  }

  if (!project) {
    return (
      <div className="page">
        <div className="empty-state">
          <div className="empty-state-icon">
            <SearchIcon size={26} />
          </div>
          <p className="empty-state-title">Không tìm thấy dự án này</p>
          <p className="empty-state-text">Đường dẫn có thể không đúng, hoặc dự án chưa có dữ liệu.</p>
          <Link to="/home" className="btn btn-primary" style={{ marginTop: 16 }}>
            Về trang chủ
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="page inv-page">
      <ProjectBanner project={project} />

      <Link to="/home" className="detail-back">
        <ArrowLeftIcon size={15} />
        Trang chủ
      </Link>

      <div className="inv-layout">
        <div className="inv-main">
          {project.description && (
            <section className="section-block">
              <h3 className="section-title">Giới thiệu</h3>
              <p className="page-sub" style={{ maxWidth: "none" }}>
                {project.description}
              </p>
              {project.developer && (
                <p className="page-sub" style={{ maxWidth: "none", marginTop: 4 }}>
                  Chủ đầu tư: <strong>{project.developer}</strong>
                </p>
              )}
            </section>
          )}

          {project.gallery.length > 0 && (
            <section className="section-block">
              <h3 className="section-title">Hình ảnh thực tế ({project.gallery.length})</h3>
              <div className="detail-gallery">
                {project.gallery.map((src, i) => (
                  <a key={src} href={src} target="_blank" rel="noreferrer" className="detail-gallery-item">
                    <img src={src} alt={`${project.name} - ảnh ${i + 1}`} loading="lazy" />
                  </a>
                ))}
              </div>
            </section>
          )}

          {project.pricing.length > 0 && (
            <section className="section-block">
              <h3 className="section-title">Bảng giá theo loại hình ({project.pricing.length})</h3>
              <div className="data-list">
                {project.pricing.map((t, i) => (
                  <div key={`${t.apartmentType}-${i}`} className="data-row">
                    <div className="data-row-icon">
                      <BuildingHomeIcon size={16} />
                    </div>
                    <div className="data-row-main">
                      <div className="data-row-title">{t.apartmentType}</div>
                      <div className="data-row-meta">
                        <span>{t.sizeRange}</span>
                        <span>{t.priceRange}</span>
                        {t.storeys && <span>{t.storeys}</span>}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </section>
          )}

          {project.highlights.length > 0 && (
            <section className="section-block">
              <h3 className="section-title">Điểm nổi bật</h3>
              <div className="detail-amenities">
                {project.highlights.map((h) => (
                  <span key={h} className="detail-amenity-chip">
                    <SparkleIcon size={13} />
                    {h}
                  </span>
                ))}
              </div>
            </section>
          )}

          {project.amenities.length > 0 && (
            <section>
              <h3 className="section-title">Tiện ích</h3>
              <div className="detail-amenities">
                {project.amenities.map((a) => (
                  <span key={a} className="detail-amenity-chip">
                    <CheckIcon size={13} />
                    {a}
                  </span>
                ))}
              </div>
            </section>
          )}
        </div>

        <aside className="inv-assist">
          <div className="inv-assist-panel">
            <div className="detail-quickfacts">
              <div className="detail-quickfact-row">
                <span>Dự án</span>
                <strong>{project.name}</strong>
              </div>
              <div className="detail-quickfact-row">
                <span>Loại hình</span>
                <strong>{project.type}</strong>
              </div>
              {project.priceFrom && (
                <div className="detail-quickfact-row">
                  <span>Giá từ</span>
                  <strong>{project.priceFrom}</strong>
                </div>
              )}
              {project.contact?.hotline && (
                <div className="detail-quickfact-row">
                  <span>Hotline</span>
                  <strong>{project.contact.hotline}</strong>
                </div>
              )}
            </div>

            <button
              type="button"
              className="btn btn-primary"
              style={{ width: "100%", marginTop: 16 }}
              onClick={bookViewing}
              disabled={booking}
            >
              {booking ? <LoaderIcon size={16} className="icon-spin" /> : <ChatIcon size={16} />}
              Chat với Auremont AI
            </button>
          </div>
        </aside>
      </div>
    </div>
  );
}
