import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { AdminMetricCard } from "../../components/admin/AdminMetricCard";
import { AdminPageHeader } from "../../components/admin/AdminPageHeader";
import { CheckIcon, CopyIcon, InfoIcon, SettingsIcon, ShieldCheckIcon } from "../../components/Icons";

interface SettingsResponse {
  verifier_threshold_sale: number;
}

export function SettingsTab() {
  const [settings, setSettings] = useState<SettingsResponse | null>(null);
  const [failedToLoad, setFailedToLoad] = useState(false);
  const [copied, setCopied] = useState(false);
  const [copyFailed, setCopyFailed] = useState(false);

  useEffect(() => {
    api
      .get<SettingsResponse>("/admin/settings")
      .then((result) => {
        setSettings(result);
        setFailedToLoad(false);
      })
      .catch(() => setFailedToLoad(true));
  }, []);

  const copyConfig = async () => {
    if (!settings) return;
    try {
      await navigator.clipboard.writeText(`VERIFIER_THRESHOLD_SALE=${settings.verifier_threshold_sale}`);
      setCopyFailed(false);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      setCopied(false);
      setCopyFailed(true);
    }
  };

  if (failedToLoad) {
    return <div className="page admin-dashboard-page business-dashboard admin-workspace"><AdminPageHeader eyebrow="Platform configuration" title="Cài đặt chung" description="Quản lý các ngưỡng an toàn của hệ thống AI." /><div className="alert alert-danger">Không tải được cấu hình từ backend.</div></div>;
  }

  if (!settings) {
    return <div className="page admin-dashboard-page business-dashboard admin-workspace"><div className="skeleton" style={{ height: 220 }} /></div>;
  }

  const score = Math.round(settings.verifier_threshold_sale * 100);

  return (
    <div className="page admin-dashboard-page business-dashboard admin-workspace admin-settings-page">
      <AdminPageHeader
        eyebrow="Platform configuration"
        title="Cài đặt chung"
        description="Theo dõi ngưỡng kiểm chứng quyết định khi nào AI được trả lời và khi nào phải từ chối an toàn."
        actions={<button className="btn btn-outline" type="button" onClick={() => void copyConfig()}>{copied ? <CheckIcon size={15} /> : <CopyIcon size={15} />}{copied ? "Đã sao chép" : "Sao chép cấu hình"}</button>}
      />

      {copyFailed ? <div className="alert alert-danger">Trình duyệt không cho phép sao chép tự động. Hãy sao chép giá trị cấu hình ở bảng bên dưới.</div> : null}

      <div className="admin-metric-grid admin-workspace-metrics settings-metric-grid">
        <AdminMetricCard label="Verifier threshold" value={`${score}%`} hint="Áp dụng cho luồng Sale" icon={<ShieldCheckIcon size={20} />} tone={score >= 70 ? "success" : "warning"} tooltip="Câu trả lời dưới ngưỡng này sẽ không được coi là đủ tin cậy." />
        <AdminMetricCard label="Nguồn cấu hình" value="ENV" hint="Đọc khi backend khởi động" icon={<SettingsIcon size={20} />} tooltip="Giá trị hiện chưa được lưu trong bảng settings của MySQL." />
        <AdminMetricCard label="Chế độ chỉnh sửa" value="Read-only" hint="Cần restart dịch vụ" icon={<InfoIcon size={20} />} tone="warning" tooltip="Backend chưa hỗ trợ cập nhật ngưỡng an toàn trong runtime." />
      </div>

      <div className="admin-two-column settings-layout">
        <section className="business-panel admin-ui-panel settings-threshold-panel">
          <div className="business-panel-head"><div><h3>Ngưỡng tin cậy — Sale</h3><p>Giá trị backend đang sử dụng tại thời điểm hiện tại.</p></div><span className="ops-caption-badge">Safety gate</span></div>
          <div className="settings-score-hero"><strong>{score}</strong><span>/ 100</span></div>
          <div className="settings-threshold-track" aria-label={`Ngưỡng verifier ${score}%`}><i style={{ width: `${score}%` }} /><b style={{ left: `${score}%` }} /></div>
          <div className="settings-threshold-labels"><span>Thấp</span><span>Cân bằng</span><span>Nghiêm ngặt</span></div>
          <div className="settings-readonly-value"><code>VERIFIER_THRESHOLD_SALE={settings.verifier_threshold_sale}</code><button type="button" onClick={() => void copyConfig()} aria-label="Sao chép biến môi trường"><CopyIcon size={15} /></button></div>
        </section>

        <section className="business-panel admin-ui-panel settings-guide-panel">
          <div className="business-panel-head"><div><h3>Cách cập nhật an toàn</h3><p>Thay đổi hiện được quản lý ở tầng triển khai.</p></div><InfoIcon size={20} /></div>
          <ol>
            <li><span>1</span><div><strong>Cập nhật biến môi trường</strong><p>Đặt giá trị từ 0 đến 1 cho <code>VERIFIER_THRESHOLD_SALE</code>.</p></div></li>
            <li><span>2</span><div><strong>Khởi động lại backend</strong><p>Dịch vụ đọc cấu hình một lần khi process bắt đầu.</p></div></li>
            <li><span>3</span><div><strong>Kiểm tra lại dashboard</strong><p>Giá trị mới sẽ xuất hiện tại trang này sau khi backend sẵn sàng.</p></div></li>
          </ol>
          <div className="admin-inline-note">UI cố ý không hiển thị nút “Lưu” để tránh tạo cảm giác thay đổi đã có hiệu lực khi backend chưa lưu runtime settings.</div>
        </section>
      </div>
    </div>
  );
}
