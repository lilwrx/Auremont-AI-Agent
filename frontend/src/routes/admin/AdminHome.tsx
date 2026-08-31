import { type KeyboardEvent, type ReactNode, useEffect, useId, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { adminDashboardApi } from "../../api/adminDashboard";
import {
  ActivityIcon,
  BotIcon,
  ChatIcon,
  DocumentIcon,
  RefreshIcon,
  ShieldCheckIcon,
  SparklesIcon,
  UsersIcon,
} from "../../components/Icons";
import { LegacyReclassificationModal } from "../../components/admin/LegacyReclassificationModal";
import { useAuth } from "../../hooks/useAuth";
import type { BusinessDashboard, BusinessSummaryBase, LeadStats } from "../../types/admin";

const EMPTY: BusinessDashboard = {
  period_days: 14,
  period: { current_start: "", current_end: "", previous_start: "", previous_end: "", timezone: "Asia/Bangkok" },
  applied_filters: { project_id: null, sale_id: null },
  filter_options: { projects: [], sales: [] },
  verifier_threshold: 0.7,
  summary: {
    sessions: 0,
    customers: 0,
    questions: 0,
    active_sales: 0,
    helpful_rate: null,
    verifier_avg: null,
    hitl_required: 0,
    hitl_confirmed: 0,
    ready_documents: 0,
  },
  previous_summary: {
    sessions: 0,
    customers: 0,
    questions: 0,
    active_sales: 0,
    helpful_rate: null,
    verifier_avg: null,
    hitl_required: 0,
    hitl_confirmed: 0,
  },
  activity: [],
  top_projects: [],
  top_sales: [],
  feedback_distribution: { helpful: 0, wrong: 0, incomplete: 0, unrated: 0 },
  quality_trend: [],
  hitl_funnel: { answers: 0, required: 0, confirmed: 0 },
  document_coverage: [],
};

type DashboardDetail = {
  title: string;
  subtitle: string;
  rows: { label: string; value: string | number }[];
};

type TrendTone = "up" | "down" | "neutral";
type Trend = { label: string; tone: TrendTone; description: string };

const CATEGORY_LABELS: Record<string, string> = {
  subdivision_info: "Thông tin phân khu",
  sales_policy: "Chính sách",
  price_list: "Bảng giá",
  floor_plan: "Mặt bằng",
  legal_document: "Pháp lý",
  payment_schedule: "Thanh toán",
};

const COVERAGE_STATE_LABELS: Record<BusinessDashboard["document_coverage"][number]["categories"][string], string> = {
  ready: "Sẵn sàng",
  pending_review: "Chờ duyệt metadata",
  unavailable: "Chưa xử lý thành công",
  missing: "Chưa có tài liệu",
};

const number = (value: number) => new Intl.NumberFormat("vi-VN").format(value);
const percent = (value: number | null) => value == null ? "Chưa có dữ liệu" : `${Math.round(value * 100)}%`;

function shortDate(value: string) {
  if (!value) return "—";
  const parsed = new Date(`${value}T00:00:00`);
  return `${parsed.getDate()}/${parsed.getMonth() + 1}`;
}

function fullDate(value: string) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("vi-VN", { day: "2-digit", month: "2-digit", year: "numeric" })
    .format(new Date(`${value}T00:00:00`));
}

function countTrend(current: number, previous: number): Trend {
  if (previous === 0) {
    if (current === 0) return { label: "0%", tone: "neutral", description: "Không đổi so với kỳ trước" };
    return { label: "Mới", tone: "up", description: `Kỳ trước chưa ghi nhận, kỳ này có ${number(current)}` };
  }
  const change = (current - previous) / previous * 100;
  const tone: TrendTone = change > 0 ? "up" : change < 0 ? "down" : "neutral";
  const arrow = change > 0 ? "↑" : change < 0 ? "↓" : "";
  return {
    label: `${arrow}${Math.abs(change).toLocaleString("vi-VN", { maximumFractionDigits: 1 })}%`,
    tone,
    description: `${current >= previous ? "Tăng" : "Giảm"} ${Math.abs(current - previous)} so với kỳ trước (${number(previous)})`,
  };
}

function scoreTrend(current: number | null, previous: number | null): Trend {
  if (current == null || previous == null) {
    return { label: "Chưa đủ mẫu", tone: "neutral", description: "Cần dữ liệu ở cả hai kỳ để so sánh" };
  }
  const points = Math.round((current - previous) * 100);
  const tone: TrendTone = points > 0 ? "up" : points < 0 ? "down" : "neutral";
  const arrow = points > 0 ? "↑" : points < 0 ? "↓" : "";
  return {
    label: `${arrow}${Math.abs(points)} điểm`,
    tone,
    description: `Kỳ trước ${percent(previous)}`,
  };
}

function handleInteractiveKey(event: KeyboardEvent<SVGElement>, action: () => void) {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    action();
  }
}

interface KpiCardProps {
  title: string;
  value: string;
  caption: string;
  tooltip: string;
  trend?: Trend;
  icon: ReactNode;
  dark?: boolean;
  loading: boolean;
  onClick: () => void;
}

function KpiCard({ title, value, caption, tooltip, trend, icon, dark, loading, onClick }: KpiCardProps) {
  return (
    <button
      type="button"
      className={`business-kpi${dark ? " business-kpi--dark" : ""}`}
      onClick={onClick}
      aria-label={`${title}: ${value}. ${tooltip}`}
    >
      <span className="business-kpi-top">
        <i className="business-kpi-icon" aria-hidden="true">{icon}</i>
        {trend && <span className={`business-trend business-trend--${trend.tone}`}>{trend.label}</span>}
      </span>
      <span className="business-kpi-title">{title}</span>
      <strong>{loading ? "—" : value}</strong>
      <small>{caption}</small>
      <span className="business-kpi-tooltip" role="tooltip">
        <b>{tooltip}</b>
        {trend && <small>{trend.description}</small>}
        <em>Nhấn để xem chi tiết</em>
      </span>
    </button>
  );
}

interface ActivityChartProps {
  points: BusinessDashboard["activity"];
  periodDays: number;
  onSelect: (point: BusinessDashboard["activity"][number]) => void;
}

function smoothPath(points: { x: number; y: number }[]) {
  if (points.length === 0) return "";
  if (points.length === 1) return `M ${points[0].x} ${points[0].y}`;
  let path = `M ${points[0].x} ${points[0].y}`;
  for (let index = 1; index < points.length - 1; index += 1) {
    const point = points[index];
    const next = points[index + 1];
    path += ` Q ${point.x} ${point.y} ${(point.x + next.x) / 2} ${(point.y + next.y) / 2}`;
  }
  const last = points[points.length - 1];
  path += ` T ${last.x} ${last.y}`;
  return path;
}

function ActivityChart({ points, periodDays, onSelect }: ActivityChartProps) {
  const [activeIndex, setActiveIndex] = useState<number | null>(null);
  const rawId = useId();
  const gradientId = `activity-area-${rawId.replace(/:/g, "")}`;
  const width = 760;
  const height = 292;
  const left = 48;
  const right = 18;
  const top = 18;
  const bottom = 38;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const rawMax = Math.max(1, ...points.flatMap((point) => [point.sessions, point.questions]));
  const step = Math.max(1, Math.ceil(rawMax / 4));
  const maxValue = step * 4;
  const x = (index: number) => points.length <= 1 ? left + plotWidth / 2 : left + index / (points.length - 1) * plotWidth;
  const y = (value: number) => top + plotHeight - value / maxValue * plotHeight;
  const sessionPoints = points.map((point, index) => ({ x: x(index), y: y(point.sessions) }));
  const questionPoints = points.map((point, index) => ({ x: x(index), y: y(point.questions) }));
  const questionPath = smoothPath(questionPoints);
  const areaPath = questionPoints.length
    ? `${questionPath} L ${questionPoints[questionPoints.length - 1].x} ${top + plotHeight} L ${questionPoints[0].x} ${top + plotHeight} Z`
    : "";
  const active = activeIndex == null ? null : points[activeIndex];
  const labelEvery = Math.max(1, Math.ceil(points.length / 7));

  if (points.length === 0) return <div className="business-empty">Chưa có hoạt động trong kỳ này.</div>;

  return (
    <div className="business-line-chart" onMouseLeave={() => setActiveIndex(null)}>
      <svg viewBox={`0 0 ${width} ${height}`} role="group" aria-label={`Biểu đồ phiên tư vấn và câu hỏi trong ${periodDays} ngày`}>
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" className="business-area-stop business-area-stop--start" />
            <stop offset="100%" className="business-area-stop business-area-stop--end" />
          </linearGradient>
        </defs>
        {[0, 1, 2, 3, 4].map((tick) => {
          const tickValue = maxValue - tick * step;
          const tickY = top + tick / 4 * plotHeight;
          return <g key={tickValue} className="business-chart-grid"><line x1={left} y1={tickY} x2={width - right} y2={tickY} /><text x={left - 9} y={tickY + 4}>{tickValue}</text></g>;
        })}
        <path d={areaPath} fill={`url(#${gradientId})`} className="business-activity-area" />
        <path d={questionPath} className="business-activity-line business-activity-line--question" />
        <path d={smoothPath(sessionPoints)} className="business-activity-line business-activity-line--session" />
        {points.map((point, index) => {
          const isActive = activeIndex === index;
          return (
            <g key={point.date}>
              {(index % labelEvery === 0 || index === points.length - 1) && <text className="business-chart-x-label" x={x(index)} y={height - 10}>{shortDate(point.date)}</text>}
              {isActive && <line className="business-chart-crosshair" x1={x(index)} y1={top} x2={x(index)} y2={top + plotHeight} />}
              <circle className={`business-line-point business-line-point--question${isActive ? " is-active" : ""}`} cx={x(index)} cy={y(point.questions)} r={isActive ? 5 : 3} />
              <circle className={`business-line-point business-line-point--session${isActive ? " is-active" : ""}`} cx={x(index)} cy={y(point.sessions)} r={isActive ? 5 : 3} />
              <rect
                className="business-chart-hitbox"
                x={x(index) - plotWidth / Math.max(points.length, 1) / 2}
                y={top}
                width={plotWidth / Math.max(points.length, 1)}
                height={plotHeight}
                tabIndex={0}
                role="button"
                aria-label={`${fullDate(point.date)}: ${point.sessions} phiên, ${point.questions} câu hỏi`}
                onPointerEnter={() => setActiveIndex(index)}
                onFocus={() => setActiveIndex(index)}
                onBlur={() => setActiveIndex(null)}
                onClick={() => onSelect(point)}
                onKeyDown={(event) => handleInteractiveKey(event, () => onSelect(point))}
              />
            </g>
          );
        })}
      </svg>
      {active && activeIndex != null && (
        <div
          className="business-chart-tooltip"
          style={{ left: `${x(activeIndex) / width * 100}%`, top: `${Math.min(y(active.sessions), y(active.questions)) / height * 100}%` }}
          role="tooltip"
        >
          <strong>{fullDate(active.date)}</strong>
          <span><i className="legend-question" />Câu hỏi <b>{number(active.questions)}</b></span>
          <span><i className="legend-session" />Phiên mới <b>{number(active.sessions)}</b></span>
        </div>
      )}
    </div>
  );
}

type FeedbackKey = keyof BusinessDashboard["feedback_distribution"];

const FEEDBACK_META: { key: FeedbackKey; label: string }[] = [
  { key: "helpful", label: "Hữu ích" },
  { key: "wrong", label: "Sai" },
  { key: "incomplete", label: "Thiếu" },
  { key: "unrated", label: "Chưa đánh giá" },
];

interface FeedbackDonutProps {
  distribution: BusinessDashboard["feedback_distribution"];
  onSelect: (key: FeedbackKey, label: string, count: number) => void;
}

function FeedbackDonut({ distribution, onSelect }: FeedbackDonutProps) {
  const [activeKey, setActiveKey] = useState<FeedbackKey | null>(null);
  const total = Object.values(distribution).reduce((sum, value) => sum + value, 0);
  let offset = 0;
  const segments = FEEDBACK_META.map((item) => {
    const count = distribution[item.key];
    const share = total ? count / total * 100 : 0;
    const segment = { ...item, count, share, offset };
    offset += share;
    return segment;
  });
  const active = activeKey ? segments.find((segment) => segment.key === activeKey) ?? null : null;

  if (!total) return <div className="business-empty">Chưa có câu trả lời trong kỳ này.</div>;

  return (
    <div className="business-feedback-interactive" onMouseLeave={() => setActiveKey(null)}>
      <div className="business-donut-shell">
        <svg viewBox="0 0 120 120" role="group" aria-label={`Phân bổ feedback của ${total} câu trả lời`}>
          <circle className="business-donut-track" cx="60" cy="60" r="44" pathLength="100" />
          {segments.filter((segment) => segment.count > 0).map((segment) => (
            <circle
              key={segment.key}
              className={`business-donut-segment feedback-stroke-${segment.key}${activeKey === segment.key ? " is-active" : ""}`}
              cx="60"
              cy="60"
              r="44"
              pathLength="100"
              strokeDasharray={`${segment.share} ${100 - segment.share}`}
              strokeDashoffset={-segment.offset}
              tabIndex={0}
              role="button"
              aria-label={`${segment.label}: ${segment.count}, ${Math.round(segment.share)}%`}
              onPointerEnter={() => setActiveKey(segment.key)}
              onFocus={() => setActiveKey(segment.key)}
              onBlur={() => setActiveKey(null)}
              onClick={() => onSelect(segment.key, segment.label, segment.count)}
              onKeyDown={(event) => handleInteractiveKey(event, () => onSelect(segment.key, segment.label, segment.count))}
            />
          ))}
        </svg>
        <div className="business-donut-center" aria-live="polite">
          <strong>{number(active?.count ?? total)}</strong>
          <span>{active ? active.label : "Câu trả lời"}</span>
          {active && <small>{Math.round(active.share)}%</small>}
        </div>
      </div>
      <div className="business-feedback-legend">
        {segments.map((segment) => (
          <button
            type="button"
            key={segment.key}
            className={activeKey === segment.key ? "is-active" : ""}
            onPointerEnter={() => setActiveKey(segment.key)}
            onFocus={() => setActiveKey(segment.key)}
            onBlur={() => setActiveKey(null)}
            onClick={() => onSelect(segment.key, segment.label, segment.count)}
          >
            <i className={`feedback-${segment.key}`} />
            <span>{segment.label}<small>{Math.round(segment.share)}%</small></span>
            <strong>{number(segment.count)}</strong>
          </button>
        ))}
      </div>
    </div>
  );
}

interface QualityChartProps {
  points: BusinessDashboard["quality_trend"];
  threshold: number;
  onSelect: (point: BusinessDashboard["quality_trend"][number]) => void;
}

function QualityChart({ points, threshold, onSelect }: QualityChartProps) {
  const [activeIndex, setActiveIndex] = useState<number | null>(null);
  const valid = points.some((point) => point.faithfulness != null || point.relevancy != null);
  if (!valid) return <div className="business-empty">Chưa có điểm chất lượng trong kỳ này.</div>;

  const coordinate = (value: number, index: number) => ({
    x: points.length === 1 ? 50 : index / (points.length - 1) * 100,
    y: 100 - value * 100,
  });
  const runs = (key: "faithfulness" | "relevancy") => {
    const result: string[] = [];
    let current: string[] = [];
    points.forEach((point, index) => {
      const value = point[key];
      if (value == null) {
        if (current.length) result.push(current.join(" "));
        current = [];
        return;
      }
      const { x, y } = coordinate(value, index);
      current.push(`${x},${y}`);
    });
    if (current.length) result.push(current.join(" "));
    return result;
  };
  const active = activeIndex == null ? null : points[activeIndex];

  return (
    <div className="business-quality-chart" onMouseLeave={() => setActiveIndex(null)}>
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" role="group" aria-label="Xu hướng faithfulness và relevancy">
        {[25, 50, 75].map((value) => <line key={value} x1="0" y1={value} x2="100" y2={value} className="business-quality-grid" />)}
        <line x1="0" y1={100 - threshold * 100} x2="100" y2={100 - threshold * 100} className="business-threshold" />
        {runs("faithfulness").map((run, index) => <polyline key={`faith-${index}`} points={run} className="business-quality-line business-quality-line--faith" />)}
        {runs("relevancy").map((run, index) => <polyline key={`relevant-${index}`} points={run} className="business-quality-line business-quality-line--relevant" />)}
        {points.map((point, index) => {
          const x = points.length === 1 ? 50 : index / (points.length - 1) * 100;
          return (
            <g key={point.date}>
              {activeIndex === index && <line x1={x} y1="0" x2={x} y2="100" className="business-quality-crosshair" />}
              <rect
                x={Math.max(0, x - 3)}
                y="0"
                width="6"
                height="100"
                className="business-quality-hitbox"
                tabIndex={0}
                role="button"
                aria-label={`${fullDate(point.date)}. Bám nguồn ${percent(point.faithfulness)}, liên quan ${percent(point.relevancy)}`}
                onPointerEnter={() => setActiveIndex(index)}
                onFocus={() => setActiveIndex(index)}
                onBlur={() => setActiveIndex(null)}
                onClick={() => onSelect(point)}
                onKeyDown={(event) => handleInteractiveKey(event, () => onSelect(point))}
              />
            </g>
          );
        })}
      </svg>
      {active && (
        <div className="business-quality-tooltip" role="tooltip">
          <strong>{fullDate(active.date)}</strong>
          <span>Bám nguồn <b>{percent(active.faithfulness)}</b></span>
          <span>Liên quan <b>{percent(active.relevancy)}</b></span>
        </div>
      )}
      <div className="business-quality-axis"><span>{shortDate(points[0].date)}</span><span>{shortDate(points[points.length - 1].date)}</span></div>
    </div>
  );
}

const LEAD_TIER_META = [
  { key: "hot" as const, label: "HOT", className: "badge badge-danger", hint: "Gọi ngay" },
  { key: "warm" as const, label: "WARM", className: "badge badge-warning", hint: "Theo dõi" },
  { key: "cold" as const, label: "COLD", className: "badge badge-muted", hint: "Chưa có tín hiệu" },
];

function LeadPanel({ leads }: { leads: LeadStats | null }) {
  if (!leads) return <div className="business-empty">Chưa tải được số liệu lead.</div>;
  if (!leads.totals.total) return <div className="business-empty">Chưa có lead nào được chấm trong kỳ này.</div>;

  const { totals } = leads;
  return (
    <>
      <div className="business-chart-summary">
        <span>Tổng lead <strong>{number(totals.total)}</strong></span>
        {/* The lead-CAPTURE KPI: whether requiring a phone at the gate is actually paying off. */}
        <span>Có số điện thoại <strong>{percent(leads.contact_rate)}</strong></span>
        <span>Điểm trung bình <strong>{leads.avg_score.toLocaleString("vi-VN", { maximumFractionDigits: 1 })}</strong></span>
      </div>

      <div className="business-lead-tiers">
        {LEAD_TIER_META.map((tier) => (
          <div className="business-lead-tier" key={tier.key}>
            <span className={tier.className}>{tier.label}</span>
            <strong>{number(totals[tier.key])}</strong>
            <small>{tier.hint}</small>
          </div>
        ))}
      </div>

      <div className="business-chart-summary">
        <span>Đã đăng ký <strong>{number(leads.registered)}</strong></span>
        <span>Ẩn danh <strong>{number(leads.anonymous)}</strong></span>
        {/* Makes the LLM cost brake measured rather than assumed — see lead_scoring_service. */}
        <span>Tỷ lệ gọi LLM <strong>{percent(leads.llm_enrichment.call_rate)}</strong></span>
      </div>
    </>
  );
}

export function AdminHome() {
  const { username } = useAuth();
  const [dashboard, setDashboard] = useState<BusinessDashboard | null>(null);
  // Leads live on their own endpoint, not inside /business: that one scopes every metric to
  // sessions owned by an official Sale, while a customer-chat session has no Sale until it
  // is claimed. See backend/schemas/admin_dashboard.py::LeadStatsResponse.
  const [leads, setLeads] = useState<LeadStats | null>(null);
  const [failed, setFailed] = useState(false);
  const [loading, setLoading] = useState(true);
  const [days, setDays] = useState(14);
  const [projectId, setProjectId] = useState("");
  const [saleId, setSaleId] = useState("");
  const [detail, setDetail] = useState<DashboardDetail | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [reclassificationOpen, setReclassificationOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setFailed(false);
    setLoading(true);
    adminDashboardApi.business(days, projectId, saleId)
      .then((result) => {
        if (!cancelled) setDashboard(result);
      })
      .catch(() => {
        if (!cancelled) {
          setFailed(true);
          setDashboard(null);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [days, projectId, saleId, refreshKey]);

  useEffect(() => {
    let cancelled = false;
    adminDashboardApi.leads(days, projectId)
      .then((result) => { if (!cancelled) setLeads(result); })
      .catch(() => { if (!cancelled) setLeads(null); });
    return () => { cancelled = true; };
  }, [days, projectId, refreshKey]);

  const data = dashboard ?? EMPTY;
  const maxProject = Math.max(1, ...data.top_projects.map((project) => project.sessions));
  const hitlRate = data.summary.hitl_required ? data.summary.hitl_confirmed / data.summary.hitl_required : null;
  const readyCategories = data.document_coverage.reduce((sum, project) => sum + project.ready_count, 0);
  const resetFilters = () => { setDays(14); setProjectId(""); setSaleId(""); setDetail(null); };
  const showDetail = (title: string, subtitle: string, rows: DashboardDetail["rows"]) => setDetail({ title, subtitle, rows });
  const comparisonPeriod = `${fullDate(data.period.previous_start)} – ${fullDate(data.period.previous_end)}`;

  const kpis = useMemo(() => {
    const current = data.summary;
    const previous: BusinessSummaryBase = data.previous_summary;
    return [
      {
        title: "Phiên tư vấn",
        value: number(current.sessions),
        caption: `${number(current.sessions)} phiên mở trong ${data.period_days} ngày`,
        tooltip: "Phiên mới của đội Sale chính thức trong kỳ đã chọn.",
        trend: countTrend(current.sessions, previous.sessions),
        icon: <ChatIcon size={21} />,
        rows: [{ label: "Kỳ hiện tại", value: current.sessions }, { label: "Kỳ trước", value: previous.sessions }],
      },
      {
        title: "Phiên có thông tin khách",
        value: number(current.customers),
        caption: "Phiên đã nhập tên khách hàng",
        tooltip: "Đây là số phiên có tên khách, không phải số khách hàng duy nhất.",
        trend: countTrend(current.customers, previous.customers),
        icon: <UsersIcon size={21} />,
        rows: [{ label: "Kỳ hiện tại", value: current.customers }, { label: "Kỳ trước", value: previous.customers }],
      },
      {
        title: "Câu hỏi tới AI",
        value: number(current.questions),
        caption: "Gom theo ngày gửi thực tế",
        tooltip: "Tin nhắn do Sale gửi tới AI, tính theo thời điểm gửi trong múi giờ nghiệp vụ.",
        trend: countTrend(current.questions, previous.questions),
        icon: <BotIcon size={21} />,
        rows: [{ label: "Kỳ hiện tại", value: current.questions }, { label: "Kỳ trước", value: previous.questions }],
      },
      {
        title: "Sale hoạt động",
        value: number(current.active_sales),
        caption: "Có phiên mới hoặc gửi câu hỏi",
        tooltip: "Tài khoản Sale chính thức có hoạt động tư vấn trong kỳ.",
        trend: countTrend(current.active_sales, previous.active_sales),
        icon: <ActivityIcon size={21} />,
        rows: [{ label: "Kỳ hiện tại", value: current.active_sales }, { label: "Kỳ trước", value: previous.active_sales }],
      },
      {
        title: "Tài liệu AI sẵn sàng",
        value: number(current.ready_documents),
        caption: `${number(readyCategories)} ô sẵn sàng trong bảng độ phủ`,
        tooltip: "Tài liệu hiện hành đã ingest hoàn tất và có thể dùng để truy xuất.",
        trend: { label: "Kho hiện hành", tone: "neutral" as TrendTone, description: "Chỉ số trạng thái hiện tại, không so sánh theo kỳ" },
        icon: <DocumentIcon size={21} />,
        rows: [{ label: "Tài liệu sẵn sàng", value: current.ready_documents }, { label: "Ô sẵn sàng trong bảng", value: readyCategories }],
      },
      {
        title: "Điểm tin cậy AI",
        value: current.verifier_avg == null ? "—" : percent(current.verifier_avg),
        caption: "Verifier trung bình trong kỳ",
        tooltip: "Điểm verifier trung bình trên các câu trả lời có chạy đánh giá.",
        trend: scoreTrend(current.verifier_avg, previous.verifier_avg),
        icon: <ShieldCheckIcon size={21} />,
        dark: true,
        rows: [{ label: "Kỳ hiện tại", value: percent(current.verifier_avg) }, { label: "Kỳ trước", value: percent(previous.verifier_avg) }],
      },
    ];
  }, [data, readyCategories]);

  return (
    <div className={`page business-dashboard${loading ? " is-loading" : ""}`} aria-busy={loading}>
      <div className="page-head business-dashboard-head">
        <div>
          <p className="business-eyebrow">Dashboard quản trị</p>
          <h2 className="page-title">Tổng quan hoạt động</h2>
          <p className="page-sub">Chào {username ?? "bạn"}, đây là dữ liệu tư vấn và chất lượng AI đang ghi nhận trong SalesMate.</p>
        </div>
        <div className="business-head-actions">
          <span className="business-period">{fullDate(data.period.current_start)} – {fullDate(data.period.current_end)}</span>
          <button type="button" className="business-refresh" onClick={() => setRefreshKey((value) => value + 1)} disabled={loading}>
            <RefreshIcon size={16} />{loading ? "Đang cập nhật" : "Làm mới"}
          </button>
        </div>
      </div>

      <div className="business-toolbar" aria-label="Bộ lọc dashboard">
        <div className="business-period-switch" aria-label="Khoảng thời gian">
          {[7, 14, 30].map((value) => <button type="button" key={value} className={days === value ? "is-active" : ""} onClick={() => setDays(value)}>{value} ngày</button>)}
        </div>
        <label>Dự án<select value={projectId} onChange={(event) => setProjectId(event.target.value)}><option value="">Tất cả dự án</option>{data.filter_options.projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label>
        <label>Nhân viên Sale<select value={saleId} onChange={(event) => setSaleId(event.target.value)}><option value="">Tất cả Sale</option>{data.filter_options.sales.map((sale) => <option key={sale.id} value={sale.id}>{sale.username}</option>)}</select></label>
        {(days !== 14 || projectId || saleId) && <button type="button" className="business-reset" onClick={resetFilters}>Đặt lại</button>}
      </div>

      {failed && <div className="business-notice">Không thể tải số liệu từ máy chủ. Hãy kiểm tra backend rồi bấm “Làm mới”.</div>}
      {loading && dashboard && <div className="business-updating" role="status">Đang lấy số liệu mới theo bộ lọc…</div>}

      <div className="business-kpi-grid">
        {kpis.map((kpi) => (
          <KpiCard
            key={kpi.title}
            {...kpi}
            loading={!dashboard}
            onClick={() => showDetail(kpi.title, `${kpi.tooltip} Kỳ so sánh: ${comparisonPeriod}.`, kpi.rows)}
          />
        ))}
      </div>

      <div className="business-main-grid">
        <section className="business-panel business-activity-panel">
          <div className="business-panel-head">
            <div><h3>Xu hướng tư vấn</h3><p>Phiên mới và câu hỏi gửi tới AI theo ngày</p></div>
            <div className="business-legend"><span><i className="legend-question" />Câu hỏi</span><span><i className="legend-session" />Phiên mới</span></div>
          </div>
          <div className="business-chart-summary">
            <span>Tổng câu hỏi <strong>{number(data.summary.questions)}</strong></span>
            <span>Phiên mới <strong>{number(data.summary.sessions)}</strong></span>
            <span>TB câu hỏi/phiên <strong>{data.summary.sessions ? (data.summary.questions / data.summary.sessions).toLocaleString("vi-VN", { maximumFractionDigits: 1 }) : "—"}</strong></span>
          </div>
          <ActivityChart
            points={data.activity}
            periodDays={data.period_days}
            onSelect={(point) => showDetail(`Hoạt động ngày ${fullDate(point.date)}`, "Số liệu theo ngày gửi thực tế", [{ label: "Phiên mới", value: point.sessions }, { label: "Câu hỏi AI", value: point.questions }])}
          />
          <p className="business-hover-hint">Di chuột hoặc dùng Tab vào từng điểm để xem số liệu.</p>
        </section>

        <section className="business-panel business-feedback-panel">
          <div className="business-panel-head"><div><h3>Phản hồi câu trả lời</h3><p>Mỗi câu trả lời lấy feedback mới nhất</p></div></div>
          <FeedbackDonut
            distribution={data.feedback_distribution}
            onSelect={(_key, label, count) => showDetail(`Feedback: ${label}`, "Phân bổ câu trả lời trong kỳ hiện tại", [{ label: "Số câu", value: count }, { label: "Tổng câu trả lời", value: Object.values(data.feedback_distribution).reduce((sum, value) => sum + value, 0) }])}
          />
          <p className="business-hover-hint">Rê vào từng phần biểu đồ để làm nổi và xem tỷ lệ.</p>
        </section>
      </div>

      <section className="business-panel">
        <div className="business-panel-head">
          <div>
            <h3>Lead theo mức độ sẵn sàng</h3>
            <p>Chấm sau mỗi lượt khách hỏi — HOT là sẵn sàng mua, không phải chi nhiều tiền</p>
          </div>
        </div>
        <LeadPanel leads={leads} />
      </section>

      <div className="business-bottom-grid">
        <section className="business-panel">
          <div className="business-panel-head"><div><h3>Dự án được quan tâm</h3><p>Xếp theo số phiên mới có gắn dự án</p></div></div>
          {data.top_projects.length === 0 ? <div className="business-empty">Các phiên hiện chưa ghi nhận dự án.</div> : <div className="business-ranking">{data.top_projects.map((project, index) => <button type="button" className="business-rank-row" key={project.project_id ?? "unknown"} onClick={() => { if (project.project_id) setProjectId(project.project_id); showDetail(project.name, project.project_id ? "Dashboard đã lọc theo dự án này" : "Các phiên chưa gắn dự án", [{ label: "Phiên tư vấn", value: project.sessions }]); }}><span className="business-rank-number">{index + 1}</span><span className="business-rank-main"><span><strong>{project.name}</strong><span>{project.sessions} phiên</span></span><span className="business-progress"><i style={{ width: `${project.sessions / maxProject * 100}%` }} /></span></span><span className="business-row-tooltip">Nhấn để lọc dashboard</span></button>)}</div>}
        </section>

        <section className="business-panel">
          <div className="business-panel-head"><div><h3>Hoạt động đội Sale</h3><p>Top nhân viên theo phiên và câu hỏi trong kỳ</p></div></div>
          {data.top_sales.length === 0 ? <div className="business-empty">Chưa có Sale hoạt động trong kỳ này.</div> : <div className="business-sale-table"><div className="business-sale-table-head"><span>Nhân viên</span><span>Khách</span><span>Phiên</span><span>Hỏi AI</span></div>{data.top_sales.map((sale) => <button type="button" className="business-sale-row" key={sale.sale_id} onClick={() => { setSaleId(String(sale.sale_id)); showDetail(sale.username, "Dashboard đã lọc theo nhân viên này", [{ label: "Phiên có tên khách", value: sale.customers }, { label: "Phiên mới", value: sale.sessions }, { label: "Câu hỏi AI", value: sale.questions }]); }}><span><i>{sale.username.slice(0, 1).toUpperCase()}</i>{sale.username}</span><strong>{sale.customers}</strong><strong>{sale.sessions}</strong><strong>{sale.questions}</strong></button>)}</div>}
        </section>
      </div>

      <div className="business-detail-grid">
        <section className="business-panel business-quality-panel">
          <div className="business-panel-head"><div><h3>Chất lượng tư vấn</h3><p>Các chỉ số an toàn đang ghi nhận</p></div></div>
          <div className="business-quality-list">
            <button type="button" onClick={() => showDetail("Feedback hữu ích", "Chỉ tính các câu đã được đánh giá", [{ label: "Tỷ lệ", value: percent(data.summary.helpful_rate) }])}><span>Feedback hữu ích</span><strong>{percent(data.summary.helpful_rate)}</strong><small>Trên các câu có feedback</small></button>
            <button type="button" onClick={() => showDetail("Điểm verifier", "Trung bình các câu có chạy verifier", [{ label: "Điểm", value: percent(data.summary.verifier_avg) }, { label: "Ngưỡng", value: percent(data.verifier_threshold) }])}><span>Verifier trung bình</span><strong>{percent(data.summary.verifier_avg)}</strong><small>Ngưỡng hiện tại {percent(data.verifier_threshold)}</small></button>
            <button type="button" onClick={() => showDetail("Xác nhận HITL", "Nội dung giá và cam kết cần Sale xác nhận", [{ label: "Đã xác nhận", value: data.summary.hitl_confirmed }, { label: "Cần xác nhận", value: data.summary.hitl_required }])}><span>Xác nhận nội dung rủi ro</span><strong>{percent(hitlRate)}</strong><small>{data.summary.hitl_confirmed}/{data.summary.hitl_required} câu cần HITL</small></button>
          </div>
        </section>

        <section className="business-panel">
          <div className="business-panel-head"><div><h3>Phễu kiểm soát HITL</h3><p>Tuân thủ với nội dung giá và cam kết</p></div></div>
          <div className="business-funnel">
            <button type="button" style={{ width: "100%" }} onClick={() => showDetail("Câu trả lời AI", "Tổng câu trả lời trong kỳ", [{ label: "Số câu", value: data.hitl_funnel.answers }])}><span>Câu trả lời AI</span><strong>{data.hitl_funnel.answers}</strong></button>
            <button type="button" style={{ width: `${Math.max(48, data.hitl_funnel.answers ? data.hitl_funnel.required / data.hitl_funnel.answers * 100 : 48)}%` }} onClick={() => showDetail("Cần xác nhận HITL", "Nội dung liên quan giá hoặc cam kết", [{ label: "Số câu", value: data.hitl_funnel.required }, { label: "Chưa xác nhận", value: Math.max(0, data.hitl_funnel.required - data.hitl_funnel.confirmed) }])}><span>Cần xác nhận</span><strong>{data.hitl_funnel.required}</strong></button>
            <button type="button" style={{ width: `${Math.max(32, data.hitl_funnel.required ? data.hitl_funnel.confirmed / data.hitl_funnel.required * 100 : 32)}%` }} onClick={() => showDetail("Đã xác nhận HITL", "Nội dung đã được Sale xác nhận", [{ label: "Số câu", value: data.hitl_funnel.confirmed }])}><span>Đã xác nhận</span><strong>{data.hitl_funnel.confirmed}</strong></button>
          </div>
        </section>

        <section className="business-panel business-quality-trend-panel">
          <div className="business-panel-head"><div><h3>Xu hướng chất lượng AI</h3><p>Bám nguồn và độ liên quan theo ngày</p></div><div className="business-legend"><span><i className="legend-faith" />Bám nguồn</span><span><i className="legend-relevant" />Liên quan</span></div></div>
          <QualityChart points={data.quality_trend} threshold={data.verifier_threshold} onSelect={(point) => showDetail(`Chất lượng ngày ${fullDate(point.date)}`, `Ngưỡng verifier: ${percent(data.verifier_threshold)}`, [{ label: "Bám nguồn", value: percent(point.faithfulness) }, { label: "Liên quan", value: percent(point.relevancy) }])} />
        </section>
      </div>

      <section className="business-panel business-coverage-panel">
        <div className="business-panel-head"><div><h3>Độ phủ tài liệu theo dự án</h3><p>Metadata xác định ô liên quan; ô xanh chỉ khi tài liệu đã duyệt, ingest xong và project_id khớp để AI truy xuất</p></div><div className="business-coverage-actions"><div className="business-coverage-legend"><span><i className="coverage-ready" />Sẵn sàng</span><span><i className="coverage-pending_review" />Chờ duyệt</span><span><i className="coverage-unavailable" />Chưa sẵn sàng</span><span><i className="coverage-missing" />Chưa có</span></div><button className="btn btn-sm btn-outline business-reclassify-button" type="button" onClick={() => setReclassificationOpen(true)}><SparklesIcon size={15} />Phân loại lại bằng AI</button></div></div>
        {data.document_coverage.length === 0 ? <div className="business-empty">Chưa có dữ liệu dự án.</div> : <div className="business-coverage-table"><div className="business-coverage-head"><span>Dự án</span>{Object.values(CATEGORY_LABELS).map((label) => <span key={label}>{label}</span>)}</div>{data.document_coverage.map((project) => <div className="business-coverage-row" key={project.project_id}><strong>{project.name}</strong>{Object.keys(CATEGORY_LABELS).map((category) => { const state = project.categories[category] ?? "missing"; const stateLabel = COVERAGE_STATE_LABELS[state]; return <Link key={category} to={`/documents?coverage_scope=${encodeURIComponent(project.project_id)}&category=${category}`} className={`coverage-cell coverage-${state}`} title={`${CATEGORY_LABELS[category]} · ${stateLabel}`} aria-label={`${CATEGORY_LABELS[category]} của ${project.name}: ${stateLabel}`}><i /></Link>; })}</div>)}</div>}
      </section>

      {detail && <aside className="business-detail-drawer" aria-live="polite"><div><div><p>Chi tiết dashboard</p><h3>{detail.title}</h3><span>{detail.subtitle}</span></div><button type="button" onClick={() => setDetail(null)} aria-label="Đóng chi tiết">×</button></div><dl>{detail.rows.map((row) => <div key={row.label}><dt>{row.label}</dt><dd>{row.value}</dd></div>)}</dl></aside>}

      <LegacyReclassificationModal
        open={reclassificationOpen}
        onClose={() => setReclassificationOpen(false)}
        onApplied={() => setRefreshKey((value) => value + 1)}
      />

      <p className="business-footnote">Nguồn: dữ liệu MySQL của SalesMate, gom ngày theo {data.period.timezone}. Dashboard không hiển thị doanh thu, hợp đồng hay tỷ lệ chốt vì hệ thống chưa lưu các dữ liệu này.</p>
    </div>
  );
}
