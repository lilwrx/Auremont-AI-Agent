import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { fetchAllProjects, type ProjectListItem } from "../../api/projects";
import { findGroup } from "../../types/catalog";
import { ArrowLeftIcon, BuildingHomeIcon, LoaderIcon, SearchIcon, SparkleIcon } from "../../components/Icons";

export function CatalogGroupPage() {
  const { groupSlug } = useParams();
  const [projects, setProjects] = useState<ProjectListItem[] | null>(null);

  useEffect(() => {
    fetchAllProjects()
      .then(setProjects)
      .catch(() => setProjects([]));
  }, []);

  const found = groupSlug ? findGroup(groupSlug) : undefined;

  if (!found) {
    return (
      <div className="page">
        <div className="empty-state">
          <div className="empty-state-icon">
            <SearchIcon size={26} />
          </div>
          <p className="empty-state-title">Không tìm thấy nhóm dự án này</p>
          <Link to="/home" className="btn btn-primary" style={{ marginTop: 16 }}>
            Về trang chủ
          </Link>
        </div>
      </div>
    );
  }

  const { mega, category, group } = found;

  if (projects === null) {
    return (
      <div className="page">
        <div className="empty-state">
          <LoaderIcon size={26} className="icon-spin" />
          <p className="empty-state-text empty-state-text--spaced">Đang tải...</p>
        </div>
      </div>
    );
  }

  const byId = new Map(projects.map((p) => [p.id, p]));

  return (
    <div className="page inv-page">
      <Link to={`/inventory/${category.slug}`} className="detail-back">
        <ArrowLeftIcon size={15} />
        {category.name}
      </Link>

      <div className="page-head">
        <div>
          <h2 className="page-title">{group.name}</h2>
          <p className="page-sub">
            {mega.name} · {category.name}
          </p>
        </div>
      </div>

      {group.projects.every((p) => !p.projectId) ? (
        <div className="empty-state">
          <div className="empty-state-icon">
            <SparkleIcon size={26} />
          </div>
          <p className="empty-state-title">Chưa có dữ liệu</p>
          <p className="empty-state-text">Phân khu này đang chờ cập nhật dữ liệu, quay lại sau nhé.</p>
        </div>
      ) : (
        <div className="inv-grid">
          {group.projects.map((p) => {
            const data = p.projectId ? byId.get(p.projectId) : undefined;
            if (!data) {
              return (
                <div key={p.name} className="project-card project-card--disabled" style={{ cursor: "default" }}>
                  <div className="project-card-media" style={{ background: "linear-gradient(135deg, #0050ef, #0a2e7a)" }}>
                    <BuildingHomeIcon size={30} className="project-card-media-icon" />
                  </div>
                  <div className="project-card-body">
                    <div className="project-card-meta">
                      <span className="project-card-type">Chưa có dữ liệu</span>
                    </div>
                    <h3 className="project-card-title">{p.name}</h3>
                  </div>
                </div>
              );
            }
            const media = data.coverImage
              ? { backgroundImage: `url(${data.coverImage})`, backgroundSize: "cover", backgroundPosition: "center" }
              : { background: "linear-gradient(135deg, #0050ef, #0a2e7a)" };
            return (
              <Link key={data.id} to={`/inventory/project/${data.id}`} className="project-card">
                <div className="project-card-media" style={media}>
                  {!data.coverImage && <BuildingHomeIcon size={30} className="project-card-media-icon" />}
                </div>
                <div className="project-card-body">
                  <div className="project-card-meta">
                    <span className="project-card-type">{data.type}</span>
                  </div>
                  <h3 className="project-card-title">{data.name}</h3>
                  {data.priceFrom && (
                    <div className="project-card-footer">
                      <div>
                        <span className="project-card-price-label">Giá từ</span>
                        <strong className="project-card-price">{data.priceFrom}</strong>
                      </div>
                    </div>
                  )}
                </div>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
