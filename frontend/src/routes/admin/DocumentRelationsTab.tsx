import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import { AdminMetricCard } from "../../components/admin/AdminMetricCard";
import { AdminPageHeader } from "../../components/admin/AdminPageHeader";
import type { DocumentRelationResponse, DocumentRelationType, DocumentResponse } from "../../types";
import { CheckIcon, DocumentIcon, LoaderIcon, RefreshIcon, WorkflowIcon, XIcon } from "../../components/Icons";

const RELATIONS: Array<[DocumentRelationType, string]> = [
  ["replaces", "Thay thế hoàn toàn"],
  ["supersedes", "Thay phiên bản cũ"],
  ["updates", "Cập nhật"],
  ["amends", "Sửa đổi / bổ sung"],
  ["repeals", "Bãi bỏ"],
  ["guides", "Hướng dẫn thi hành"],
  ["related_to", "Liên quan"],
];

export function DocumentRelationsTab() {
  const [documents, setDocuments] = useState<DocumentResponse[]>([]);
  const [relations, setRelations] = useState<DocumentRelationResponse[]>([]);
  const [sourceId, setSourceId] = useState("");
  const [targetId, setTargetId] = useState("");
  const [relationType, setRelationType] = useState<DocumentRelationType>("replaces");
  const [scopeNote, setScopeNote] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const names = useMemo(() => new Map(documents.map((item) => [item.id, item.title])), [documents]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [documentList, relationList] = await Promise.all([
        api.get<DocumentResponse[]>("/documents"),
        api.get<DocumentRelationResponse[]>("/document-relations?pending_only=true"),
      ]);
      setDocuments(documentList);
      setRelations(relationList);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Không tải được quan hệ tài liệu.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const create = async () => {
    if (!sourceId || !targetId) {
      setError("Hãy chọn cả tài liệu mới và tài liệu cũ.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const relation = await api.post<DocumentRelationResponse>("/document-relations", {
        source_document_id: Number(sourceId),
        target_document_id: Number(targetId),
        relation_type: relationType,
        scope_note: scopeNote || null,
      });
      setRelations((current) => [relation, ...current]);
      setTargetId("");
      setScopeNote("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Không tạo được quan hệ.");
    } finally {
      setSaving(false);
    }
  };

  const review = async (relationId: number, approve: boolean) => {
    setSaving(true);
    setError(null);
    try {
      await api.post<DocumentRelationResponse>(`/document-relations/${relationId}/review`, { approve });
      setRelations((current) => current.filter((item) => item.id !== relationId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Không thể xử lý quan hệ này.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="page admin-dashboard-page business-dashboard admin-workspace admin-relations-page">
      <AdminPageHeader
        eyebrow="Document lifecycle"
        title="Quan hệ tài liệu"
        description="Xác nhận tài liệu cập nhật, thay thế hoặc bãi bỏ nguồn cũ để giữ RAG nhất quán theo phiên bản."
        actions={<><Link className="btn btn-outline" to="/documents"><DocumentIcon size={15} /> Kho tài liệu</Link><button className="business-refresh" type="button" disabled={loading} onClick={() => void load()}><RefreshIcon size={15} className={loading ? "is-spinning" : ""} /> Làm mới</button></>}
      />
      {error && <div className="alert alert-danger" style={{ marginTop: 16 }}>{error}</div>}

      <div className="admin-metric-grid admin-workspace-metrics settings-metric-grid">
        <AdminMetricCard label="Tài liệu có thể liên kết" value={documents.length} hint="Nguồn trong kho" icon={<DocumentIcon size={20} />} tooltip="Tổng tài liệu backend trả về cho việc thiết lập quan hệ." />
        <AdminMetricCard label="Chờ duyệt" value={relations.length} hint="Quan hệ chưa có hiệu lực" icon={<WorkflowIcon size={20} />} tone={relations.length ? "warning" : "success"} tooltip="Nguồn cũ chưa bị loại khỏi RAG cho tới khi quan hệ được duyệt." />
        <AdminMetricCard label="Loại quan hệ" value={RELATIONS.length} hint="Quy tắc vòng đời hỗ trợ" icon={<CheckIcon size={20} />} tooltip="Thay thế, cập nhật, sửa đổi, bãi bỏ và các quan hệ nghiệp vụ khác." />
      </div>

      <section className="review-form business-panel admin-ui-panel relation-create-panel">
        <div className="business-panel-head"><div><h3>Tạo quan hệ mới</h3><p>Chọn chiều phiên bản chính xác trước khi gửi duyệt.</p></div><span className="ops-caption-badge">New relation</span></div>
        <div className="review-grid">
          <label>Tài liệu mới<select value={sourceId} onChange={(event) => setSourceId(event.target.value)}><option value="">— Chọn tài liệu —</option>{documents.map((doc) => <option key={doc.id} value={doc.id}>{doc.title}</option>)}</select></label>
          <label>Tài liệu cũ<select value={targetId} onChange={(event) => setTargetId(event.target.value)}><option value="">— Chọn tài liệu —</option>{documents.filter((doc) => String(doc.id) !== sourceId).map((doc) => <option key={doc.id} value={doc.id}>{doc.title}</option>)}</select></label>
          <label>Loại quan hệ<select value={relationType} onChange={(event) => setRelationType(event.target.value as DocumentRelationType)}>{RELATIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
          <label>Phạm vi / ghi chú<input value={scopeNote} onChange={(event) => setScopeNote(event.target.value)} placeholder="Ví dụ: chỉ áp dụng phân khu The Beverly" /></label>
        </div>
        <button className="btn btn-primary" type="button" onClick={() => void create()} disabled={saving}>{saving && <LoaderIcon size={16} className="icon-spin" />} Tạo quan hệ chờ duyệt</button>
      </section>

      <section className="business-panel admin-ui-panel relation-pending-panel">
        <div className="business-panel-head"><div><h3>Quan hệ chờ duyệt</h3><p>Phê duyệt để áp dụng thay đổi vào phạm vi truy xuất.</p></div><span className="admin-count-badge">{relations.length}</span></div>
        {loading ? <div className="empty-state"><LoaderIcon size={24} className="icon-spin" /></div> : relations.length === 0 ? <div className="empty-state"><p>Không có quan hệ nào chờ duyệt.</p></div> : <div className="data-list">
          {relations.map((relation) => <div className="conflict-card" key={relation.id}>
            <div className="conflict-card-head">{RELATIONS.find(([value]) => value === relation.relation_type)?.[1] ?? relation.relation_type}</div>
            <div className="conflict-pair"><div className="conflict-doc"><div className="conflict-doc-meta">Tài liệu mới</div><div className="conflict-doc-name">{names.get(relation.source_document_id) ?? `#${relation.source_document_id}`}</div></div><div className="conflict-doc"><div className="conflict-doc-meta">Tài liệu cũ</div><div className="conflict-doc-name">{names.get(relation.target_document_id) ?? `#${relation.target_document_id}`}</div></div></div>
            {relation.scope_note && <p className="review-reason">{relation.scope_note}</p>}
            <div className="conflict-actions"><button className="btn btn-primary" type="button" disabled={saving} onClick={() => void review(relation.id, true)}><CheckIcon size={16} /> Duyệt</button><button className="btn btn-danger" type="button" disabled={saving} onClick={() => void review(relation.id, false)}><XIcon size={16} /> Bác bỏ</button></div>
          </div>)}
        </div>}
      </section>
    </div>
  );
}
