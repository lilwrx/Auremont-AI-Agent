import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { api } from "../../api/client";
import type {
  LegacyReclassificationCandidate,
  ReclassificationApplyItem,
  ReclassificationApplyResponse,
  ReclassificationPreviewItem,
  ReclassificationPreviewResponse,
} from "../../types/admin";
import { CheckIcon, LoaderIcon, SparklesIcon, XIcon } from "../Icons";

const MAX_DOCUMENTS = 20;

interface ProjectCatalogItem {
  id: string;
  name: string;
  location: string | null;
}

interface Props {
  open: boolean;
  onClose: () => void;
  onApplied: () => void;
}

const FIELD_LABELS: Record<string, string> = {
  category: "Loại tài liệu",
  subcategory: "Loại phụ",
  subdivision_names: "Phân khu",
  building_codes: "Tòa / block",
  unit_types: "Loại căn",
  applicable_area: "Phạm vi áp dụng",
  document_summary: "Tóm tắt",
  version_label: "Phiên bản",
  issued_date: "Ngày ban hành",
  effective_date: "Ngày hiệu lực",
  expiry_date: "Ngày hết hiệu lực",
  applicable_period: "Kỳ áp dụng",
  legal_status: "Trạng thái pháp lý",
  classification_confidence: "Độ tin cậy",
  classification_reason: "Lý do phân loại",
  conflict_facts: "Các fact dùng đối chiếu mâu thuẫn",
};

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : "Không thể thực hiện yêu cầu phân loại lại.";
}

function displayValue(value: unknown): string {
  if (value == null || value === "") return "—";
  if (Array.isArray(value)) {
    if (!value.length) return "—";
    if (value.some((item) => typeof item === "object" && item !== null)) return `${value.length} fact`;
    return value.join(", ");
  }
  if (typeof value === "boolean") return value ? "Có" : "Không";
  if (typeof value === "object") return JSON.stringify(value);
  const text = String(value);
  return text.length > 180 ? `${text.slice(0, 177)}…` : text;
}

function initialDecision(item: ReclassificationPreviewItem): string {
  const resolution = item.project_resolution;
  if (resolution?.recommended_project_id && resolution.recommended_project_id !== resolution.stored_project_id) {
    return `assign:${resolution.recommended_project_id}`;
  }
  return "keep";
}

export function LegacyReclassificationModal({ open, onClose, onApplied }: Props) {
  const [candidates, setCandidates] = useState<LegacyReclassificationCandidate[]>([]);
  const [projects, setProjects] = useState<ProjectCatalogItem[]>([]);
  const [preview, setPreview] = useState<ReclassificationPreviewResponse | null>(null);
  const [confirmedIds, setConfirmedIds] = useState<number[]>([]);
  const [decisions, setDecisions] = useState<Record<number, string>>({});
  const [result, setResult] = useState<ReclassificationApplyResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    setPreview(null);
    setResult(null);
    setCandidates([]);
    setConfirmedIds([]);
    setDecisions({});
    setWorking(true);
    Promise.all([
      api.get<LegacyReclassificationCandidate[]>(`/documents/llm-reclassification/candidates?legacy_only=false&pending_only=true&limit=${MAX_DOCUMENTS}`),
      api.get<ProjectCatalogItem[]>("/documents/project-catalog"),
    ])
      .then(async ([candidateRows, projectRows]) => {
        if (cancelled) return;
        setCandidates(candidateRows);
        setProjects(projectRows);
        if (candidateRows.length === 0) return;

        const response = await api.post<ReclassificationPreviewResponse>(
          "/documents/llm-reclassification/preview",
          { document_ids: candidateRows.map((item) => item.document_id) },
        );
        if (cancelled) return;
        setPreview(response);
        setDecisions(Object.fromEntries(response.items.map((item) => [item.document_id, initialDecision(item)])));
      })
      .catch((requestError) => !cancelled && setError(messageOf(requestError)))
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
          setWorking(false);
        }
      });
    return () => { cancelled = true; };
  }, [open, reloadKey]);

  useEffect(() => {
    if (!open) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const closeOnEscape = (event: KeyboardEvent) => event.key === "Escape" && !working && onClose();
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [open, onClose, working]);

  if (!open) return null;

  const applyConfirmed = async () => {
    if (!preview) return;
    const items: ReclassificationApplyItem[] = [];
    for (const item of preview.items) {
      if (!confirmedIds.includes(item.document_id) || !item.confirmation_token) continue;
      const decision = decisions[item.document_id] ?? "keep";
      items.push(decision.startsWith("assign:")
        ? { confirmation_token: item.confirmation_token, project_action: "assign", project_id: decision.slice(7) }
        : { confirmation_token: item.confirmation_token, project_action: decision === "clear" ? "clear" : "keep" });
    }
    if (!items.length) {
      setError("Hãy xác nhận ít nhất một kết quả trước khi áp dụng.");
      return;
    }
    setWorking(true);
    setError(null);
    try {
      const response = await api.post<ReclassificationApplyResponse>(
        "/documents/llm-reclassification/apply",
        { confirmation: "APPLY_LLM_RECLASSIFICATION", items },
      );
      setResult(response);
      if (response.applied > 0) onApplied();
    } catch (requestError) {
      setError(messageOf(requestError));
    } finally {
      setWorking(false);
    }
  };

  return createPortal(
    <div className="admin-modal-backdrop" role="presentation" onMouseDown={() => !working && onClose()}>
      <section className="legacy-reclass-modal" role="dialog" aria-modal="true" aria-labelledby="legacy-reclass-title" onMouseDown={(event) => event.stopPropagation()}>
        <header className="legacy-reclass-head">
          <div><span className="admin-eyebrow">Knowledge base governance</span><h2 id="legacy-reclass-title">Phân loại lại tài liệu chưa duyệt</h2><p>Hệ thống tự lấy tối đa {MAX_DOCUMENTS} tài liệu đang chờ Admin duyệt và tạo bản xem trước. Metadata chỉ được ghi sau khi Admin xác nhận.</p></div>
          <button className="admin-icon-button" type="button" onClick={onClose} disabled={working} aria-label="Đóng"><XIcon size={19} /></button>
        </header>

        <div className="legacy-reclass-body">
          {error && <div className="legacy-reclass-alert" role="alert">{error}</div>}

          {!preview && !result && <>
            {loading ? <div className="legacy-reclass-empty"><LoaderIcon size={24} />{candidates.length > 0 ? `AI đang phân loại ${candidates.length} tài liệu chưa duyệt…` : "Đang kiểm tra tài liệu chờ duyệt…"}</div>
              : !error && candidates.length === 0 ? <div className="legacy-reclass-empty"><CheckIcon size={25} />Không có tài liệu nào đang chờ Admin duyệt.</div>
                : error ? <div className="legacy-reclass-empty">Không thể tạo bản xem trước. Bạn có thể thử lại mà không làm thay đổi dữ liệu.</div>
                  : null}
          </>}

          {preview && !result && <>
            <div className="legacy-reclass-summary"><span><strong>{preview.previewed}</strong> thành công</span><span><strong>{preview.failed}</strong> thất bại</span><span><strong>{confirmedIds.length}</strong> đã xác nhận</span></div>
            <div className="legacy-preview-list">{preview.items.map((item) => <PreviewCard key={item.document_id} item={item} projects={projects} confirmed={confirmedIds.includes(item.document_id)} decision={decisions[item.document_id] ?? "keep"} onConfirm={(checked) => setConfirmedIds((current) => checked ? [...current, item.document_id] : current.filter((id) => id !== item.document_id))} onDecision={(decision) => setDecisions((current) => ({ ...current, [item.document_id]: decision }))} />)}</div>
          </>}

          {result && <><div className="legacy-reclass-summary"><span><strong>{result.applied}</strong> đã áp dụng</span><span><strong>{result.failed}</strong> thất bại</span></div><div className="legacy-result-list">{result.items.map((item, index) => <div className={`legacy-result-row ${item.error ? "is-error" : "is-success"}`} key={item.document_id ?? index}>{item.error ? <XIcon size={17} /> : <CheckIcon size={17} />}<div><strong>{item.title ?? `Tài liệu #${item.document_id ?? "—"}`}</strong><small>{item.error ?? `${item.category} · ${item.project_id ?? "chưa gán dự án"} · ${item.status}`}</small></div>{!item.error && item.duplicate_document_ids.length > 0 && <span className="badge badge-warning">Trùng {item.duplicate_document_ids.length} bản</span>}{!item.error && item.conflict_ids.length > 0 && <span className="badge badge-danger">{item.conflict_ids.length} mâu thuẫn</span>}</div>)}</div></>}
        </div>

        <footer className="legacy-reclass-actions">
          {!preview && !result && <><button className="btn btn-outline" type="button" disabled={working} onClick={onClose}>Đóng</button>{error && <button className="btn btn-primary" type="button" disabled={working} onClick={() => setReloadKey((value) => value + 1)}><SparklesIcon size={16} />Thử lại</button>}</>}
          {preview && !result && <><button className="btn btn-outline" type="button" disabled={working} onClick={() => setReloadKey((value) => value + 1)}>Chạy lại AI</button><button className="btn btn-primary" type="button" disabled={working || confirmedIds.length === 0} onClick={() => void applyConfirmed()}>{working ? <LoaderIcon size={16} /> : <CheckIcon size={16} />}{working ? "Đang áp dụng…" : `Áp dụng ${confirmedIds.length} tài liệu`}</button></>}
          {result && <button className="btn btn-primary" type="button" onClick={onClose}>Hoàn tất</button>}
        </footer>
      </section>
    </div>,
    document.body,
  );
}

interface PreviewCardProps {
  item: ReclassificationPreviewItem;
  projects: ProjectCatalogItem[];
  confirmed: boolean;
  decision: string;
  onConfirm: (checked: boolean) => void;
  onDecision: (decision: string) => void;
}

function PreviewCard({ item, projects, confirmed, decision, onConfirm, onDecision }: PreviewCardProps) {
  const resolution = item.project_resolution;
  const confidence = typeof item.suggestion?.confidence === "number" ? item.suggestion.confidence : null;
  const conflictFacts = Array.isArray(item.suggestion?.conflict_facts)
    ? item.suggestion.conflict_facts.filter((fact): fact is Record<string, unknown> => Boolean(fact && typeof fact === "object"))
    : [];
  const canApply = Boolean(item.confirmation_token && !item.error);
  return <article className={`legacy-preview-card ${item.error ? "is-error" : ""}`}>
    <header><div><strong>{item.title}</strong><small>#{item.document_id} · {Object.keys(item.changes).length} metadata thay đổi</small></div>{canApply && <label className="legacy-confirm-check"><input type="checkbox" checked={confirmed} onChange={(event) => onConfirm(event.target.checked)} />Xác nhận áp dụng</label>}</header>
    {item.error ? <div className="legacy-preview-error">{item.error}</div> : <>
      <div className="legacy-classification-compare"><div><span>Metadata hiện tại</span><b>{displayValue(item.changes.category?.stored ?? item.suggestion?.category)}</b><small>{resolution?.stored_project_id ?? "Chưa gán dự án"}</small></div><div><span>LLM đề xuất</span><b>{displayValue(item.suggestion?.category)}</b><small>{resolution?.llm_project_id ?? "Không xác định dự án"}</small></div><div><span>Độ tin cậy</span><b>{confidence == null ? "—" : `${Math.round(confidence * 100)}%`}</b><small className={item.suggestion?.requires_admin_review === true ? "is-warning" : "is-safe"}>{item.suggestion?.requires_admin_review === true ? "Cần Admin kiểm tra" : "Không có cờ cảnh báo"}</small></div></div>
      {resolution?.warning && <div className="legacy-project-warning">{resolution.warning}</div>}
      <label className="legacy-project-decision"><span>Dự án sẽ được lưu</span><select value={decision} onChange={(event) => onDecision(event.target.value)}><option value="keep">Giữ hiện tại ({resolution?.stored_project_id ?? "trống"})</option><option value="clear">Không gán dự án</option>{projects.map((project) => <option value={`assign:${project.id}`} key={project.id}>Gán: {project.name}</option>)}</select></label>
      <details className="legacy-fact-details" open={conflictFacts.length > 0 && conflictFacts.length <= 3}>
        <summary>Fact LLM dùng để phát hiện mâu thuẫn ({conflictFacts.length})</summary>
        {conflictFacts.length === 0
          ? <p>LLM không tìm thấy assertion đủ bằng chứng trong tài liệu này.</p>
          : <div className="legacy-fact-list">{conflictFacts.map((fact, index) => <article key={`${String(fact.fact_key ?? "fact")}-${index}`}><div><strong>{displayValue(fact.fact_key)}</strong>{fact.value != null && <span>{displayValue(fact.value)}{fact.unit ? ` ${displayValue(fact.unit)}` : ""}</span>}</div><p>{displayValue(fact.claim)}</p><small>Phạm vi: {displayValue(fact.scope)} · Hiệu lực: {displayValue(fact.effective_period)}</small><blockquote>{displayValue(fact.evidence)}</blockquote></article>)}</div>}
      </details>
      {Object.keys(item.changes).length > 0 && <details className="legacy-change-details"><summary>Xem toàn bộ metadata thay đổi</summary><div>{Object.entries(item.changes).map(([field, change]) => <div className="legacy-change-row" key={field}><strong>{FIELD_LABELS[field] ?? field}</strong><span title={displayValue(change.stored)}>{displayValue(change.stored)}</span><span title={displayValue(change.suggested)}>{displayValue(change.suggested)}</span></div>)}</div></details>}
    </>}
  </article>;
}
