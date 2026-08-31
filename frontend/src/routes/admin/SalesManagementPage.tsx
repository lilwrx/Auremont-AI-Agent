import { useCallback, useEffect, useState } from "react";
import { adminDashboardApi } from "../../api/adminDashboard";
import { ActivityIcon, ChartIcon, PlusIcon, RefreshIcon, UsersIcon } from "../../components/Icons";
import { CreateSaleAccountModal } from "../../components/admin/CreateSaleAccountModal";
import { AdminMetricCard } from "../../components/admin/AdminMetricCard";
import { AdminPageHeader } from "../../components/admin/AdminPageHeader";
import type { SalesBoard, SaleStatus } from "../../types/admin";
import { parseServerDate } from "../../utils/datetime";

const PRESENCE_LABEL = { online: "Online", offline: "Offline", busy: "Busy" } as const;

function displayDate(value: string | null) {
  return value ? parseServerDate(value).toLocaleString("vi-VN") : "Chưa có hoạt động";
}

function displayRate(value: number | null) {
  return value == null ? "Chưa có dữ liệu" : `${value.toLocaleString("vi-VN")}%`;
}

export function SalesManagementPage() {
  const [board, setBoard] = useState<SalesBoard | null>(null);
  const [view, setView] = useState<"table" | "grid">("table");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [assignments, setAssignments] = useState<Record<number, string>>({});

  const load = useCallback(async () => {
    try {
      setError(null);
      setBoard(await adminDashboardApi.sales());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Không tải được dữ liệu Sale.");
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 10_000);
    return () => window.clearInterval(timer);
  }, [load]);

  const toggleActive = async (saleId: number, isActive: boolean) => {
    setBusyKey(`sale-${saleId}`);
    try {
      await adminDashboardApi.setSaleActive(saleId, !isActive);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Không cập nhật được tài khoản Sale.");
    } finally {
      setBusyKey(null);
    }
  };

  const reassign = async (sessionId: number) => {
    const saleId = Number(assignments[sessionId]);
    if (!saleId) return;
    setBusyKey(`session-${sessionId}`);
    try {
      await adminDashboardApi.reassign(sessionId, saleId);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Không chuyển được khách hàng.");
    } finally {
      setBusyKey(null);
    }
  };

  const handleSaleCreated = useCallback((sale: SaleStatus) => {
    setBoard((current) => current ? {
      ...current,
      summary: {
        ...current.summary,
        total_sales: current.summary.total_sales + 1,
        active_accounts: current.summary.active_accounts + (sale.is_active ? 1 : 0),
      },
      sales: [...current.sales, sale].sort((left, right) => left.username.localeCompare(right.username, "vi")),
    } : current);
    setError(null);
    setNotice(`Đã tạo tài khoản Sale “${sale.username}” thành công.`);
    setCreateOpen(false);
    void load();
  }, [load]);

  return (
    <div className="page admin-dashboard-page business-dashboard admin-workspace sales-workspace">
      <AdminPageHeader
        eyebrow="Sales operations"
        title="Quản lý Sale"
        description="Theo dõi tải xử lý, trạng thái hoạt động và phân phối khách hàng theo thời gian thực."
        actions={
          <>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => {
              setNotice(null);
              setCreateOpen(true);
            }}
          >
            <PlusIcon size={15} /> Tạo tài khoản Sale
          </button>
          <div className="admin-segmented" aria-label="Chế độ xem">
            <button type="button" className={view === "table" ? "is-active" : ""} onClick={() => setView("table")}>Table</button>
            <button type="button" className={view === "grid" ? "is-active" : ""} onClick={() => setView("grid")}>Grid</button>
          </div>
          <button type="button" className="btn btn-outline" onClick={() => void load()}><RefreshIcon size={15} /> Làm mới</button>
          </>
        }
      />

      {error && <div className="alert alert-danger">{error}</div>}
      {notice ? <div className="alert alert-success" role="status">{notice}</div> : null}
      {!board ? <div className="admin-empty">Đang tải bảng điều phối Sale…</div> : (
        <>
          <div className="admin-metric-grid">
            <AdminMetricCard label="Tài khoản Sale" value={board.summary.total_sales} hint={`${board.summary.active_accounts} đang kích hoạt`} icon={<UsersIcon size={20} />} tooltip="Tổng tài khoản Sale hợp lệ trong hệ thống." />
            <AdminMetricCard label="Đang online" value={board.summary.online_sales} hint={`Ước tính trong ${board.presence_window_minutes} phút`} icon={<ActivityIcon size={20} />} tone="success" tooltip="Trạng thái được suy ra từ hoạt động gần nhất." />
            <AdminMetricCard label="Đang bận" value={board.summary.busy_sales} hint={`${board.summary.live_customers} phiên live`} icon={<ChartIcon size={20} />} tone="warning" tooltip="Sale đang sở hữu ít nhất một phiên hỗ trợ trực tiếp." />
            <AdminMetricCard label="Khách chờ Sale" value={board.summary.waiting_customers} hint="Cần phân công" icon={<UsersIcon size={20} />} tone={board.summary.waiting_customers ? "danger" : "default"} tooltip="Các phiên đã yêu cầu con người nhưng chưa có Sale tiếp nhận." />
          </div>

          <section className="admin-panel">
            <div className="admin-panel-head">
              <div><h2>Sales Status Board</h2><p>Online là trạng thái ước tính từ audit/activity gần nhất; Busy là đang xử lý phiên live.</p></div>
              <span className="live-indicator"><i /> cập nhật mỗi 10 giây</span>
            </div>

            {board.sales.length === 0 ? <div className="admin-empty compact">Chưa có tài khoản Sale.</div> : view === "table" ? (
              <div className="admin-table-wrap">
                <table className="admin-table">
                  <thead><tr><th>Sale</th><th>Trạng thái</th><th>Chat đang xử lý</th><th>Tương tác (30 ngày)</th><th>Tỉ lệ chốt</th><th>Tài khoản</th></tr></thead>
                  <tbody>{board.sales.map((sale) => (
                    <tr key={sale.id}>
                      <td><div className="sale-identity"><span>{sale.username.charAt(0).toUpperCase()}</span><div><strong>{sale.username}</strong><small>{sale.email}<br />{displayDate(sale.last_activity_at)}</small></div></div></td>
                      <td><span className={`presence presence--${sale.presence}`}><i />{PRESENCE_LABEL[sale.presence]}</span></td>
                      <td><strong>{sale.active_chat_sessions}</strong><small className="table-sub">/{sale.handled_sessions} phiên đã nhận</small></td>
                      <td>{displayRate(sale.interaction_rate)}</td>
                      <td><span className="muted-value">Chưa tích hợp CRM</span></td>
                      <td><button type="button" role="switch" aria-checked={sale.is_active} className={`admin-switch ${sale.is_active ? "is-on" : ""}`} disabled={busyKey === `sale-${sale.id}`} onClick={() => void toggleActive(sale.id, sale.is_active)}><span /></button></td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
            ) : (
              <div className="sale-card-grid">{board.sales.map((sale) => (
                <article className="sale-card" key={sale.id}>
                  <div className="sale-card-head"><div className="sale-avatar">{sale.username.charAt(0).toUpperCase()}</div><span className={`presence presence--${sale.presence}`}><i />{PRESENCE_LABEL[sale.presence]}</span></div>
                  <h3>{sale.username}</h3><p>{sale.email}</p>
                  <div className="sale-card-stats"><div><strong>{sale.active_chat_sessions}</strong><span>Đang xử lý</span></div><div><strong>{displayRate(sale.interaction_rate)}</strong><span>Tương tác</span></div></div>
                  <div className="sale-card-foot"><small>{displayDate(sale.last_activity_at)}</small><button type="button" role="switch" aria-checked={sale.is_active} className={`admin-switch ${sale.is_active ? "is-on" : ""}`} onClick={() => void toggleActive(sale.id, sale.is_active)}><span /></button></div>
                </article>
              ))}</div>
            )}
          </section>

          <section className="admin-panel" id="sessions">
            <div className="admin-panel-head"><div><h2>Điều phối khách hàng</h2><p>Giao khách đang chờ hoặc chuyển phiên đang xử lý sang Sale khác.</p></div><span className="admin-count-badge">{board.live_sessions.length} phiên</span></div>
            {board.live_sessions.length === 0 ? <div className="admin-empty compact">Không có khách chờ hoặc phiên live đang hoạt động.</div> : (
              <div className="routing-list">{board.live_sessions.map((session) => (
                <article className="routing-row" key={session.session_id}>
                  <div className="routing-customer"><strong>{session.customer_label}</strong><span>#{session.session_id} · {session.project_id ?? "Chưa chọn dự án"}</span><p>{session.last_message_preview || "Chưa có tin nhắn"}</p></div>
                  <span className={`status-chip status-chip--${session.status === "waiting_sale" ? "warning" : "success"}`}>{session.status === "waiting_sale" ? "Đang chờ" : `Đang cùng ${session.current_sale_name ?? "Sale"}`}</span>
                  <div className="routing-action"><select value={assignments[session.session_id] ?? ""} onChange={(event) => setAssignments((prev) => ({ ...prev, [session.session_id]: event.target.value }))}><option value="">Chọn Sale nhận khách</option>{board.sales.filter((sale) => sale.is_active).map((sale) => <option key={sale.id} value={sale.id}>{sale.username} · {sale.presence}</option>)}</select><button className="btn btn-sm btn-primary" type="button" disabled={!assignments[session.session_id] || busyKey === `session-${session.session_id}`} onClick={() => void reassign(session.session_id)}>Chuyển khách</button></div>
                </article>
              ))}</div>
            )}
          </section>
        </>
      )}
      <CreateSaleAccountModal
        isOpen={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={handleSaleCreated}
      />
    </div>
  );
}
