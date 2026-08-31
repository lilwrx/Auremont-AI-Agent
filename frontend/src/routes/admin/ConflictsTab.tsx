import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import { AdminMetricCard } from "../../components/admin/AdminMetricCard";
import { AdminPageHeader } from "../../components/admin/AdminPageHeader";
import { AlertIcon, CheckIcon, DocumentIcon, ExternalLinkIcon, ScaleIcon, ShieldCheckIcon } from "../../components/Icons";
import type { ConflictDetail, ConflictDocumentSummary } from "../../types/admin";
import { parseServerDate } from "../../utils/datetime";

type ConflictFilter = "all" | ConflictDetail["severity"];

const severityMeta: Record<ConflictDetail["severity"], { label: string; description: string }> = {
  low: { label: "Mức thấp", description: "Cần xác minh thêm trước khi kết luận." },
  medium: { label: "Mức trung bình", description: "Mâu thuẫn đã có tín hiệu rõ và cần xử lý sớm." },
  high: { label: "Mức nghiêm trọng", description: "Mâu thuẫn tác động cao hoặc đã được xác nhận chắc chắn." },
};

const severityRank: Record<ConflictDetail["severity"], number> = { low: 1, medium: 2, high: 3 };

function detectorLabel(method: ConflictDetail["detection_method"]) {
  if (method === "llm") return "LLM ngữ nghĩa";
  if (method === "hybrid") return "Rule + LLM";
  return "Rule xác định";
}

function evidenceForSide(conflict: ConflictDetail, side: "a" | "b") {
  const quotes = (conflict.evidence?.semantic?.evidence ?? [])
    .map((item) => side === "a" ? item.quote_a : item.quote_b)
    .filter(Boolean);
  const rule = conflict.evidence?.rule;
  for (const item of rule?.price_differences ?? []) {
    const values = side === "a" ? item.document_a : item.document_b;
    quotes.push(`${item.fact_key}: ${values.map((value) => new Intl.NumberFormat("vi-VN").format(value)).join(" / ")} VNĐ`);
  }
  for (const item of rule?.fact_differences ?? []) {
    const values = side === "a" ? item.document_a : item.document_b;
    quotes.push(`${item.fact_key}: ${values.join(" / ")}`);
  }
  return [...new Set(quotes)];
}

function DocumentPane({ label, document, conflict, evidence, onOpen }: { label: string; document: ConflictDocumentSummary; conflict: string | null; evidence: string[]; onOpen: () => void }) {
  return <article className="conflict-document-pane">
    <header><span>{label}</span><button type="button" className="admin-icon-button" onClick={onOpen} aria-label={`Mở ${document.title}`}><ExternalLinkIcon size={16} /></button></header>
    <div className="conflict-document-body">
      <div className="conflict-document-title"><small>Tài liệu #{document.id}</small><h3>{document.title}</h3></div>
      <dl className="conflict-document-meta"><div><dt>Phiên bản</dt><dd>{document.version_label ?? "Không ghi nhận"}</dd></div><div><dt>Hiệu lực</dt><dd>{document.effective_date ?? document.issued_date ?? "Không ghi nhận"}</dd></div><div><dt>Phân loại</dt><dd>{document.category}</dd></div><div><dt>Quyền xem</dt><dd>{document.visibility}</dd></div></dl>
      <div className="conflict-copy"><span>Tóm tắt nguồn</span><p>{document.summary ?? document.classification_reason ?? "Tài liệu chưa có bản tóm tắt để hiển thị."}</p></div>
      <div className="conflict-highlight"><span>Bằng chứng được đánh dấu</span><div className="conflict-highlight-list">{evidence.length > 0 ? evidence.map((quote, index) => <mark key={`${document.id}-${index}`}>{quote}</mark>) : <mark>{conflict ?? "Hệ thống ghi nhận hai tài liệu có thông tin không nhất quán."}</mark>}</div></div>
    </div>
  </article>;
}

export function ConflictsTab() {
  const [conflicts, setConflicts] = useState<ConflictDetail[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [resolving, setResolving] = useState<number | null>(null);
  const [manualId, setManualId] = useState<number | null>(null);
  const [filter, setFilter] = useState<ConflictFilter>("all");

  useEffect(() => {
    api.get<ConflictDetail[]>("/admin/conflicts").then((rows) => { setConflicts(rows); setError(null); }).catch(() => { setError("Không tải được danh sách mâu thuẫn."); setConflicts([]); });
  }, []);

  const resolve = async (conflictId: number, keepDocumentId: number) => {
    setError(null);
    setResolving(conflictId);
    try {
      await api.post(`/admin/conflicts/${conflictId}/resolve`, { keep_document_id: keepDocumentId });
      setConflicts((previous) => previous?.filter((conflict) => conflict.id !== conflictId) ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Không xử lý được mâu thuẫn này.");
    } finally {
      setResolving(null);
    }
  };

  const dismiss = async (conflictId: number) => {
    setError(null);
    setResolving(conflictId);
    try {
      await api.post(`/admin/conflicts/${conflictId}/dismiss`, {});
      setConflicts((previous) => previous?.filter((conflict) => conflict.id !== conflictId) ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Không đóng được cảnh báo này.");
    } finally {
      setResolving(null);
    }
  };

  const openDocument = async (documentId: number) => {
    try {
      const { url } = await api.get<{ url: string }>(`/documents/${documentId}/view-url`);
      window.open(url, "_blank", "noopener,noreferrer");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Không mở được tài liệu.");
    }
  };

  const allConflicts = conflicts ?? [];
  const lowCount = allConflicts.filter((conflict) => conflict.severity === "low").length;
  const mediumCount = allConflicts.filter((conflict) => conflict.severity === "medium").length;
  const highCount = allConflicts.filter((conflict) => conflict.severity === "high").length;
  const visibleConflicts = [...allConflicts]
    .filter((conflict) => filter === "all" || conflict.severity === filter)
    .sort((left, right) => severityRank[right.severity] - severityRank[left.severity]);

  return <div className="page admin-dashboard-page business-dashboard admin-workspace admin-conflicts-page">
    <AdminPageHeader eyebrow="Knowledge governance" title="Cảnh báo mâu thuẫn tài liệu" description="So sánh hai nguồn độc lập trước khi quyết định phiên bản được phép tham gia RAG." actions={<Link className="btn btn-outline" to="/documents"><DocumentIcon size={15} /> Kho tài liệu</Link>} />
    {error && <div className="alert alert-danger">{error}</div>}

    <div className="admin-metric-grid admin-workspace-metrics">
      <AdminMetricCard label="Cảnh báo đang mở" value={allConflicts.length} hint="Sắp xếp đỏ → cam → vàng" icon={<AlertIcon size={20} />} tone={highCount ? "danger" : mediumCount ? "caution" : lowCount ? "warning" : "success"} tooltip="Nhấn để hiển thị tất cả cảnh báo theo thứ tự ưu tiên." active={filter === "all"} onClick={() => setFilter("all")} />
      <AdminMetricCard label="Mức thấp · Vàng" value={lowCount} hint="Cần xác minh thêm" icon={<ScaleIcon size={20} />} tone="warning" tooltip={severityMeta.low.description} active={filter === "low"} onClick={() => setFilter("low")} />
      <AdminMetricCard label="Mức trung bình · Cam" value={mediumCount} hint="Cần xử lý sớm" icon={<AlertIcon size={20} />} tone="caution" tooltip={severityMeta.medium.description} active={filter === "medium"} onClick={() => setFilter("medium")} />
      <AdminMetricCard label="Mức nghiêm trọng · Đỏ" value={highCount} hint="Ưu tiên xử lý ngay" icon={<ShieldCheckIcon size={20} />} tone="danger" tooltip={severityMeta.high.description} active={filter === "high"} onClick={() => setFilter("high")} />
    </div>

    {conflicts === null ? <div className="admin-empty">Đang tải cảnh báo…</div> : allConflicts.length === 0 ? <div className="ops-empty-state"><CheckIcon size={26} /><strong>Không có mâu thuẫn cần xử lý</strong><span>Kho tri thức hiện không có cặp nguồn đang tranh chấp.</span></div> : visibleConflicts.length === 0 ? <div className="ops-empty-state compact"><CheckIcon size={24} /><strong>Không có cảnh báo khớp bộ lọc</strong><span>Chọn thẻ “Cảnh báo đang mở” để xem toàn bộ.</span></div> : <div className="conflict-list">{visibleConflicts.map((conflict) => <section className={`conflict-compare conflict-compare--${conflict.severity} admin-ui-panel`} key={conflict.id} aria-labelledby={`conflict-title-${conflict.id}`}>
      <header className="conflict-compare-head"><div><span className="conflict-alert-title"><AlertIcon size={17} /> Conflict #{conflict.id}</span><h2 id={`conflict-title-${conflict.id}`}>{conflict.project_name ?? conflict.project_id ?? "Tài liệu áp dụng chung"}</h2></div><div className="conflict-badges"><span className={`conflict-severity-badge conflict-severity-badge--${conflict.severity}`} title={severityMeta[conflict.severity].description}>{severityMeta[conflict.severity].label}</span><span>Nguồn: {detectorLabel(conflict.detection_method)}</span>{conflict.evidence?.semantic?.decision === "uncertain" && <span className="is-uncertain">Cần Admin xác minh</span>}{conflict.evidence?.semantic?.decision === "conflict" && <span className="is-confirmed">Có bằng chứng mâu thuẫn</span>}{conflict.confidence != null && <span>Độ tin cậy: {Math.round(conflict.confidence * 100)}%</span>}{conflict.similarity_score != null && <span>Similarity: {Math.round(conflict.similarity_score * 100)}%</span>}{conflict.conflict_type && <span>Loại: {conflict.conflict_type}</span>}<span>Phát hiện {parseServerDate(conflict.created_at).toLocaleDateString("vi-VN")}</span><span>{conflict.project_name ?? "Toàn hệ thống"}</span></div></header>
      {conflict.evidence?.semantic?.summary && <p className="conflict-analysis-summary">{conflict.evidence.semantic.summary}</p>}
      <div className="conflict-split"><DocumentPane label="Tài liệu A · nguồn cũ" document={conflict.document_a} conflict={conflict.description} evidence={evidenceForSide(conflict, "a")} onOpen={() => void openDocument(conflict.document_a.id)} /><DocumentPane label="Tài liệu B · nguồn mới" document={conflict.document_b} conflict={conflict.description} evidence={evidenceForSide(conflict, "b")} onOpen={() => void openDocument(conflict.document_b.id)} /></div>
      {manualId === conflict.id && <div className="manual-merge-note"><ScaleIcon size={19} /><div><strong>Quy trình gộp/chỉnh sửa thủ công</strong><p>Mở hai bản nguồn, tạo hoặc tải bản đã chỉnh sửa vào Kho tài liệu, rồi quay lại chọn tài liệu thắng. Cảnh báo vẫn mở để không vô tình đưa hai nguồn mâu thuẫn vào retrieval.</p></div><div><button className="btn btn-sm btn-outline" onClick={() => void openDocument(conflict.document_a.id)}>Mở A</button><button className="btn btn-sm btn-outline" onClick={() => void openDocument(conflict.document_b.id)}>Mở B</button><Link className="btn btn-sm btn-primary" to="/documents">Đến Kho tài liệu</Link></div></div>}
      <footer className="conflict-compare-actions"><span>{conflict.evidence?.semantic?.decision === "uncertain" ? "AI chưa kết luận mâu thuẫn. Hãy mở hai nguồn và xác minh trước khi chọn." : "Chọn một nguồn sẽ chặn nguồn còn lại khỏi RAG."}</span><div><button className="btn btn-outline" type="button" disabled={resolving === conflict.id} onClick={() => void resolve(conflict.id, conflict.document_a.id)}>Chấp nhận Bản A</button><button className="btn btn-primary" type="button" disabled={resolving === conflict.id} onClick={() => void resolve(conflict.id, conflict.document_b.id)}>Chấp nhận Bản B</button><button className="btn btn-outline" type="button" disabled={resolving === conflict.id} onClick={() => void dismiss(conflict.id)}><CheckIcon size={15} /> Giữ cả 2 file</button><button className="btn btn-outline" type="button" onClick={() => setManualId((value) => value === conflict.id ? null : conflict.id)}><ScaleIcon size={15} /> Gộp/Chỉnh sửa thủ công</button></div></footer>
    </section>)}</div>}
  </div>;
}
