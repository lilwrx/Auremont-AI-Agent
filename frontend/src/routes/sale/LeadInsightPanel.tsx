import { useState } from "react";
import type { LeadDetail, LeadPurpose, LeadTier, LeadUrgency } from "../../types";
import { parseServerDate } from "../../utils/datetime";
import {
  CheckIcon,
  ClockIcon,
  CopyIcon,
  FlameIcon,
  PhoneIcon,
  SparklesIcon,
  TargetIcon,
  UserIcon,
} from "../../components/Icons";

const TIER_META: Record<LeadTier, { label: string; subtitle: string; icon: React.ReactNode }> = {
  hot: { label: "HOT", subtitle: "Rất sẵn sàng — nên liên hệ ngay", icon: <FlameIcon size={22} /> },
  warm: { label: "WARM", subtitle: "Đang cân nhắc — nên theo dõi sát", icon: <TargetIcon size={20} /> },
  cold: { label: "COLD", subtitle: "Mới bắt đầu tìm hiểu", icon: <TargetIcon size={20} /> },
};

const URGENCY_LABEL: Record<LeadUrgency, string> = {
  immediate: "Cần gấp",
  near_term: "Có mốc thời gian",
  exploring: "Đang tìm hiểu",
};

const PURPOSE_LABEL: Record<LeadPurpose, string> = {
  living: "Mua để ở",
  investment: "Đầu tư",
  business: "Kinh doanh",
  unknown: "Chưa rõ mục đích",
};

function formatScoredAt(iso: string | null): string {
  if (!iso) return "";
  const date = parseServerDate(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString("vi-VN", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

// Circumference of the r=34 ring used below (2 * PI * 34), precomputed once.
const RING_CIRCUMFERENCE = 213.6;

function ScoreRing({ score }: { score: number }) {
  const offset = RING_CIRCUMFERENCE * (1 - Math.min(100, Math.max(0, score)) / 100);
  return (
    <div className="lead-panel-ring">
      <svg viewBox="0 0 80 80" width={72} height={72}>
        <circle cx="40" cy="40" r="34" fill="none" strokeWidth="7" className="lead-panel-ring-track" />
        <circle
          cx="40"
          cy="40"
          r="34"
          fill="none"
          strokeWidth="7"
          strokeLinecap="round"
          className="lead-panel-ring-value-arc"
          strokeDasharray={RING_CIRCUMFERENCE}
          strokeDashoffset={offset}
          transform="rotate(-90 40 40)"
        />
      </svg>
      <div className="lead-panel-ring-label">
        <strong>{score}</strong>
        <span>/100</span>
      </div>
    </div>
  );
}

function CallActions({ phone }: { phone: string }) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(phone);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      // Clipboard is blocked on insecure origins and in some embedded webviews. The number
      // is on screen either way, so a failed copy is a silent non-event, not an error worth
      // interrupting the Sale mid-conversation.
    }
  };

  return (
    <div className="lead-panel-actions">
      {/* `<a href="tel:">` is safe here: unlike the inbox rows, this panel is an <aside>,
          not a <button>, so there is no invalid nesting. */}
      <a className="btn btn-primary lead-panel-call" href={`tel:${phone}`}>
        <PhoneIcon size={15} />
        Gọi ngay
      </a>
      <button type="button" className="btn btn-outline btn-sm lead-panel-copy" onClick={copy} title="Sao chép số">
        {copied ? <CheckIcon size={14} /> : <CopyIcon size={14} />}
        {copied ? "Đã chép" : "Chép số"}
      </button>
    </div>
  );
}

interface Props {
  lead: LeadDetail | null;
  loading: boolean;
}

/** The "vì sao" panel beside a live chat: what tier this customer is, and the actual
 * evidence behind it — not just the badge. A tier with no visible evidence is a verdict a
 * Sale cannot check, which is exactly the objection this panel exists to answer. */
export function LeadInsightPanel({ lead, loading }: Props) {
  if (loading) {
    return (
      <aside className="lead-panel">
        <div className="lead-panel-loading">
          <span className="lead-panel-spinner" />
          Đang tải đánh giá...
        </div>
      </aside>
    );
  }

  if (!lead) {
    return (
      <aside className="lead-panel">
        <div className="lead-panel-empty">
          <div className="lead-panel-empty-icon">
            <TargetIcon size={22} />
          </div>
          <p>Chưa có đủ dữ liệu để đánh giá mức độ quan tâm.</p>
          <span>Hệ thống sẽ chấm lại sau tin nhắn tiếp theo của khách.</span>
        </div>
      </aside>
    );
  }

  const tier = TIER_META[lead.lead_tier];
  const topSignal = lead.signals[0];

  return (
    <aside className="lead-panel">
      <div className={`lead-panel-banner lead-panel-banner--${lead.lead_tier}`}>
        <div className="lead-panel-banner-text">
          <span className="lead-panel-eyebrow">Mức độ quan tâm</span>
          <div className="lead-panel-tier">
            {tier.icon}
            {tier.label}
          </div>
          <p className="lead-panel-subtitle">{tier.subtitle}</p>
        </div>
        <ScoreRing score={lead.lead_score} />
      </div>

      <div className="lead-panel-content">
        <div className="lead-panel-contact">
          <div className="lead-panel-contact-avatar">
            <UserIcon size={16} />
          </div>
          <div className="lead-panel-contact-info">
            <span className="lead-panel-contact-name">{lead.customer_name ?? lead.customer_label}</span>
            {lead.customer_phone && (
              <span className="lead-panel-contact-phone">
                <PhoneIcon size={12} />
                {lead.customer_phone}
              </span>
            )}
          </div>
        </div>

        {lead.customer_phone && <CallActions phone={lead.customer_phone} />}

        {lead.next_action && (
          <div className={`lead-panel-next lead-panel-next--${lead.lead_tier}`}>
            <span className="lead-panel-next-label">Nên làm gì tiếp theo</span>
            <p>{lead.next_action}</p>
          </div>
        )}

        {(lead.urgency || lead.purpose) && (
          <div className="lead-panel-chips">
            {lead.urgency && <span className="lead-panel-chip">{URGENCY_LABEL[lead.urgency]}</span>}
            {lead.purpose && <span className="lead-panel-chip">{PURPOSE_LABEL[lead.purpose]}</span>}
          </div>
        )}

        {lead.llm_reason && (
          <div className="lead-panel-ai-note">
            <SparklesIcon size={14} />
            <p>{lead.llm_reason}</p>
          </div>
        )}

        <div className="lead-panel-section">
          <h4>Vì sao ở mức này</h4>
          {lead.signals.length === 0 ? (
            <p className="lead-panel-no-signals">Chưa ghi nhận tín hiệu cụ thể nào.</p>
          ) : (
            <ul className="lead-panel-signals">
              {lead.signals.map((signal) => (
                <li key={signal.label} className={signal.label === topSignal?.label ? "is-top" : undefined}>
                  <span>{signal.label}</span>
                  <b>+{signal.points}</b>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="lead-panel-meta">
          <ClockIcon size={12} />
          <span>
            Đã hỏi {lead.turn_count} lượt · Chấm lúc {formatScoredAt(lead.scored_at)}
          </span>
        </div>
      </div>
    </aside>
  );
}
