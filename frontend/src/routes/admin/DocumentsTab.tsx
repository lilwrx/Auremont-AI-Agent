import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../../api/client";
import { AdminMetricCard } from "../../components/admin/AdminMetricCard";
import { AdminPageHeader } from "../../components/admin/AdminPageHeader";
import type {
  DocumentCategory,
  DocumentResponse,
  DocumentVisibility,
  ProjectResponse,
} from "../../types";
import { parseServerDate } from "../../utils/datetime";
import {
  AlertIcon,
  CheckIcon,
  DocumentIcon,
  InboxIcon,
  LoaderIcon,
  RefreshIcon,
  ShieldCheckIcon,
  TrashIcon,
  UploadIcon,
  WorkflowIcon,
  XIcon,
} from "../../components/Icons";

const STATUS_LABEL: Record<
  string,
  { text: string; badge: string }
> = {
  pending: { text: "Đang chờ", badge: "badge-warning" },
  processing: {
    text: "Đang xử lý & quét mã độc",
    badge: "badge-info",
  },
  completed: {
    text: "Upload & Vector hóa thành công",
    badge: "badge-success",
  },
  failed: { text: "Thất bại", badge: "badge-danger" },
  blocked: { text: "Đã chặn — cần kiểm tra", badge: "badge-danger" },
};

function documentStatusLabel(document: DocumentResponse): { text: string; badge: string } {
  if (document.status === "blocked") {
    if (document.block_reason === "duplicate_content") {
      return { text: "Trùng tài liệu", badge: "badge-warning" };
    }
    if (document.block_reason === "prompt_injection") {
      return { text: "Đã chặn — nghi ngờ chỉ thị AI", badge: "badge-danger" };
    }
    return STATUS_LABEL.blocked;
  }
  if (document.status === "completed" && document.review_status === "pending") {
    return { text: "Chờ Admin duyệt metadata", badge: "badge-warning" };
  }
  if (document.status === "completed" && !document.is_current) {
    return { text: "Đang cách ly khỏi AI", badge: "badge-warning" };
  }
  return STATUS_LABEL[document.status] ?? { text: document.status, badge: "badge-muted" };
}

// Shown in the per-row category picker. Ordered by how often an Admin actually corrects to
// them, with "other" last — it is where the classifier puts anything it could not identify,
// and the value a correction is normally moving away from.
const CATEGORY_LABEL: { value: DocumentCategory; text: string }[] = [
  { value: "sales_policy", text: "Chính sách bán hàng" },
  { value: "price_list", text: "Bảng giá" },
  { value: "payment_schedule", text: "Tiến độ thanh toán" },
  { value: "floor_plan", text: "Mặt bằng" },
  { value: "legal_document", text: "Tài liệu pháp lý" },
  { value: "inventory_snapshot", text: "Bảng hàng / tồn kho" },
  { value: "promotion", text: "Ưu đãi / khuyến mãi" },
  { value: "subdivision_info", text: "Thông tin phân khu" },
  { value: "building_info", text: "Thông tin tòa" },
  { value: "contract_template", text: "Hợp đồng mẫu" },
  { value: "internal_guide", text: "Tài liệu nội bộ" },
  { value: "other", text: "Khác — chưa phân loại" },
];

const ALLOWED_EXTENSIONS = [".pdf", ".docx"];

interface UploadResponse {
  document_id: number;
  status: string;
  message: string;
}

function isSupportedFile(file: File): boolean {
  const filename = file.name.toLowerCase();
  return ALLOWED_EXTENSIONS.some((extension) =>
    filename.endsWith(extension),
  );
}

interface UploadQueueItem {
  id: string;
  file: File;
  status: "pending" | "uploading" | "done" | "error";
  message?: string;
}

type DocumentFilter = "all" | "ready" | "review" | "attention";

function isReadyDocument(document: DocumentResponse): boolean {
  return document.status === "completed"
    && document.review_status === "approved"
    && document.is_current;
}

function needsDocumentReview(document: DocumentResponse): boolean {
  return document.review_status === "pending";
}

function needsDocumentAttention(document: DocumentResponse): boolean {
  return document.status === "failed"
    || document.status === "blocked"
    || !document.is_current;
}

export function DocumentsTab() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [documents, setDocuments] = useState<DocumentResponse[]>([]);
  const [queue, setQueue] = useState<UploadQueueItem[]>([]);
  const [dragActive, setDragActive] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [projects, setProjects] = useState<ProjectResponse[]>([]);
  // Which project the uploaded document belongs to. Retrieval filters on this, and
  // conflict detection only compares documents within the same project.
  const [projectId, setProjectId] = useState<string>(() => searchParams.get("project_id") ?? "");
  // Chosen per upload rather than fixed: this used to be hardcoded to "internal", so every
  // document had to be switched over one by one in the table below after the fact.
  const [uploadVisibility, setUploadVisibility] = useState<DocumentVisibility>("internal");
  const [reclassifyingId, setReclassifyingId] = useState<number | null>(null);
  const [documentFilter, setDocumentFilter] = useState<DocumentFilter>("all");
  const categoryFilter = searchParams.get("category") ?? "";
  const coverageScope = searchParams.get("coverage_scope") ?? "";
  const fileInputRef = useRef<HTMLInputElement>(null);
  const scopedDocuments = documents.filter((document) =>
    (!searchParams.get("project_id") || document.project_id === searchParams.get("project_id")) &&
    (!categoryFilter || document.category === categoryFilter)
  );
  const readyDocuments = scopedDocuments.filter(isReadyDocument);
  const reviewDocuments = scopedDocuments.filter(needsDocumentReview);
  const attentionDocuments = scopedDocuments.filter(needsDocumentAttention);
  const filteredDocuments = scopedDocuments.filter((document) => {
    if (documentFilter === "ready") return isReadyDocument(document);
    if (documentFilter === "review") return needsDocumentReview(document);
    if (documentFilter === "attention") return needsDocumentAttention(document);
    return true;
  });

  const uploading = queue.some((item) => item.status === "pending" || item.status === "uploading");

  const loadDocuments = useCallback(() => {
    const query = coverageScope ? `?coverage_scope=${encodeURIComponent(coverageScope)}` : "";
    api
      .get<DocumentResponse[]>(`/documents${query}`)
      .then(setDocuments)
      .catch(() => setDocuments([]));
  }, [coverageScope]);

  useEffect(() => {
    loadDocuments();
  }, [loadDocuments]);

  useEffect(() => {
    api
      .get<ProjectResponse[]>("/projects")
      .then((list) => {
        setProjects(list);
        // Preselect when there is only one project, so the common case needs no clicks.
        if (list.length === 1) setProjectId(list[0].id);
      })
      .catch(() => setProjects([]));
  }, []);

  // Uploaded one at a time, in order — the backend does synchronous work per file (parse,
  // prompt-injection scan, classify, embed), so firing them all in parallel would pile
  // several of those onto the server/LLM API at once for no real benefit; sequential keeps
  // each file's progress legible in the queue below and is no slower in practice for the
  // handful of files an Admin drags in at once.
  const processQueue = useCallback(
    async (items: UploadQueueItem[]) => {
      for (const item of items) {
        if (!isSupportedFile(item.file)) {
          setQueue((prev) =>
            prev.map((q) =>
              q.id === item.id
                ? { ...q, status: "error", message: `Không hỗ trợ "${item.file.name}". Chỉ nhận PDF hoặc DOCX.` }
                : q,
            ),
          );
          continue;
        }

        setQueue((prev) => prev.map((q) => (q.id === item.id ? { ...q, status: "uploading" } : q)));

        try {
          const formData = new FormData();
          formData.append("file", item.file);
          formData.append("visibility", uploadVisibility);
          // Without a project the document cannot be filtered per project at retrieval
          // time, and conflict detection has nothing to compare it against.
          if (projectId) formData.append("project_id", projectId);

          const result = await api.postForm<UploadResponse>("/documents/upload", formData);

          setQueue((prev) =>
            prev.map((q) =>
              q.id === item.id
                ? result.status === "completed"
                  ? { ...q, status: "done", message: result.message }
                  : { ...q, status: "error", message: result.message }
                : q,
            ),
          );
        } catch (err) {
          setQueue((prev) =>
            prev.map((q) =>
              q.id === item.id
                ? { ...q, status: "error", message: err instanceof Error ? err.message : "Upload tài liệu thất bại." }
                : q,
            ),
          );
        }

        loadDocuments();
      }
    },
    [projectId, uploadVisibility, loadDocuments],
  );

  const handleFiles = (files: FileList | null) => {
    if (!files || files.length === 0) {
      return;
    }

    const items: UploadQueueItem[] = Array.from(files).map((file, index) => ({
      id: `${Date.now()}-${index}-${file.name}`,
      file,
      status: "pending",
    }));
    setQueue((prev) => [...prev, ...items]);
    void processQueue(items);
  };

  const clearFinishedQueue = () => {
    setQueue((prev) => prev.filter((item) => item.status === "pending" || item.status === "uploading"));
  };

  // These three all mutate server state. Without a catch, a rejected call threw into an
  // unhandled promise and the Admin saw nothing at all — the row simply stayed as it was,
  // indistinguishable from "nothing happened", while the local list quietly disagreed with
  // the server. State is only updated after the call resolves, so the list stays truthful.
  const setVisibility = async (
    documentId: number,
    visibility: DocumentVisibility,
  ) => {
    setActionError(null);
    try {
      const updated = await api.patch<DocumentResponse>(
        `/documents/${documentId}/visibility`,
        { visibility },
      );

      setDocuments((previous) =>
        previous.map((document) =>
          document.id === documentId ? updated : document,
        ),
      );
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Không đổi được phân quyền tài liệu.");
    }
  };

  // Re-chunks the document from its original file and re-scans it for conflicts, so it is
  // markedly slower than the visibility toggle beside it — hence the per-row busy state.
  const changeCategory = async (documentId: number, category: DocumentCategory) => {
    setActionError(null);
    setReclassifyingId(documentId);
    try {
      const updated = await api.post<DocumentResponse>(`/documents/${documentId}/reclassify`, { category });
      setDocuments((previous) => previous.map((document) => (document.id === documentId ? updated : document)));
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Không đổi được loại tài liệu.");
    } finally {
      setReclassifyingId(null);
    }
  };

  const viewDocument = async (documentId: number) => {
    setActionError(null);
    try {
      const { url } = await api.get<{ url: string }>(`/documents/${documentId}/view-url`);
      window.open(url, "_blank", "noopener,noreferrer");
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Không mở được tài liệu.");
    }
  };

  const removeDocument = async (documentId: number) => {
    setActionError(null);
    try {
      await api.delete(`/documents/${documentId}`);

      setDocuments((previous) =>
        previous.filter((document) => document.id !== documentId),
      );
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Không xóa được tài liệu.");
    }
  };

  return (
    <div className="page admin-dashboard-page business-dashboard admin-workspace admin-documents-page">
      <AdminPageHeader
        eyebrow="Knowledge operations"
        title="Kho Tài liệu"
        description="Tải PDF/DOCX, theo dõi trạng thái xử lý và quản trị nguồn tri thức được phép tham gia RAG."
        actions={
          <>
            <Link className="btn btn-outline" to="/document-relations"><WorkflowIcon size={15} /> Quan hệ phiên bản</Link>
            <Link className="btn btn-primary" to="/document-review"><ShieldCheckIcon size={15} /> Duyệt metadata</Link>
          </>
        }
      />

      {actionError && <div className="alert alert-danger">{actionError}</div>}

      <div className="admin-metric-grid admin-workspace-metrics">
        <AdminMetricCard label="Tổng tài liệu" value={scopedDocuments.length} hint="Trong phạm vi đang xem" icon={<DocumentIcon size={20} />} tooltip="Nhấn để hiển thị toàn bộ tài liệu trong bộ lọc dự án hiện tại." active={documentFilter === "all"} onClick={() => setDocumentFilter("all")} />
        <AdminMetricCard label="Sẵn sàng cho AI" value={readyDocuments.length} hint="Đã duyệt và vector hóa" icon={<CheckIcon size={20} />} tone="success" tooltip="Chỉ gồm tài liệu hiện hành, đã duyệt metadata và xử lý thành công." active={documentFilter === "ready"} onClick={() => setDocumentFilter("ready")} />
        <AdminMetricCard label="Chờ Admin duyệt" value={reviewDocuments.length} hint="Chưa chunk/embedding" icon={<ShieldCheckIcon size={20} />} tone="warning" tooltip="Tài liệu đang cách ly cho tới khi metadata được xác nhận." active={documentFilter === "review"} onClick={() => setDocumentFilter("review")} />
        <AdminMetricCard label="Cần kiểm tra" value={attentionDocuments.length} hint="Lỗi, bị chặn hoặc cách ly" icon={<AlertIcon size={20} />} tone={attentionDocuments.length ? "danger" : "default"} tooltip="Các nguồn chưa thể tham gia trả lời và cần Admin xử lý." active={documentFilter === "attention"} onClick={() => setDocumentFilter("attention")} />
      </div>

      <section className="business-panel admin-ui-panel admin-upload-panel">
        <div className="business-panel-head">
          <div><h3>Nạp tài liệu mới</h3><p>Chọn phạm vi, phân quyền rồi thả nhiều file vào hàng đợi xử lý.</p></div>
          <button type="button" className="business-refresh" onClick={loadDocuments}><RefreshIcon size={15} /> Đồng bộ</button>
        </div>
      <div className="upload-project-row">
        <label htmlFor="upload-project" className="upload-project-label">
          Dự án
        </label>
        <select
          id="upload-project"
          className="upload-project-select"
          value={projectId}
          onChange={(event) => setProjectId(event.target.value)}
        >
          <option value="">— Để AI nhận diện dự án —</option>
          {projects.map((project) => (
            <option key={project.id} value={project.id}>
              {project.name}
            </option>
          ))}
        </select>
        {!projectId && (
          <span className="upload-project-hint">
            AI sẽ đối chiếu tên dự án/phân khu trong tài liệu với danh mục dự án hiện có. Nếu kết quả mơ hồ,
            tài liệu được cách ly và chuyển sang trang Metadata để Admin xác nhận.
          </span>
        )}

        <label htmlFor="upload-visibility" className="upload-project-label">
          Phân quyền
        </label>
        <select
          id="upload-visibility"
          className="upload-project-select"
          value={uploadVisibility}
          onChange={(event) => setUploadVisibility(event.target.value as DocumentVisibility)}
        >
          <option value="internal">Nội bộ — chỉ Sale/Admin</option>
          <option value="public">Public — khách xem được</option>
        </select>
        <span className="upload-project-hint">
          {uploadVisibility === "internal"
            ? "Chỉ Sale và Admin tra cứu được tài liệu này. Khách hỏi qua chat công khai sẽ không thấy."
            : "Khách hỏi qua chat công khai cũng tra cứu được tài liệu này."}
        </span>
      </div>

      <div
        className={`upload-zone ${
          dragActive ? "upload-zone--active" : ""
        }`}
        onDragOver={(event) => {
          event.preventDefault();
          setDragActive(true);
        }}
        onDragLeave={() => setDragActive(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragActive(false);
          handleFiles(event.dataTransfer.files);
        }}
        onClick={() => fileInputRef.current?.click()}
      >
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
          onChange={(event) => {
            handleFiles(event.target.files);
            // Without this, picking the same file(s) again right after (e.g. to retry
            // one that failed) fires no "change" event — the browser dedupes an
            // unchanged file list against its own last value.
            event.target.value = "";
          }}
          style={{ display: "none" }}
        />

        <div className="upload-zone-icon">
          {uploading ? (
            <LoaderIcon size={24} className="icon-spin" />
          ) : (
            <UploadIcon size={24} />
          )}
        </div>

        <p className="upload-zone-title">
          {uploading
            ? "Đang xử lý và đưa vào kho tri thức..."
            : "Kéo thả tài liệu vào đây"}
        </p>

        <p className="upload-zone-hint">
          hoặc bấm để chọn từ máy tính · hỗ trợ PDF và DOCX · chọn/thả được nhiều file cùng lúc
        </p>
      </div>

      {queue.length > 0 && (
        <div className="upload-queue">
          {queue.map((item) => (
            <div key={item.id} className={`upload-queue-item upload-queue-item--${item.status}`}>
              <span className="upload-queue-item-icon">
                {item.status === "pending" || item.status === "uploading" ? (
                  <LoaderIcon size={14} className="icon-spin" />
                ) : item.status === "done" ? (
                  <CheckIcon size={14} />
                ) : (
                  <AlertIcon size={14} />
                )}
              </span>
              <span className="upload-queue-item-name">{item.file.name}</span>
              {item.message && <span className="upload-queue-item-msg">{item.message}</span>}
            </div>
          ))}
          {!uploading && (
            <button type="button" className="btn btn-sm btn-ghost upload-queue-clear" onClick={clearFinishedQueue}>
              <XIcon size={13} />
              Xóa danh sách
            </button>
          )}
        </div>
      )}
      </section>

      <section className="business-panel admin-ui-panel admin-document-list-panel">
        <div className="business-panel-head">
          <div><h3>Danh sách tài liệu</h3><p>
          Sale tra cứu được toàn bộ nội dung trong file, không phụ thuộc loại tài liệu chọn ở đây. Loại tài liệu
          chỉ quyết định cách hệ thống cắt nội dung (bảng giá giữ nguyên hàng, văn bản luật cắt theo Điều/Khoản)
          và cách đối chiếu mâu thuẫn. File gồm nhiều phần thì chọn phần chiếm chính, hoặc để &ldquo;Khác&rdquo;.
          </p></div>
          <span className="admin-count-badge">{filteredDocuments.length} tài liệu</span>
        </div>

        {(searchParams.get("project_id") || coverageScope || categoryFilter) && <div className="document-filter-notice"><span>Đang xem tài liệu được chọn từ dashboard.</span><button type="button" onClick={() => setSearchParams({})}>Xóa bộ lọc</button></div>}

        {filteredDocuments.length === 0 ? (
          <div className="empty-state">
            <div className="empty-state-icon">
              <InboxIcon size={26} />
            </div>
            <p>Chưa có tài liệu nào được tải lên.</p>
          </div>
        ) : (
          <div className="data-list">
            {filteredDocuments.map((document) => {
              const displayStatus = documentStatusLabel(document);

              return (
                <div key={document.id} className="data-row">
                  <div className="data-row-icon"><DocumentIcon size={18} /></div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    {document.file_path ? (
                      <button
                        type="button"
                        className="data-row-title data-row-title--link"
                        onClick={() => void viewDocument(document.id)}
                      >
                        {document.title}
                      </button>
                    ) : (
                      <div className="data-row-title">{document.title}</div>
                    )}
                    <div className="data-row-meta">
                      {parseServerDate(document.created_at).toLocaleString("vi-VN")}
                    </div>
                    {document.security_findings.length > 0 && (
                      <details className="document-security-details">
                        <summary>
                          {document.security_findings.length} cảnh báo kiểm tra nội dung
                        </summary>
                        <ul>
                          {document.security_findings.map((finding, index) => (
                            <li key={`${finding.rule_id}-${finding.page ?? "document"}-${index}`}>
                              <span>
                                {finding.description}
                                {finding.page ? ` · Trang ${finding.page}` : ""}
                              </span>
                              <q>{finding.excerpt}</q>
                            </li>
                          ))}
                        </ul>
                      </details>
                    )}
                  </div>

                  <span className={`badge ${displayStatus.badge}`}>
                    {displayStatus.text}
                  </span>


                  {/* Correcting this re-chunks and re-scans the document — the review tab
                      deliberately refuses category edits, so this is the only way to fix a
                      misclassified upload without deleting and re-uploading it. */}
                  <select
                    className="doc-visibility-select"
                    value={document.category}
                    aria-label="Loại tài liệu"
                    disabled={reclassifyingId !== null}
                    onChange={(event) =>
                      void changeCategory(document.id, event.target.value as DocumentCategory)
                    }
                  >
                    {CATEGORY_LABEL.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.text}
                      </option>
                    ))}
                  </select>

                  <select
                    className="doc-visibility-select"
                    value={document.visibility}
                    aria-label="Phân quyền tài liệu"
                    onChange={(event) =>
                      void setVisibility(
                        document.id,
                        event.target.value as DocumentVisibility,
                      )
                    }
                  >
                    <option value="internal">Nội bộ</option>
                    <option value="public">Public</option>
                  </select>

                  <button
                    className="btn btn-sm btn-danger"
                    type="button"
                    aria-label="Xóa"
                    onClick={() => void removeDocument(document.id)}
                  >
                    <TrashIcon size={14} />
                    Xóa
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}
