import { useEffect, useMemo, useState } from "react";
import type { ChangeEvent, FormEvent } from "react";
import {
  approveNews,
  archiveNews,
  createNewsDraft,
  deleteNewsDraft,
  fetchAdminNews,
  fetchMyNews,
  rejectNews,
  requestNewsChanges,
  submitNewsDraft,
  updateNewsDraft,
  uploadNewsImage,
  type NewsDraftPayload,
  type NewsStatus,
  type NewsTopic,
  type NewsWorkflowArticle,
} from "../api/news";
import {
  AlertTriangleIcon,
  CheckCircleIcon,
  ClockIcon,
  DocumentIcon,
  PlusIcon,
  RefreshIcon,
  TrashIcon,
  UploadCloudIcon,
  XCircleIcon,
} from "../components/Icons";
import { useAuth } from "../hooks/useAuth";

const TOPICS: Array<{ value: NewsTopic; label: string }> = [
  { value: "official_update", label: "Thông tin chính thức" },
  { value: "project_progress", label: "Tiến độ dự án" },
  { value: "infrastructure", label: "Hạ tầng" },
  { value: "market_potential", label: "Tiềm năng phát triển" },
  { value: "promotion", label: "Ưu đãi" },
];

const PROJECTS = ["Vinhomes Ocean Park 1", "Vinhomes Ocean Park 2", "Vinhomes Ocean Park 3"];

const STATUS_META: Record<NewsStatus, { label: string; tone: string }> = {
  draft: { label: "Bản nháp", tone: "neutral" },
  pending_review: { label: "Chờ Admin duyệt", tone: "warning" },
  changes_requested: { label: "Cần chỉnh sửa", tone: "warning" },
  rejected: { label: "Đã từ chối", tone: "danger" },
  published: { label: "Đã xuất bản", tone: "success" },
  archived: { label: "Đã lưu trữ", tone: "neutral" },
};

const EMPTY_DRAFT: NewsDraftPayload = {
  title: "",
  summary: null,
  content: "",
  image_url: null,
  topic: "official_update",
  project_names: [],
};

function formatDate(value: string | null): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat("vi-VN", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function StatusBadge({ status }: { status: NewsStatus }) {
  const meta = STATUS_META[status];
  return <span className={`news-workflow-status news-workflow-status--${meta.tone}`}>{meta.label}</span>;
}

function ArticleQueue({
  items,
  selectedId,
  onSelect,
  emptyText,
}: {
  items: NewsWorkflowArticle[];
  selectedId: number | null;
  onSelect: (article: NewsWorkflowArticle) => void;
  emptyText: string;
}) {
  if (!items.length) {
    return (
      <div className="news-workflow-empty">
        <DocumentIcon size={30} />
        <span>{emptyText}</span>
      </div>
    );
  }
  return (
    <div className="news-workflow-queue-list">
      {items.map((article) => (
        <button
          type="button"
          key={article.id}
          className={`news-workflow-queue-item ${selectedId === article.id ? "is-selected" : ""}`}
          onClick={() => onSelect(article)}
        >
          <div>
            <strong>{article.title}</strong>
            <StatusBadge status={article.status} />
          </div>
          <p>{article.summary || "Chưa có mô tả ngắn."}</p>
          <small><ClockIcon size={12} /> Cập nhật {formatDate(article.updatedAt)}</small>
        </button>
      ))}
    </div>
  );
}

function SummaryCards({ items, admin }: { items: NewsWorkflowArticle[]; admin: boolean }) {
  const values = admin
    ? [
        ["Chờ duyệt", items.filter((item) => item.status === "pending_review").length, "warning"],
        ["Đã xuất bản", items.filter((item) => item.status === "published").length, "success"],
        ["Cần chỉnh sửa", items.filter((item) => item.status === "changes_requested").length, "warning"],
        ["Đã từ chối", items.filter((item) => item.status === "rejected").length, "danger"],
      ]
    : [
        ["Tổng bài của tôi", items.length, "primary"],
        ["Bản nháp", items.filter((item) => item.status === "draft").length, "neutral"],
        ["Đang chờ duyệt", items.filter((item) => item.status === "pending_review").length, "warning"],
        ["Đã xuất bản", items.filter((item) => item.status === "published").length, "success"],
      ];
  return (
    <div className="news-workflow-summary">
      {values.map(([label, value, tone]) => (
        <div className={`news-workflow-stat news-workflow-stat--${tone}`} key={String(label)}>
          <span>{label}</span>
          <strong>{value}</strong>
        </div>
      ))}
    </div>
  );
}

function SaleNewsWorkspace() {
  const [items, setItems] = useState<NewsWorkflowArticle[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [draft, setDraft] = useState<NewsDraftPayload>(EMPTY_DRAFT);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const selected = items.find((item) => item.id === selectedId) ?? null;
  const editable = !selected || ["draft", "changes_requested", "rejected"].includes(selected.status);

  const load = async (keepSelection = true) => {
    setLoading(true);
    setError(null);
    try {
      const result = await fetchMyNews();
      setItems(result.items);
      if (keepSelection && selectedId) {
        const fresh = result.items.find((item) => item.id === selectedId);
        if (fresh) selectArticle(fresh);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Không thể tải danh sách bài viết.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void load(false); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const selectArticle = (article: NewsWorkflowArticle) => {
    setSelectedId(article.id);
    setDraft({
      title: article.title,
      summary: article.summary,
      content: article.content ?? "",
      image_url: article.imageUrl,
      topic: article.topic,
      project_names: article.projectNames,
    });
    setMessage(null);
    setError(null);
  };

  const newDraft = () => {
    setSelectedId(null);
    setDraft(EMPTY_DRAFT);
    setMessage(null);
    setError(null);
  };

  const validate = (): boolean => {
    if (draft.title.trim().length < 5 || draft.content.trim().length < 50) {
      setError("Tiêu đề cần ít nhất 5 ký tự và nội dung cần ít nhất 50 ký tự.");
      return false;
    }
    return true;
  };

  const save = async (): Promise<NewsWorkflowArticle | null> => {
    if (!validate()) return null;
    setSaving(true);
    setError(null);
    try {
      const saved = selectedId
        ? await updateNewsDraft(selectedId, draft)
        : await createNewsDraft(draft);
      setSelectedId(saved.id);
      setMessage("Đã lưu bản nháp.");
      await load(false);
      return saved;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Không thể lưu bài viết.");
      return null;
    } finally {
      setSaving(false);
    }
  };

  const submit = async () => {
    const saved = await save();
    if (!saved) return;
    setSaving(true);
    try {
      await submitNewsDraft(saved.id);
      setMessage("Đã gửi bài cho Admin duyệt.");
      await load(false);
      setSelectedId(saved.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Không thể gửi duyệt.");
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!selected || !window.confirm("Xóa vĩnh viễn bản nháp này?")) return;
    setSaving(true);
    try {
      await deleteNewsDraft(selected.id);
      newDraft();
      await load(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Không thể xóa bài viết.");
    } finally {
      setSaving(false);
    }
  };

  const upload = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      const url = await uploadNewsImage(file);
      setDraft((current) => ({ ...current, image_url: url }));
      setMessage("Đã tải ảnh đại diện lên.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Không thể tải ảnh.");
    } finally {
      setUploading(false);
      event.target.value = "";
    }
  };

  const toggleProject = (project: string) => {
    setDraft((current) => ({
      ...current,
      project_names: current.project_names.includes(project)
        ? current.project_names.filter((item) => item !== project)
        : [...current.project_names, project],
    }));
  };

  const submitForm = (event: FormEvent) => {
    event.preventDefault();
    void save();
  };

  return (
    <>
      <SummaryCards items={items} admin={false} />
      <div className="news-workflow-grid">
        <aside className="news-workflow-queue">
          <div className="news-workflow-panel-head">
            <div><span>BÀI VIẾT CỦA TÔI</span><h2>Quản lý nội dung</h2></div>
            <button type="button" className="news-icon-button" onClick={() => void load()} title="Làm mới"><RefreshIcon size={16} /></button>
          </div>
          <button type="button" className="news-new-button" onClick={newDraft}><PlusIcon size={16} /> Tạo bài viết mới</button>
          {loading ? <div className="news-workflow-loading">Đang tải…</div> : (
            <ArticleQueue items={items} selectedId={selectedId} onSelect={selectArticle} emptyText="Bạn chưa tạo bài viết nào." />
          )}
        </aside>

        <form className="news-editor" onSubmit={submitForm}>
          <div className="news-workflow-panel-head">
            <div><span>TRÌNH SOẠN THẢO</span><h2>{selected ? "Chỉnh sửa bài viết" : "Bài viết mới"}</h2></div>
            {selected && <StatusBadge status={selected.status} />}
          </div>
          {selected?.reviewNote && (
            <div className="news-review-feedback"><AlertTriangleIcon size={17} /><div><strong>Phản hồi từ Admin</strong><p>{selected.reviewNote}</p></div></div>
          )}
          {error && <div className="news-form-message news-form-message--error">{error}</div>}
          {message && <div className="news-form-message news-form-message--success">{message}</div>}

          <fieldset disabled={!editable || saving}>
            <label>Tiêu đề <b>*</b><input value={draft.title} maxLength={500} onChange={(event) => setDraft({ ...draft, title: event.target.value })} placeholder="Tiêu đề rõ ràng, đúng nội dung" /></label>
            <label>Chủ đề<select value={draft.topic} onChange={(event) => setDraft({ ...draft, topic: event.target.value as NewsTopic })}>{TOPICS.map((item) => <option value={item.value} key={item.value}>{item.label}</option>)}</select></label>
            <label>Mô tả ngắn<textarea rows={3} maxLength={2000} value={draft.summary ?? ""} onChange={(event) => setDraft({ ...draft, summary: event.target.value || null })} placeholder="Tóm tắt ngắn hiển thị trên thẻ tin" /></label>
            <label>Nội dung bài viết <b>*</b><textarea className="news-content-input" rows={13} maxLength={50000} value={draft.content} onChange={(event) => setDraft({ ...draft, content: event.target.value })} placeholder="Nhập nội dung chính xác, có thể kiểm chứng…" /><small>{draft.content.length.toLocaleString("vi-VN")} / 50.000 ký tự</small></label>
            <div className="news-project-field"><span>Dự án liên quan</span><div>{PROJECTS.map((project) => <label key={project}><input type="checkbox" checked={draft.project_names.includes(project)} onChange={() => toggleProject(project)} />{project.replace("Vinhomes ", "")}</label>)}</div></div>
            <div className="news-cover-field">
              <label>Ảnh đại diện<input value={draft.image_url ?? ""} onChange={(event) => setDraft({ ...draft, image_url: event.target.value || null })} placeholder="URL ảnh hoặc tải ảnh lên MinIO" /></label>
              <label className="news-upload-button"><UploadCloudIcon size={17} />{uploading ? "Đang tải…" : "Tải ảnh lên"}<input type="file" accept="image/png,image/jpeg,image/webp,image/gif" onChange={(event) => void upload(event)} disabled={uploading} /></label>
            </div>
            {draft.image_url && <img className="news-cover-preview" src={draft.image_url} alt="Xem trước ảnh đại diện" />}
          </fieldset>

          <div className="news-editor-actions">
            {selected && editable && <button type="button" className="btn news-danger-button" onClick={() => void remove()} disabled={saving}><TrashIcon size={15} /> Xóa bản nháp</button>}
            <span />
            {editable && <button type="submit" className="btn btn-secondary" disabled={saving}>{saving ? "Đang lưu…" : "Lưu bản nháp"}</button>}
            {editable && <button type="button" className="btn btn-primary" onClick={() => void submit()} disabled={saving}><CheckCircleIcon size={15} /> Gửi Admin duyệt</button>}
          </div>
        </form>
      </div>
    </>
  );
}

function AdminNewsWorkspace() {
  const [items, setItems] = useState<NewsWorkflowArticle[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [filter, setFilter] = useState<NewsStatus | "">("pending_review");
  const [note, setNote] = useState("");
  const [loading, setLoading] = useState(true);
  const [acting, setActing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selected = items.find((item) => item.id === selectedId) ?? null;
  const visible = useMemo(() => filter ? items.filter((item) => item.status === filter) : items, [items, filter]);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await fetchAdminNews();
      setItems(result.items);
      if (selectedId && !result.items.some((item) => item.id === selectedId)) setSelectedId(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Không thể tải hàng đợi kiểm duyệt.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const runAction = async (action: "approve" | "changes" | "reject" | "archive") => {
    if (!selected) return;
    if ((action === "changes" || action === "reject") && note.trim().length < 3) {
      setError("Hãy nhập lý do ít nhất 3 ký tự để Sale biết cần chỉnh sửa gì.");
      return;
    }
    setActing(true);
    setError(null);
    try {
      if (action === "approve") await approveNews(selected.id, note.trim() || null);
      if (action === "changes") await requestNewsChanges(selected.id, note.trim());
      if (action === "reject") await rejectNews(selected.id, note.trim());
      if (action === "archive") await archiveNews(selected.id, note.trim() || null);
      setSelectedId(null);
      setNote("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Không thể xử lý bài viết.");
    } finally {
      setActing(false);
    }
  };

  return (
    <>
      <SummaryCards items={items} admin />
      <div className="news-workflow-grid">
        <aside className="news-workflow-queue">
          <div className="news-workflow-panel-head">
            <div><span>HÀNG ĐỢI KIỂM DUYỆT</span><h2>Bài viết từ Sale</h2></div>
            <button type="button" className="news-icon-button" onClick={() => void load()} title="Làm mới"><RefreshIcon size={16} /></button>
          </div>
          <select className="news-status-filter" value={filter} onChange={(event) => { setFilter(event.target.value as NewsStatus | ""); setSelectedId(null); }}>
            <option value="">Tất cả trạng thái</option>
            {Object.entries(STATUS_META).map(([value, meta]) => <option value={value} key={value}>{meta.label}</option>)}
          </select>
          {loading ? <div className="news-workflow-loading">Đang tải…</div> : (
            <ArticleQueue items={visible} selectedId={selectedId} onSelect={(article) => { setSelectedId(article.id); setNote(""); setError(null); }} emptyText="Không có bài viết trong trạng thái này." />
          )}
        </aside>

        <section className="news-review-panel">
          {!selected ? (
            <div className="news-workflow-empty news-workflow-empty--large"><CheckCircleIcon size={42} /><h2>Chọn bài viết cần kiểm duyệt</h2><p>Kiểm tra nội dung Sale đã soạn và dự án liên quan trước khi xuất bản.</p></div>
          ) : (
            <>
              <div className="news-workflow-panel-head"><div><span>XEM TRƯỚC BÀI VIẾT #{selected.id}</span><h2>{selected.title}</h2></div><StatusBadge status={selected.status} /></div>
              {error && <div className="news-form-message news-form-message--error">{error}</div>}
              <div className="news-review-meta"><span>Tác giả <strong>{selected.authorName}</strong></span><span>Gửi duyệt <strong>{formatDate(selected.submittedAt)}</strong></span><span>Chủ đề <strong>{TOPICS.find((item) => item.value === selected.topic)?.label}</strong></span></div>
              {selected.imageUrl && <img className="news-review-cover" src={selected.imageUrl} alt="Ảnh đại diện" />}
              {selected.summary && <p className="news-review-summary">{selected.summary}</p>}
              <div className="news-review-content">{selected.content}</div>
              {selected.projectNames.length > 0 && <div className="news-review-projects">{selected.projectNames.map((project) => <span key={project}>{project}</span>)}</div>}
              {selected.reviewNote && <div className="news-review-feedback"><AlertTriangleIcon size={17} /><div><strong>Phản hồi gần nhất</strong><p>{selected.reviewNote}</p></div></div>}
              <label className="news-review-note">Ghi chú cho Sale<textarea rows={3} value={note} onChange={(event) => setNote(event.target.value)} placeholder="Bắt buộc khi yêu cầu sửa hoặc từ chối…" /></label>
              <div className="news-editor-actions news-admin-actions">
                {selected.status === "pending_review" && <>
                  <button type="button" className="btn news-danger-button" disabled={acting} onClick={() => void runAction("reject")}><XCircleIcon size={15} /> Từ chối</button>
                  <span />
                  <button type="button" className="btn btn-secondary" disabled={acting} onClick={() => void runAction("changes")}><AlertTriangleIcon size={15} /> Yêu cầu sửa</button>
                  <button type="button" className="btn btn-primary" disabled={acting} onClick={() => void runAction("approve")}><CheckCircleIcon size={15} /> Duyệt & xuất bản</button>
                </>}
                {selected.status === "published" && <><span /><span /><button type="button" className="btn btn-secondary" disabled={acting} onClick={() => void runAction("archive")}>Lưu trữ bài viết</button></>}
              </div>
            </>
          )}
        </section>
      </div>
    </>
  );
}

export function NewsWorkspacePage() {
  const { role } = useAuth();
  const admin = role === "admin";
  return (
    <main className="news-workflow-page">
      <header className="news-workflow-header">
        <div><span>{admin ? "ADMIN · KIỂM DUYỆT NỘI DUNG" : "SALE · TRUNG TÂM NỘI DUNG"}</span><h1>{admin ? "Duyệt tin tức" : "Đăng tin tức"}</h1><p>{admin ? "Kiểm tra và phê duyệt nội dung trước khi hiển thị trên website." : "Soạn bài, gửi Admin duyệt và theo dõi trạng thái xuất bản."}</p></div>
        <div className="news-workflow-rule"><CheckCircleIcon size={20} /><div><strong>Kiểm duyệt trước khi công khai</strong><span>Chỉ bài được Admin duyệt mới xuất hiện ở trang Tin tức.</span></div></div>
      </header>
      {admin ? <AdminNewsWorkspace /> : <SaleNewsWorkspace />}
    </main>
  );
}
