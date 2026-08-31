import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { saleLiveApi } from "../../api/saleLive";
import type { LeadTier, LiveInboxEntry } from "../../types";
import { parseServerDate } from "../../utils/datetime";
import { ArrowRightIcon, ChatIcon, ClockIcon, FlameIcon, PhoneIcon, UsersIcon } from "../../components/Icons";

const POLL_INTERVAL_MS = 5000;

function formatWaitTime(iso: string | null): string {
  if (!iso) return "";
  const started = parseServerDate(iso).getTime();
  if (Number.isNaN(started)) return "";
  const minutes = Math.max(0, Math.round((Date.now() - started) / 60000));
  if (minutes < 1) return "vừa mới xong";
  return `${minutes} phút trước`;
}

function initialsOf(label: string): string {
  const parts = label.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  const first = parts[0][0];
  const last = parts.length > 1 ? parts[parts.length - 1][0] : "";
  return (first + last).toUpperCase();
}

// "Khách đang chờ" — the Sale/Admin queue of customers the AI has handed off to a live
// person (see the SessionStatus state machine in backend/core/enums.py), plus this Sale's
// own already-claimed conversations. Both lists matter: claiming a session removes it from
// the waiting queue, so without the second list a Sale who navigates away (or logs back in
// later) would have no way back to a customer they're already chatting with. Polled rather
// than pushed — see the plan's real-time decision (polling first, WebSocket is a later
// upgrade).
// Rose for HOT, amber for WARM, muted for COLD — reusing the existing `.badge` variants in
// salesmate.css. Deliberately NOT `badge-success`: green reads "done / healthy" everywhere
// else in this design system, which is the opposite of "call this person now".
const LEAD_BADGE: Record<LeadTier, { className: string; label: string }> = {
  hot: { className: "badge badge-danger", label: "HOT" },
  warm: { className: "badge badge-warning", label: "WARM" },
  cold: { className: "badge badge-muted", label: "COLD" },
};

function LeadBadge({ tier }: { tier: LeadTier }) {
  const { className, label } = LEAD_BADGE[tier];
  return (
    <span className={className}>
      {tier === "hot" && <FlameIcon size={11} />}
      {label}
    </span>
  );
}

interface RowProps {
  entry: LiveInboxEntry;
  variant: "mine" | "waiting";
  onAction: () => void;
  busy: boolean;
}

function LeadCard({ entry, variant, onAction, busy }: RowProps) {
  const wait = formatWaitTime(entry.waiting_since);
  const body = (
    <>
      <div className={`lead-card-avatar lead-card-avatar--${entry.lead_tier}`}>{initialsOf(entry.customer_label)}</div>
      <div className="lead-card-body">
        <div className="lead-card-top">
          <span className="lead-card-name">{entry.customer_label}</span>
          <LeadBadge tier={entry.lead_tier} />
          <span className="lead-card-score">{entry.lead_score}</span>
        </div>
        <p className="lead-card-preview">{entry.last_message_preview}</p>
        {entry.lead_reason && <p className="lead-card-reason">{entry.lead_reason}</p>}
        <div className="lead-card-meta">
          {entry.customer_phone && (
            <span className="lead-card-meta-item">
              <PhoneIcon size={12} />
              {entry.customer_phone}
            </span>
          )}
          {/* `waiting_since` is cleared once a session is claimed, so a claimed row shows
              its live status instead of an empty gap where the queue rows have a clock. */}
          <span className="lead-card-meta-item">
            <ClockIcon size={12} />
            {variant === "mine" ? "Đang chat trực tiếp" : wait || "vừa vào hàng chờ"}
          </span>
        </div>
      </div>
    </>
  );

  if (variant === "mine") {
    return (
      <button type="button" className={`lead-card lead-card--${entry.lead_tier} lead-card--clickable`} onClick={onAction}>
        {body}
        <span className="btn btn-outline btn-sm lead-card-action">
          <ChatIcon size={14} />
          Tiếp tục chat
        </span>
      </button>
    );
  }

  return (
    <div className={`lead-card lead-card--${entry.lead_tier}`}>
      {body}
      <button type="button" className="btn btn-primary lead-card-action" onClick={onAction} disabled={busy}>
        Tiếp nhận
        <ArrowRightIcon size={14} />
      </button>
    </div>
  );
}

export function LiveInboxPage() {
  const [waiting, setWaiting] = useState<LiveInboxEntry[]>([]);
  const [mine, setMine] = useState<LiveInboxEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [claimingId, setClaimingId] = useState<number | null>(null);
  const [tierFilter, setTierFilter] = useState<LeadTier | "all">("all");
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  const reload = useCallback(() => {
    Promise.all([saleLiveApi.listWaiting(), saleLiveApi.listMine()])
      .then(([waitingRows, mineRows]) => {
        setWaiting(waitingRows);
        setMine(mineRows);
      })
      .catch(() => {
        setWaiting([]);
        setMine([]);
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    reload();
    const interval = setInterval(reload, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [reload]);

  const claim = async (sessionId: number) => {
    if (claimingId) return;
    setClaimingId(sessionId);
    setError(null);
    try {
      await saleLiveApi.claim(sessionId);
      navigate(`/live-inbox/${sessionId}`);
    } catch {
      setError("Khách này vừa được chuyên viên khác tiếp nhận — danh sách đã được làm mới.");
      reload();
    } finally {
      setClaimingId(null);
    }
  };

  // A quick-scan header so a Sale sees the shape of the queue before reading a single row —
  // how many are waiting and how many of those are worth calling first.
  const stats = useMemo(() => {
    const hot = waiting.filter((e) => e.lead_tier === "hot").length;
    const warm = waiting.filter((e) => e.lead_tier === "warm").length;
    return { total: waiting.length, hot, warm, cold: waiting.length - hot - warm };
  }, [waiting]);

  const visible = useMemo(
    () => (tierFilter === "all" ? waiting : waiting.filter((e) => e.lead_tier === tierFilter)),
    [waiting, tierFilter],
  );

  return (
    <div className="page">
      <div className="live-inbox-head">
        <div>
          <h2 className="page-title">Khách đang chờ</h2>
          <p className="page-sub">
            Khách đã được AI kết nối tới chuyên viên — bấm Tiếp nhận để đọc lại lịch sử và trả lời trực tiếp.
          </p>
        </div>
        {!loading && stats.total > 0 && (
          <div className="live-inbox-stats">
            <div className="live-inbox-stat">
              <strong>{stats.total}</strong>
              <span>Đang chờ</span>
            </div>
            <div className="live-inbox-stat live-inbox-stat--hot">
              <strong>{stats.hot}</strong>
              <span>HOT</span>
            </div>
            <div className="live-inbox-stat live-inbox-stat--warm">
              <strong>{stats.warm}</strong>
              <span>WARM</span>
            </div>
          </div>
        )}
      </div>

      {error && (
        <div className="alert alert-danger" style={{ marginBottom: 16 }}>
          {error}
        </div>
      )}

      {!loading && mine.length > 0 && (
        <div style={{ marginBottom: 28 }}>
          <h3 className="live-inbox-section-title">Chat với khách hàng</h3>
          <div className="lead-card-list">
            {mine.map((e) => (
              <LeadCard key={e.session_id} entry={e} variant="mine" busy={false} onAction={() => navigate(`/live-inbox/${e.session_id}`)} />
            ))}
          </div>
        </div>
      )}

      <div className="live-inbox-queue-head">
        <h3 className="live-inbox-section-title">Đang chờ tiếp nhận</h3>
        {!loading && waiting.length > 0 && (
          <div className="admin-segmented live-inbox-filter">
            {([
              ["all", "Tất cả", stats.total],
              ["hot", "HOT", stats.hot],
              ["warm", "WARM", stats.warm],
              ["cold", "COLD", stats.cold],
            ] as const).map(([key, label, count]) => (
              <button
                key={key}
                type="button"
                className={tierFilter === key ? "is-active" : ""}
                onClick={() => setTierFilter(key)}
              >
                {label} <b>{count}</b>
              </button>
            ))}
          </div>
        )}
      </div>
      {loading ? (
        <div className="empty-state">
          <p>Đang tải...</p>
        </div>
      ) : visible.length === 0 ? (
        <div className="empty-state">
          <div className="empty-state-icon">
            <UsersIcon size={26} />
          </div>
          <p>{waiting.length === 0 ? "Chưa có khách nào đang chờ." : "Không có khách nào ở mức này."}</p>
        </div>
      ) : (
        <div className="lead-card-list">
          {visible.map((e) => (
            <LeadCard
              key={e.session_id}
              entry={e}
              variant="waiting"
              busy={claimingId !== null}
              onAction={() => claim(e.session_id)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
