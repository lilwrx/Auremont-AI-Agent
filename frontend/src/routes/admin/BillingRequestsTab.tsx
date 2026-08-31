import { useCallback, useEffect, useState } from "react";
import { api } from "../../api/client";
import { formatVnd } from "../../api/billing";
import { AdminMetricCard } from "../../components/admin/AdminMetricCard";
import { AdminPageHeader } from "../../components/admin/AdminPageHeader";
import { CheckIcon, ClockIcon, RefreshIcon, XIcon } from "../../components/Icons";

type RequestStatus = "pending" | "contacted" | "approved" | "rejected";

interface SubscriptionRequest {
  id: number;
  plan_id: string;
  seats: number;
  company_name: string;
  contact_name: string;
  contact_email: string;
  contact_phone: string;
  tax_code: string | null;
  billing_address: string | null;
  note: string | null;
  quoted_price_per_seat_vnd: number;
  quoted_monthly_total_vnd: number;
  status: RequestStatus;
  review_note: string | null;
  reviewed_at: string | null;
  organization_id: number | null;
  created_at: string;
}

interface RequestList {
  items: SubscriptionRequest[];
  total: number;
  offset: number;
  limit: number;
}

const STATUS_LABELS: Record<RequestStatus, string> = {
  pending: "Chờ duyệt",
  contacted: "Đã liên hệ",
  approved: "Đã kích hoạt",
  rejected: "Từ chối",
};

const FILTERS: Array<{ value: RequestStatus | "all"; label: string }> = [
  { value: "pending", label: "Chờ duyệt" },
  { value: "contacted", label: "Đã liên hệ" },
  { value: "approved", label: "Đã kích hoạt" },
  { value: "rejected", label: "Từ chối" },
  { value: "all", label: "Tất cả" },
];

function formatDate(value: string | null): string {
  if (!value) return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "—" : parsed.toLocaleString("vi-VN");
}

export function BillingRequestsTab() {
  const [rows, setRows] = useState<SubscriptionRequest[]>([]);
  const [filter, setFilter] = useState<RequestStatus | "all">("pending");
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [selected, setSelected] = useState<SubscriptionRequest | null>(null);
  const [reviewNote, setReviewNote] = useState("");
  const [acting, setActing] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const query = filter === "all" ? "" : `?status=${filter}`;
      const data = await api.get<RequestList>(`/admin/billing/subscription-requests${query}`);
      setRows(data.items);
      setFailed(false);
    } catch {
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => {
    void load();
  }, [load]);

  const review = async (request: SubscriptionRequest, status: "approved" | "rejected" | "contacted") => {
    setActing(true);
    setActionError(null);
    try {
      await api.patch(`/admin/billing/subscription-requests/${request.id}`, {
        status,
        review_note: reviewNote.trim() || null,
      });
      setSelected(null);
      setReviewNote("");
      await load();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Không thực hiện được thao tác.");
    } finally {
      setActing(false);
    }
  };

  const pendingCount = rows.filter((row) => row.status === "pending").length;
  const monthlyValue = rows
    .filter((row) => row.status === "approved")
    .reduce((sum, row) => sum + row.quoted_monthly_total_vnd, 0);

  return (
    <div className="page admin-dashboard-page business-dashboard admin-workspace">
      <AdminPageHeader
        eyebrow="Doanh nghiệp"
        title="Yêu cầu đăng ký gói"
        description="Duyệt yêu cầu từ sàn giao dịch. Kích hoạt sẽ tạo workspace, tài khoản chủ sở hữu và subscription cùng lúc."
        actions={
          <button className="business-refresh" type="button" disabled={loading} onClick={() => void load()}>
            <RefreshIcon size={15} className={loading ? "is-spinning" : ""} /> Làm mới
          </button>
        }
      />

      {failed ? <div className="alert alert-danger">Không tải được danh sách yêu cầu.</div> : null}
      {actionError ? <div className="alert alert-danger">{actionError}</div> : null}

      <div className="admin-metric-grid admin-workspace-metrics">
        <AdminMetricCard
          label="Đang chờ duyệt"
          value={pendingCount}
          hint="Cần xử lý"
          icon={<ClockIcon size={20} />}
          tone={pendingCount ? "warning" : "success"}
          tooltip="Số yêu cầu chưa được duyệt hoặc từ chối."
        />
        <AdminMetricCard
          label="Doanh thu tháng đã kích hoạt"
          value={formatVnd(monthlyValue)}
          hint="Theo báo giá lúc đăng ký"
          icon={<CheckIcon size={20} />}
          tone="success"
          tooltip="Tổng giá trị hàng tháng của các yêu cầu đã kích hoạt trong danh sách hiện tại."
        />
      </div>

      <div className="admin-filter-row">
        {FILTERS.map((option) => (
          <button
            key={option.value}
            type="button"
            className={`admin-filter-chip ${filter === option.value ? "is-active" : ""}`}
            onClick={() => setFilter(option.value)}
          >
            {option.label}
          </button>
        ))}
      </div>

      <section className="business-panel admin-ui-panel">
        {loading && rows.length === 0 ? (
          <div className="admin-empty compact">Đang tải yêu cầu…</div>
        ) : rows.length === 0 ? (
          <div className="ops-empty-state compact">
            <CheckIcon size={24} />
            <strong>Không có yêu cầu nào</strong>
            <span>Yêu cầu đăng ký mới sẽ xuất hiện tại đây.</span>
          </div>
        ) : (
          <div className="admin-table-wrap">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Doanh nghiệp</th>
                  <th>Gói</th>
                  <th>Seat</th>
                  <th>Giá trị / tháng</th>
                  <th>Trạng thái</th>
                  <th>Gửi lúc</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id}>
                    <td>
                      <strong>{row.company_name}</strong>
                      <br />
                      <small>
                        {row.contact_name} · {row.contact_email}
                      </small>
                    </td>
                    <td>{row.plan_id}</td>
                    <td>{row.seats}</td>
                    <td>{formatVnd(row.quoted_monthly_total_vnd)}</td>
                    <td>
                      <span className={`admin-status-badge is-${row.status}`}>{STATUS_LABELS[row.status]}</span>
                    </td>
                    <td>{formatDate(row.created_at)}</td>
                    <td>
                      <button
                        type="button"
                        className="btn btn-outline btn-sm"
                        onClick={() => {
                          setSelected(row);
                          setReviewNote(row.review_note ?? "");
                        }}
                      >
                        Xem
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {selected ? (
        <aside className="business-detail-drawer" aria-live="polite">
          <div>
            <div>
              <p>Yêu cầu #{selected.id}</p>
              <h3>{selected.company_name}</h3>
              <span>{STATUS_LABELS[selected.status]}</span>
            </div>
            <button type="button" onClick={() => setSelected(null)} aria-label="Đóng chi tiết">
              <XIcon size={17} />
            </button>
          </div>

          <dl>
            <div>
              <dt>Người đại diện</dt>
              <dd>{selected.contact_name}</dd>
            </div>
            <div>
              <dt>Email</dt>
              <dd>{selected.contact_email}</dd>
            </div>
            <div>
              <dt>Điện thoại</dt>
              <dd>{selected.contact_phone}</dd>
            </div>
            <div>
              <dt>Gói / seat</dt>
              <dd>
                {selected.plan_id} · {selected.seats} seat
              </dd>
            </div>
            <div>
              <dt>Đơn giá</dt>
              <dd>{formatVnd(selected.quoted_price_per_seat_vnd)} / seat</dd>
            </div>
            <div>
              <dt>Tổng mỗi tháng</dt>
              <dd>{formatVnd(selected.quoted_monthly_total_vnd)}</dd>
            </div>
            <div>
              <dt>Mã số thuế</dt>
              <dd>{selected.tax_code ?? "—"}</dd>
            </div>
            <div>
              <dt>Địa chỉ hoá đơn</dt>
              <dd>{selected.billing_address ?? "—"}</dd>
            </div>
            {selected.note ? (
              <div>
                <dt>Ghi chú của khách</dt>
                <dd>{selected.note}</dd>
              </div>
            ) : null}
            {selected.organization_id ? (
              <div>
                <dt>Workspace</dt>
                <dd>#{selected.organization_id}</dd>
              </div>
            ) : null}
          </dl>

          {selected.status === "approved" ? (
            <p className="admin-drawer-hint">
              Workspace đã được tạo. Tài khoản chủ sở hữu đăng nhập bằng chính email và mật khẩu họ đã đăng ký.
            </p>
          ) : (
            <>
              <label className="login-label">
                Ghi chú duyệt (hiển thị nội bộ)
                <textarea
                  className="login-input"
                  rows={3}
                  value={reviewNote}
                  onChange={(event) => setReviewNote(event.target.value)}
                />
              </label>
              <div className="register-business-actions">
                <button
                  type="button"
                  className="btn btn-outline"
                  disabled={acting}
                  onClick={() => void review(selected, "contacted")}
                >
                  Đã liên hệ
                </button>
                <button
                  type="button"
                  className="btn btn-outline"
                  disabled={acting}
                  onClick={() => void review(selected, "rejected")}
                >
                  Từ chối
                </button>
                <button
                  type="button"
                  className="btn btn-primary"
                  disabled={acting}
                  onClick={() => void review(selected, "approved")}
                >
                  Kích hoạt
                </button>
              </div>
            </>
          )}
        </aside>
      ) : null}
    </div>
  );
}
