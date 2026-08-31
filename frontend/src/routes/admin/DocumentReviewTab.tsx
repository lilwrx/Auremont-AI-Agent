import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import { AdminMetricCard } from "../../components/admin/AdminMetricCard";
import { AdminPageHeader } from "../../components/admin/AdminPageHeader";
import type {
  DocumentCategory,
  DocumentClassificationUpdate,
  DocumentReclassificationUpdate,
  DocumentResponse,
  DocumentSectionClassification,
  LegalStatus,
  ProjectResponse,
} from "../../types";
import { AlertIcon, CheckIcon, DocumentIcon, ExternalLinkIcon, InboxIcon, LoaderIcon, RefreshIcon, ShieldCheckIcon } from "../../components/Icons";
import { getDocumentDisplayName } from "../../utils/documentDisplayName";

const CATEGORIES: Array<[DocumentCategory, string]> = [
  ["sales_policy", "Chính sách bán hàng"],
  ["price_list", "Bảng giá"],
  ["inventory_snapshot", "Giỏ hàng / tồn kho"],
  ["subdivision_info", "Thông tin phân khu"],
  ["building_info", "Thông tin tòa"],
  ["floor_plan", "Mặt bằng"],
  ["payment_schedule", "Tiến độ thanh toán"],
  ["promotion", "Ưu đãi / khuyến mại"],
  ["legal_document", "Tài liệu pháp lý"],
  ["contract_template", "Hợp đồng / biểu mẫu"],
  ["internal_guide", "Tài liệu nội bộ"],
  ["other", "Khác"],
];

function asText(values: string[] | null): string {
  return values?.join(", ") ?? "";
}

type ScopeField = "subdivision_names" | "building_codes" | "unit_types";

type ScopeText = Record<ScopeField, string>;
type ProjectCatalogItem = Pick<ProjectResponse, "id" | "name" | "location">;
type ReviewQueueFilter = "pending" | "approved" | "all";

function scopeTextFrom(document: DocumentResponse): ScopeText {
  return {
    subdivision_names: asText(document.subdivision_names),
    building_codes: asText(document.building_codes),
    unit_types: asText(document.unit_types),
  };
}

function asList(value: string): string[] | null {
  const values = [...new Set(value.split(",").map((item) => item.trim()).filter(Boolean))];
  return values.length > 0 ? values : null;
}

function sameList(left: string[] | null, right: string[] | null): boolean {
  const normalise = (values: string[] | null) => [...new Set(
    (values ?? []).map((value) => value.trim().toLocaleLowerCase("vi-VN")).filter(Boolean),
  )].sort();
  return normalise(left).join("\u0000") === normalise(right).join("\u0000");
}

function hasStructuralChanges(
  document: DocumentResponse,
  draft: DocumentReclassificationUpdate,
): boolean {
  return document.category !== draft.category
    || !sameList(document.categories, draft.categories)
    || JSON.stringify(document.section_classifications) !== JSON.stringify(draft.section_classifications)
    || document.project_id !== draft.project_id
    || !sameList(document.subdivision_names, draft.subdivision_names)
    || !sameList(document.building_codes, draft.building_codes)
    || !sameList(document.unit_types, draft.unit_types);
}

function withoutProjectId({
  project_id: _projectId,
  ...payload
}: DocumentReclassificationUpdate): DocumentClassificationUpdate {
  return payload;
}

function payloadFrom(document: DocumentResponse): DocumentReclassificationUpdate {
  return {
    project_id: document.project_id,
    category: document.category,
    categories: document.categories.length ? document.categories : [document.category],
    section_classifications: document.section_classifications,
    subcategory: document.subcategory,
    subdivision_names: document.subdivision_names,
    building_codes: document.building_codes,
    unit_types: document.unit_types,
    applicable_area: document.applicable_area,
    document_summary: document.document_summary,
    version_label: document.version_label,
    issued_date: document.issued_date,
    effective_date: document.effective_date,
    expiry_date: document.expiry_date,
    applicable_period: document.applicable_period,
    legal_document_type: document.legal_document_type,
    legal_document_number: document.legal_document_number,
    legal_issuer: document.legal_issuer,
    legal_domain: document.legal_domain,
    legal_status: document.legal_status,
  };
}

function hasAnyChanges(
  document: DocumentResponse,
  draft: DocumentReclassificationUpdate,
): boolean {
  const original = payloadFrom(document);
  const listFields: ScopeField[] = ["subdivision_names", "building_codes", "unit_types"];
  if (!sameList(original.categories, draft.categories)) return true;
  if (JSON.stringify(original.section_classifications) !== JSON.stringify(draft.section_classifications)) return true;
  if (listFields.some((field) => !sameList(original[field], draft[field]))) return true;

  return (Object.keys(original) as Array<keyof DocumentReclassificationUpdate>).some((field) => {
    if (listFields.includes(field as ScopeField)) return false;
    return original[field] !== draft[field];
  });
}

export function DocumentReviewTab() {
  const [documents, setDocuments] = useState<DocumentResponse[]>([]);
  const [projects, setProjects] = useState<ProjectCatalogItem[]>([]);
  const [selected, setSelected] = useState<DocumentResponse | null>(null);
  const [draft, setDraft] = useState<DocumentReclassificationUpdate | null>(null);
  const [scopeText, setScopeText] = useState<ScopeText>({
    subdivision_names: "",
    building_codes: "",
    unit_types: "",
  });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [openingSource, setOpeningSource] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [queueFilter, setQueueFilter] = useState<ReviewQueueFilter>("pending");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [list, projectList] = await Promise.all([
        api.get<DocumentResponse[]>("/documents/metadata-editable"),
        api.get<ProjectCatalogItem[]>("/documents/project-catalog"),
      ]);
      setDocuments(list);
      setProjects(projectList);
      setSelected((current) => list.find((item) => item.id === current?.id) ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Không tải được danh sách tài liệu.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const select = (document: DocumentResponse) => {
    setSelected(document);
    setDraft(payloadFrom(document));
    setScopeText(scopeTextFrom(document));
    setError(null);
  };

  const update = <K extends keyof DocumentReclassificationUpdate>(key: K, value: DocumentReclassificationUpdate[K]) => {
    setDraft((current) => current ? { ...current, [key]: value } : current);
  };

  const updateScope = (key: ScopeField, value: string) => {
    setScopeText((current) => ({ ...current, [key]: value }));
    update(key, asList(value));
  };

  const updatePrimaryCategory = (category: DocumentCategory) => {
    if (!draft) return;
    update("category", category);
    update("categories", [
      category,
      ...draft.section_classifications.map((section) => section.category),
    ].filter((value, index, values) => values.indexOf(value) === index));
  };

  const updateSectionCategory = (sectionIndex: number, category: DocumentCategory) => {
    if (!draft) return;
    const sections = draft.section_classifications.map((section) =>
      section.section_index === sectionIndex ? { ...section, category } : section
    );
    const categories = [draft.category, ...sections.map((section) => section.category)].filter(
      (value, index, values) => values.indexOf(value) === index,
    );
    update("section_classifications", sections);
    update("categories", categories);
  };

  const save = async () => {
    if (!selected || !draft) return;
    setSaving(true);
    setError(null);
    try {
      let savedDocument: DocumentResponse;
      if (hasStructuralChanges(selected, draft)) {
        savedDocument = await api.post<DocumentResponse>(`/documents/${selected.id}/reclassify`, draft);
      } else {
        savedDocument = await api.patch<DocumentResponse>(
          `/documents/${selected.id}/classification`,
          withoutProjectId(draft),
        );
      }
      setDocuments((current) => savedDocument.status === "completed"
        ? current.map((item) => item.id === savedDocument.id ? savedDocument : item)
        : current.filter((item) => item.id !== savedDocument.id));
      if (savedDocument.status === "completed" && queueFilter !== "pending") {
        setSelected(savedDocument);
        setDraft(payloadFrom(savedDocument));
        setScopeText(scopeTextFrom(savedDocument));
      } else {
        setSelected(null);
        setDraft(null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Không lưu được thay đổi.");
    } finally {
      setSaving(false);
    }
  };

  const openSource = async () => {
    if (!selected?.file_path) return;
    const previewWindow = window.open("about:blank", "_blank");
    if (previewWindow) previewWindow.opener = null;
    setOpeningSource(true);
    setError(null);
    try {
      const { url } = await api.get<{ url: string }>(`/documents/${selected.id}/view-url`);
      if (previewWindow) previewWindow.location.replace(url);
      else window.open(url, "_blank", "noopener,noreferrer");
    } catch (err) {
      previewWindow?.close();
      setError(err instanceof Error ? err.message : "Không mở được tài liệu gốc.");
    } finally {
      setOpeningSource(false);
    }
  };

  const changeQueueFilter = (nextFilter: ReviewQueueFilter) => {
    setQueueFilter(nextFilter);
    setSelected(null);
    setDraft(null);
    setError(null);
  };

  const pendingDocuments = documents.filter((document) => document.review_status === "pending");
  const approvedDocuments = documents.filter((document) => document.review_status === "approved");
  const visibleDocuments = queueFilter === "pending"
    ? pendingDocuments
    : queueFilter === "approved"
      ? approvedDocuments
      : documents;
  const unclassifiedDocuments = pendingDocuments.filter((document) => document.category === "other");
  const lowConfidenceDocuments = pendingDocuments.filter((document) =>
    document.classification_confidence == null || document.classification_confidence < 0.75
  );
  const selectedDisplayName = selected ? getDocumentDisplayName(selected.title) : null;
  const hasChanges = selected && draft ? hasAnyChanges(selected, draft) : false;
  const invalidDateRange = Boolean(
    draft?.effective_date && draft.expiry_date && draft.expiry_date < draft.effective_date,
  );
  const pendingUnclassified = selected?.review_status === "pending" && draft?.category === "other";
  const removesFromAi = draft?.category === "other" || ["not_yet_effective", "expired", "repealed", "replaced"].includes(draft?.legal_status ?? "");
  const saveDisabled = saving || pendingUnclassified || invalidDateRange || (selected?.review_status !== "pending" && !hasChanges);

  return (
    <div className="page admin-dashboard-page business-dashboard admin-workspace admin-review-page">
      <AdminPageHeader
        eyebrow="Knowledge governance"
        title="Duyệt metadata"
        description={<>Xác nhận phạm vi tài liệu trước khi hệ thống chunk, embedding, quét mâu thuẫn và cho phép AI sử dụng.</>}
        actions={
          <>
            <Link className="btn btn-outline" to="/documents"><DocumentIcon size={15} /> Kho tài liệu</Link>
            <button className="business-refresh" type="button" disabled={loading} onClick={() => void load()}><RefreshIcon size={15} className={loading ? "is-spinning" : ""} /> Làm mới</button>
          </>
        }
      />

      {error && <div className="alert alert-danger" style={{ marginTop: 16 }}>{error}</div>}

      <div className="admin-metric-grid admin-workspace-metrics">
        <AdminMetricCard label="Đang chờ duyệt" value={pendingDocuments.length} hint="Nguồn đang được cách ly" icon={<ShieldCheckIcon size={20} />} tone={pendingDocuments.length ? "warning" : "success"} tooltip="Nhấn để xem đúng hàng đợi chưa được đưa vào Qdrant." onClick={() => changeQueueFilter("pending")} active={queueFilter === "pending" && selected == null} />
        <AdminMetricCard label="Chưa phân loại" value={unclassifiedDocuments.length} hint="Metadata loại Khác" icon={<AlertIcon size={20} />} tone={unclassifiedDocuments.length ? "danger" : "success"} tooltip="Tài liệu pending cần chọn loại nghiệp vụ trước khi duyệt." onClick={() => { changeQueueFilter("pending"); const target = unclassifiedDocuments[0]; if (target) select(target); }} active={selected?.review_status === "pending" && selected.category === "other"} />
        <AdminMetricCard label="Độ tin cậy thấp" value={lowConfidenceDocuments.length} hint="Confidence dưới 75%" icon={<AlertIcon size={20} />} tone={lowConfidenceDocuments.length ? "warning" : "success"} tooltip="Tài liệu pending cần ưu tiên kiểm tra phạm vi dự án và loại tài liệu." onClick={() => { changeQueueFilter("pending"); const target = lowConfidenceDocuments[0]; if (target) select(target); }} active={selected?.review_status === "pending" && (selected.classification_confidence == null || selected.classification_confidence < 0.75)} />
        <AdminMetricCard label="Danh mục dự án" value={projects.length} hint="Phạm vi có thể gán" icon={<DocumentIcon size={20} />} tooltip="Danh mục backend dùng để kiểm tra project_id hợp lệ." />
      </div>

      {loading ? (
        <div className="empty-state"><LoaderIcon size={24} className="icon-spin" /><p>Đang tải tài liệu…</p></div>
      ) : documents.length === 0 ? (
        <div className="empty-state"><div className="empty-state-icon"><InboxIcon size={26} /></div><p>Chưa có tài liệu nào đã ingest xong.</p></div>
      ) : (
        <div className="review-layout admin-review-layout">
          <section className="business-panel admin-ui-panel review-queue-panel">
            <div className="business-panel-head review-queue-head"><div><h3>{queueFilter === "pending" ? "Hàng đợi kiểm duyệt" : queueFilter === "approved" ? "Metadata đã duyệt" : "Tất cả tài liệu"}</h3><p>{queueFilter === "pending" ? "Chọn tài liệu để xác nhận đề xuất của LLM." : "Mở lại tài liệu khi cần hiệu chỉnh metadata."}</p></div><span className="admin-count-badge">{visibleDocuments.length}</span></div>
            <div className="admin-segmented review-queue-filter" aria-label="Lọc trạng thái duyệt">
              <button type="button" className={queueFilter === "pending" ? "is-active" : ""} aria-pressed={queueFilter === "pending"} onClick={() => changeQueueFilter("pending")}>Chờ duyệt <span>{pendingDocuments.length}</span></button>
              <button type="button" className={queueFilter === "approved" ? "is-active" : ""} aria-pressed={queueFilter === "approved"} onClick={() => changeQueueFilter("approved")}>Đã duyệt <span>{approvedDocuments.length}</span></button>
              <button type="button" className={queueFilter === "all" ? "is-active" : ""} aria-pressed={queueFilter === "all"} onClick={() => changeQueueFilter("all")}>Tất cả <span>{documents.length}</span></button>
            </div>
            {visibleDocuments.length === 0 ? <div className="review-list-empty"><CheckIcon size={22} /><strong>Không có tài liệu trong nhóm này</strong><span>Chọn nhóm khác để xem hoặc hiệu chỉnh metadata.</span></div> : <div className="data-list review-list">
              {visibleDocuments.map((document) => {
                const displayName = getDocumentDisplayName(document.title);
                return <button className={`review-item ${selected?.id === document.id ? "review-item--active" : ""}`} type="button" key={document.id} onClick={() => select(document)} title={document.title}>
                  <span className="review-item-heading"><span className="data-row-title">{displayName.name}</span>{displayName.extension ? <span className="review-file-type">{displayName.extension}</span> : null}</span>
                  <span className="data-row-meta">
                    {(document.categories.length ? document.categories : [document.category]).map((category) => CATEGORIES.find(([key]) => key === category)?.[1] ?? "Khác").join(" + ")} · {document.classification_confidence !== null ? `${Math.round(document.classification_confidence * 100)}%` : "Chưa rõ"} · {document.review_status === "pending" ? "Cần duyệt" : "Đã duyệt"}
                  </span>
                </button>;
              })}
            </div>}
          </section>

          {selected && draft && (
            <section className="review-form business-panel admin-ui-panel review-editor-panel">
              <div className="business-panel-head review-editor-head"><div><h3 title={selected.title}>{selectedDisplayName?.name}</h3><p>Đối chiếu đề xuất AI với nội dung nguồn trước khi duyệt.</p></div><div className="review-editor-actions">{selected.file_path ? <button className="btn btn-sm btn-outline" type="button" disabled={openingSource} onClick={() => void openSource()}>{openingSource ? <LoaderIcon size={14} className="icon-spin" /> : <ExternalLinkIcon size={14} />} Mở tài liệu gốc</button> : null}<span className="ops-caption-badge">Document #{selected.id}</span></div></div>
              <p className="review-original-name">Tên tệp gốc: <code>{selected.title}</code></p>
              <p className="review-reason">
                Project: <strong>{selected.project_id ?? "Chưa xác định"}</strong> · Bộ phân loại: <strong>{selected.classification_version ?? "Legacy"}</strong>
                {selected.classification_requires_admin_review ? " · LLM yêu cầu Admin kiểm tra" : ""}
              </p>
              {selected.classification_reason && <p className="review-reason">Đề xuất hệ thống: {selected.classification_reason}</p>}
              <p className="review-reason">
                Thay đổi dự án, loại tài liệu hoặc phạm vi conflict sẽ chạy lại luồng xử lý an toàn:
                cách ly tài liệu, lập chỉ mục lại khi cần và quét mâu thuẫn trước khi cho AI sử dụng.
              </p>
              {selected.review_status === "pending" && draft.category === "other" && (
                <div className="alert alert-warning">
                  LLM chưa xác định được loại nghiệp vụ. Hãy chọn một loại tài liệu phù hợp trước khi duyệt.
                </div>
              )}
              <div className="review-grid">
                <label>Dự án<select value={draft.project_id ?? ""} onChange={(event) => update("project_id", event.target.value || null)}>
                  <option value="">Không gắn dự án</option>
                  {draft.project_id && !projects.some((project) => project.id === draft.project_id) && (
                    <option value={draft.project_id}>{draft.project_id}</option>
                  )}
                  {projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
                </select></label>
                <label>Loại tài liệu chính<select value={draft.category} onChange={(event) => updatePrimaryCategory(event.target.value as DocumentCategory)}>{CATEGORIES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
                <label>Phân loại phụ<input value={draft.subcategory ?? ""} onChange={(event) => update("subcategory", event.target.value || null)} /></label>
                <label>Phân khu<input value={scopeText.subdivision_names} placeholder="Phân cách bằng dấu phẩy" onChange={(event) => updateScope("subdivision_names", event.target.value)} /></label>
                <label>Tòa / block<input value={scopeText.building_codes} placeholder="Phân cách bằng dấu phẩy" onChange={(event) => updateScope("building_codes", event.target.value)} /></label>
                <label>Loại căn<input value={scopeText.unit_types} placeholder="Phân cách bằng dấu phẩy" onChange={(event) => updateScope("unit_types", event.target.value)} /></label>
                <label>Phạm vi áp dụng<input value={draft.applicable_area ?? ""} onChange={(event) => update("applicable_area", event.target.value || null)} /></label>
                <label>Ngày ban hành<input type="date" value={draft.issued_date ?? ""} onChange={(event) => update("issued_date", event.target.value || null)} /></label>
                <label>Hiệu lực từ<input type="date" value={draft.effective_date ?? ""} onChange={(event) => update("effective_date", event.target.value || null)} /></label>
                <label>Hết hiệu lực<input type="date" value={draft.expiry_date ?? ""} onChange={(event) => update("expiry_date", event.target.value || null)} /></label>
                <label>Phiên bản<input value={draft.version_label ?? ""} onChange={(event) => update("version_label", event.target.value || null)} /></label>
                <label>Kỳ áp dụng<input value={draft.applicable_period ?? ""} onChange={(event) => update("applicable_period", event.target.value || null)} /></label>
              </div>

              <div className="review-multi-category">
                <div className="review-multi-category-head"><strong>Nội dung có trong tài liệu</strong><span>Tự động tổng hợp từ nhãn của từng section; loại chính luôn được giữ.</span></div>
                <div className="review-category-options">
                  {draft.categories.map((value) => <span key={value} className="is-selected">{CATEGORIES.find(([key]) => key === value)?.[1] ?? value}{value === draft.category ? " · Chính" : ""}</span>)}
                </div>
              </div>

              {draft.section_classifications.length > 0 && <div className="review-sections">
                <div className="review-multi-category-head"><strong>Phân loại theo section</strong><span>Mỗi phần chỉ embedding một lần với category riêng.</span></div>
                <div className="review-section-list">
                  {draft.section_classifications.map((section: DocumentSectionClassification) => <article key={section.section_index} className="review-section-item">
                    <div><strong>Section #{section.section_index + 1}{section.page ? ` · Trang ${section.page}` : ""}</strong><span>{section.content_type === "table" ? "Bảng" : "Văn bản"} · {Math.round(section.confidence * 100)}%</span></div>
                    <select value={section.category} onChange={(event) => updateSectionCategory(section.section_index, event.target.value as DocumentCategory)}>{CATEGORIES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
                    <p>{section.excerpt || section.reason || "Không có nội dung xem trước."}</p>
                  </article>)}
                </div>
              </div>}

              {draft.category === "legal_document" && <div className="review-grid review-grid--legal">
                <label>Loại văn bản<input value={draft.legal_document_type ?? ""} onChange={(event) => update("legal_document_type", event.target.value || null)} /></label>
                <label>Số hiệu<input value={draft.legal_document_number ?? ""} onChange={(event) => update("legal_document_number", event.target.value || null)} /></label>
                <label>Cơ quan ban hành<input value={draft.legal_issuer ?? ""} onChange={(event) => update("legal_issuer", event.target.value || null)} /></label>
                <label>Lĩnh vực<input value={draft.legal_domain ?? ""} onChange={(event) => update("legal_domain", event.target.value || null)} /></label>
                <label>Trạng thái pháp lý<select value={draft.legal_status} onChange={(event) => update("legal_status", event.target.value as LegalStatus)}><option value="unknown">Chưa xác định</option><option value="not_yet_effective">Chưa hiệu lực</option><option value="effective">Đang hiệu lực</option><option value="expired">Hết hiệu lực</option><option value="repealed">Bị bãi bỏ</option><option value="replaced">Bị thay thế</option></select></label>
              </div>}

              <label className="review-summary">Tóm tắt<textarea value={draft.document_summary ?? ""} onChange={(event) => update("document_summary", event.target.value || null)} rows={4} /></label>
              {invalidDateRange ? <div className="alert alert-warning">Ngày hết hiệu lực phải bằng hoặc sau ngày bắt đầu hiệu lực.</div> : null}
              <button className="btn btn-primary review-save-button" type="button" onClick={() => void save()} disabled={saveDisabled}>{saving ? <LoaderIcon size={16} className="icon-spin" /> : <CheckIcon size={16} />} {pendingUnclassified ? "Chọn loại tài liệu trước" : invalidDateRange ? "Kiểm tra lại thời gian hiệu lực" : selected.review_status !== "pending" && !hasChanges ? "Chưa có thay đổi" : removesFromAi ? "Lưu và đưa ra khỏi phạm vi AI" : selected.review_status === "pending" ? "Duyệt, chunk và embedding" : "Lưu thay đổi"}</button>
            </section>
          )}
          {!selected && (
            <section className="business-panel admin-ui-panel review-editor-panel review-editor-empty">
              <ShieldCheckIcon size={30} />
              <strong>Chọn tài liệu cần xác nhận</strong>
              <span>Metadata, phạm vi và lý do phân loại sẽ xuất hiện tại đây.</span>
            </section>
          )}
        </div>
      )}
    </div>
  );
}
