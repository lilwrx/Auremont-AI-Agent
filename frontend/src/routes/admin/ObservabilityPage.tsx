import { type ReactNode, useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { adminDashboardApi } from "../../api/adminDashboard";
import {
  ActivityIcon,
  AlertIcon,
  ApiIcon,
  BotIcon,
  ChartIcon,
  RefreshIcon,
  ServerIcon,
  TerminalIcon,
  UsersIcon,
} from "../../components/Icons";
import { ApiTester } from "../../components/admin/ApiTester";
import { SwaggerConsoleModal } from "../../components/admin/SwaggerConsoleModal";
import { TraceTimeline } from "../../components/admin/TraceTimeline";
import type { ObservabilityOverview, TraceSummary } from "../../types/admin";
import { parseServerDate } from "../../utils/datetime";

const number = new Intl.NumberFormat("vi-VN");
const dateTime = new Intl.DateTimeFormat("vi-VN", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

type DashboardDetail = {
  title: string;
  subtitle: string;
  rows: { label: string; value: string | number }[];
};

interface OpsKpiProps {
  label: string;
  value: string | number;
  hint: string;
  tooltip: string;
  badge: string;
  badgeTone?: "up" | "down" | "neutral";
  icon: ReactNode;
  dark?: boolean;
  onClick: () => void;
}

function OpsKpi({ label, value, hint, tooltip, badge, badgeTone = "neutral", icon, dark, onClick }: OpsKpiProps) {
  return (
    <button
      type="button"
      className={`business-kpi ops-kpi${dark ? " business-kpi--dark" : ""}`}
      onClick={onClick}
      aria-label={`${label}: ${value}. ${tooltip}`}
    >
      <span className="business-kpi-top">
        <i className="business-kpi-icon" aria-hidden="true">{icon}</i>
        <span className={`business-trend business-trend--${badgeTone}`}>{badge}</span>
      </span>
      <span className="business-kpi-title">{label}</span>
      <strong>{value}</strong>
      <small>{hint}</small>
      <span className="business-kpi-tooltip" role="tooltip">
        <b>{tooltip}</b>
        <em>Nhấn để xem số liệu chi tiết</em>
      </span>
    </button>
  );
}

interface InteractiveBarsProps {
  rows: { label: string; count: number }[];
  noun: string;
  onSelect: (row: { label: string; count: number }, rank: number) => void;
}

function InteractiveBars({ rows, noun, onSelect }: InteractiveBarsProps) {
  const max = Math.max(...rows.map((row) => row.count), 1);
  const total = rows.reduce((sum, row) => sum + row.count, 0);
  const [activeLabel, setActiveLabel] = useState<string | null>(null);

  if (!rows.some((row) => row.count)) {
    return (
      <div className="ops-empty-state">
        <ChartIcon size={24} />
        <strong>Chưa có dữ liệu trong kỳ</strong>
        <span>Dữ liệu sẽ xuất hiện khi hệ thống ghi nhận tương tác mới.</span>
      </div>
    );
  }

  return (
    <div className="business-ranking ops-ranking" onPointerLeave={() => setActiveLabel(null)}>
      {rows.map((row, index) => {
        const share = total ? row.count / total * 100 : 0;
        return (
          <button
            type="button"
            className={`business-rank-row${activeLabel === row.label ? " is-active" : ""}`}
            key={row.label}
            onPointerEnter={() => setActiveLabel(row.label)}
            onFocus={() => setActiveLabel(row.label)}
            onBlur={() => setActiveLabel(null)}
            onClick={() => onSelect(row, index + 1)}
          >
            <span className="business-rank-number">{index + 1}</span>
            <span className="business-rank-main">
              <span><strong>{row.label}</strong><span>{number.format(row.count)} {noun}</span></span>
              <i className="business-progress"><i style={{ width: `${row.count / max * 100}%` }} /></i>
            </span>
            <span className="business-row-tooltip">{share.toFixed(1)}% tổng dữ liệu · nhấn để xem</span>
          </button>
        );
      })}
    </div>
  );
}

interface TokenChartProps {
  tokens: ObservabilityOverview["tokens"];
  onSelect: (day: ObservabilityOverview["tokens"]["daily"][number]) => void;
}

function TokenChart({ tokens, onSelect }: TokenChartProps) {
  const [activeIndex, setActiveIndex] = useState<number | null>(null);
  const max = Math.max(...tokens.daily.map((day) => day.input_tokens + day.output_tokens), 1);
  const active = activeIndex == null ? null : tokens.daily[activeIndex];

  return (
    <div className="ops-token-visual" onPointerLeave={() => setActiveIndex(null)}>
      <div className={`ops-token-readout${active ? " is-active" : ""}`} aria-live="polite">
        <div><span>{active ? active.date : "Toàn kỳ"}</span><strong>{number.format(active ? active.input_tokens + active.output_tokens : tokens.input_tokens + tokens.output_tokens)} token</strong></div>
        <div><span>Input</span><strong>{number.format(active?.input_tokens ?? tokens.input_tokens)}</strong></div>
        <div><span>Output</span><strong>{number.format(active?.output_tokens ?? tokens.output_tokens)}</strong></div>
        <div><span>Chi phí</span><strong>{tokens.cost_configured ? `$${(active?.estimated_cost_usd ?? tokens.estimated_cost_usd).toFixed(4)}` : "Chưa cấu hình"}</strong></div>
      </div>
      <div className="token-chart ops-token-chart" aria-label="Biểu đồ token theo ngày">
        {tokens.daily.map((day, index) => {
          const total = day.input_tokens + day.output_tokens;
          return (
            <button
              type="button"
              className={`token-day${activeIndex === index ? " is-active" : ""}`}
              key={day.date}
              onPointerEnter={() => setActiveIndex(index)}
              onFocus={() => setActiveIndex(index)}
              onBlur={() => setActiveIndex(null)}
              onClick={() => onSelect(day)}
              aria-label={`${day.date}: ${total} token`}
            >
              <span className="token-stack" style={{ height: `${Math.max(total / max * 100, total ? 5 : 1)}%` }}>
                <i className="token-input" style={{ flex: day.input_tokens || 0 }} />
                <i className="token-output" style={{ flex: day.output_tokens || 0 }} />
              </span>
              <small>{day.date.slice(5).replace("-", "/")}</small>
            </button>
          );
        })}
      </div>
      <div className="chart-legend ops-chart-legend">
        <span><i className="legend-input" /> Input</span>
        <span><i className="legend-output" /> Output</span>
        <em>Rê chuột hoặc dùng Tab để xem từng ngày</em>
      </div>
    </div>
  );
}

export function ObservabilityPage() {
  const [data, setData] = useState<ObservabilityOverview | null>(null);
  const [days, setDays] = useState(14);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [swaggerOpen, setSwaggerOpen] = useState(false);
  const [selectedTrace, setSelectedTrace] = useState<TraceSummary | null>(null);
  const [selectedTool, setSelectedTool] = useState<string | null>(null);
  const [severity, setSeverity] = useState("ALL");
  const [module, setModule] = useState("ALL");
  const [detail, setDetail] = useState<DashboardDetail | null>(null);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const next = await adminDashboardApi.observability(days);
      setData(next);
      setSelectedTrace((current) => next.traces.find((trace) => trace.run_id === current?.run_id) ?? next.traces[0] ?? null);
      setSelectedTool((current) => next.tool_reliability.some((tool) => tool.key === current) ? current : null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Không tải được dữ liệu giám sát.");
    } finally {
      setLoading(false);
    }
  }, [days]);

  useEffect(() => { void load(); }, [load]);

  const modules = useMemo(() => [...new Set(data?.logs.map((log) => log.module) ?? [])], [data]);
  const filteredLogs = useMemo(
    () => (data?.logs ?? []).filter((log) => (severity === "ALL" || log.severity === severity) && (module === "ALL" || log.module === module)),
    [data, severity, module],
  );

  const showDetail = (title: string, subtitle: string, rows: DashboardDetail["rows"]) => {
    setDetail({ title, subtitle, rows });
  };

  return (
    <div className="page admin-dashboard-page business-dashboard observability-dashboard">
      <header className="admin-page-head business-dashboard-head ops-dashboard-head">
        <div>
          <p className="business-eyebrow">AI & platform operations</p>
          <h1 className="page-title">Giám sát hệ thống</h1>
          <p className="page-sub">Theo dõi độ tin cậy AI, token, trace và tín hiệu cần Sale can thiệp theo thời gian thực.</p>
        </div>
        <div className="business-head-actions ops-head-actions">
          {data && <span className="business-period ops-live-status"><i /> Cập nhật {dateTime.format(parseServerDate(data.generated_at))}</span>}
          <button className="business-refresh" type="button" disabled={loading} onClick={() => void load()}>
            <RefreshIcon size={15} className={loading ? "is-spinning" : ""} /> {loading ? "Đang tải" : "Làm mới"}
          </button>
          <button className="btn btn-primary" type="button" onClick={() => setSwaggerOpen(true)}><ApiIcon size={16} /> FastAPI Console</button>
        </div>
      </header>

      <div className="business-toolbar ops-toolbar" aria-label="Bộ lọc thời gian">
        <span className="ops-toolbar-label">Khoảng thời gian</span>
        <div className="business-period-switch">
          {[7, 14, 30].map((value) => <button type="button" key={value} className={days === value ? "is-active" : ""} onClick={() => setDays(value)}>{value} ngày</button>)}
        </div>
        <span className={`ops-collector-status ${data?.tracing_enabled ? "is-online" : "is-offline"}`}><i />{data?.tracing_enabled ? "MySQL metrics đang hoạt động" : "Metrics đang tắt"}</span>
      </div>

      {error && <div className="business-notice">{error}</div>}
      {loading && data && <div className="business-updating">Đang đồng bộ dữ liệu mới từ backend…</div>}
      {!data ? <div className="ops-loading"><span /><strong>Đang tải trung tâm giám sát…</strong></div> : <>
        <div className="business-kpi-grid ops-kpi-grid">
          <OpsKpi
            label="DAU / MAU"
            value={`${data.users.dau} / ${data.users.mau}`}
            hint="Người dùng có hoạt động audit"
            tooltip="DAU là người dùng hoạt động trong 24 giờ; MAU là số người dùng trong 30 ngày."
            badge={`${data.users.mau ? Math.round(data.users.dau / data.users.mau * 100) : 0}% active`}
            badgeTone={data.users.dau ? "up" : "neutral"}
            icon={<UsersIcon size={21} />}
            onClick={() => showDetail("Mức độ hoạt động người dùng", "Tổng hợp từ business audit activity trong MySQL.", [
              { label: "Daily Active Users", value: data.users.dau },
              { label: "Monthly Active Users", value: data.users.mau },
              { label: "Tỷ lệ DAU/MAU", value: `${data.users.mau ? (data.users.dau / data.users.mau * 100).toFixed(1) : 0}%` },
            ])}
          />
          <OpsKpi
            label="Active sessions"
            value={number.format(data.users.active_sessions)}
            hint={`${data.users.waiting_sessions} phiên đang chờ Sale`}
            tooltip="Bao gồm các phiên đang chờ tiếp nhận và các phiên Sale đang xử lý."
            badge={data.users.waiting_sessions ? `${data.users.waiting_sessions} cần xử lý` : "Ổn định"}
            badgeTone={data.users.waiting_sessions ? "down" : "up"}
            icon={<ActivityIcon size={21} />}
            onClick={() => showDetail("Tình trạng phiên chat", "Số liệu trực tiếp từ bảng chat_sessions.", [
              { label: "Phiên đang hoạt động", value: data.users.active_sessions },
              { label: "Đang chờ Sale", value: data.users.waiting_sessions },
              { label: "Đang được xử lý", value: Math.max(data.users.active_sessions - data.users.waiting_sessions, 0) },
            ])}
          />
          <OpsKpi
            label="Tokens trong kỳ"
            value={number.format(data.tokens.input_tokens + data.tokens.output_tokens)}
            hint={`${number.format(data.tokens.input_tokens)} input · ${number.format(data.tokens.output_tokens)} output`}
            tooltip="Token được ghi từ phản hồi usage của Gemini, gồm chat, verifier, phân loại và kiểm tra xung đột."
            badge={`${days} ngày`}
            icon={<BotIcon size={21} />}
            onClick={() => showDetail("Mức tiêu thụ token", `Dữ liệu provider trong ${days} ngày gần nhất.`, [
              { label: "Input token", value: number.format(data.tokens.input_tokens) },
              { label: "Output token", value: number.format(data.tokens.output_tokens) },
              { label: "Tổng token", value: number.format(data.tokens.input_tokens + data.tokens.output_tokens) },
            ])}
          />
          <OpsKpi
            label="Chi phí ước tính"
            value={data.tokens.cost_configured ? `$${data.tokens.estimated_cost_usd.toFixed(2)}` : "Chưa cấu hình"}
            hint={data.tokens.cost_configured ? `Dự phóng tháng $${data.tokens.projected_monthly_cost_usd.toFixed(2)}` : "Cần thiết lập đơn giá token"}
            tooltip={data.tokens.cost_configured ? "Ước tính từ token thực tế và đơn giá đã cấu hình." : "Backend đã ghi token; chỉ thiếu đơn giá input/output để quy đổi chi phí."}
            badge={data.tokens.cost_configured ? "USD" : "Cần thiết lập"}
            badgeTone={data.tokens.cost_configured ? "up" : "neutral"}
            icon={<ChartIcon size={21} />}
            dark
            onClick={() => showDetail("Chi phí AI ước tính", "Không tự giả định bảng giá của nhà cung cấp.", [
              { label: "Chi phí trong kỳ", value: data.tokens.cost_configured ? `$${data.tokens.estimated_cost_usd.toFixed(4)}` : "Chưa cấu hình" },
              { label: "Dự phóng 30 ngày", value: data.tokens.cost_configured ? `$${data.tokens.projected_monthly_cost_usd.toFixed(4)}` : "Chưa cấu hình" },
              { label: "Trạng thái đơn giá", value: data.tokens.cost_configured ? "Đã cấu hình" : "Thiếu đơn giá môi trường" },
            ])}
          />
        </div>

        <div className="admin-two-column ops-primary-grid">
          <section className="business-panel ops-panel">
            <div className="business-panel-head">
              <div><h3>Tool Reliability</h3><p>Nhấn một công cụ để xem success rate, lỗi và độ trễ chi tiết.</p></div>
              <span className="ops-panel-icon"><ServerIcon size={19} /></span>
            </div>
            {!data.tracing_enabled && <div className="admin-inline-note">Thu thập metrics đang tắt. Bật <code>OBSERVABILITY_METRICS_ENABLED=true</code> để lưu dữ liệu vào MySQL.</div>}
            <div className="tool-list ops-tool-list">
              {data.tool_reliability.map((tool) => (
                <button
                  type="button"
                  key={tool.key}
                  className={`tool-row ops-tool-row${selectedTool === tool.key ? " is-active" : ""}`}
                  onClick={() => {
                    setSelectedTool(tool.key);
                    showDetail(tool.name, "Hiệu năng được tổng hợp từ các pipeline trace trong kỳ.", [
                      { label: "Số lần gọi", value: number.format(tool.calls) },
                      { label: "Số lỗi", value: number.format(tool.errors) },
                      { label: "Tỷ lệ thành công", value: tool.success_rate == null ? "Chưa đủ dữ liệu" : `${tool.success_rate}%` },
                      { label: "Latency trung bình", value: tool.average_latency_ms == null ? "Chưa đo" : `${number.format(tool.average_latency_ms)} ms` },
                    ]);
                  }}
                >
                  <span className="tool-row-title"><strong>{tool.name}</strong><span>{tool.calls} calls · {tool.errors} errors</span></span>
                  <span className="tool-progress"><i><span className={tool.success_rate != null && tool.success_rate < 90 ? "is-warning" : ""} style={{ width: `${tool.success_rate ?? 0}%` }} /></i><strong>{tool.success_rate == null ? "—" : `${tool.success_rate}%`}</strong></span>
                  <span className="tool-latency">{tool.average_latency_ms == null ? "Chưa đo latency" : `${number.format(tool.average_latency_ms)} ms avg`}</span>
                  <span className="ops-row-hover">Nhấn để xem chi tiết</span>
                </button>
              ))}
            </div>
          </section>

          <section className="business-panel ops-panel ops-token-panel">
            <div className="business-panel-head">
              <div><h3>Token Consumption</h3><p>Input và output token theo từng ngày trong khoảng đã chọn.</p></div>
              <span className="ops-panel-icon"><ChartIcon size={19} /></span>
            </div>
            <TokenChart tokens={data.tokens} onSelect={(day) => showDetail(`Token ngày ${day.date}`, "Số liệu usage do Gemini trả về.", [
              { label: "Input token", value: number.format(day.input_tokens) },
              { label: "Output token", value: number.format(day.output_tokens) },
              { label: "Tổng token", value: number.format(day.input_tokens + day.output_tokens) },
              { label: "Chi phí", value: data.tokens.cost_configured ? `$${day.estimated_cost_usd.toFixed(4)}` : "Chưa cấu hình" },
            ])} />
          </section>
        </div>

        <div className="admin-two-column ops-analytics-grid">
          <section className="business-panel ops-panel">
            <div className="business-panel-head"><div><h3>Real Estate Intent Analytics</h3><p>Phân khúc ngân sách được khách nhắc đến nhiều nhất.</p></div><span className="ops-caption-badge">Customer intent</span></div>
            <InteractiveBars rows={data.budget_intents} noun="lượt" onSelect={(row, rank) => showDetail(row.label, "Phân khúc ngân sách được trích xuất từ câu hỏi khách hàng.", [
              { label: "Xếp hạng", value: `#${rank}` },
              { label: "Số lượt nhắc", value: number.format(row.count) },
              { label: "Khoảng thời gian", value: `${days} ngày` },
            ])} />
          </section>
          <section className="business-panel ops-panel">
            <div className="business-panel-head"><div><h3>Dự án được hỏi nhiều</h3><p>Dựa trên project gắn với các phiên khách trong kỳ.</p></div><span className="ops-caption-badge">Top projects</span></div>
            <InteractiveBars rows={data.popular_projects.map((item) => ({ label: item.project_name, count: item.count }))} noun="phiên" onSelect={(row, rank) => showDetail(row.label, "Mức độ quan tâm theo số phiên khách hàng.", [
              { label: "Xếp hạng", value: `#${rank}` },
              { label: "Số phiên", value: number.format(row.count) },
              { label: "Khoảng thời gian", value: `${days} ngày` },
            ])} />
          </section>
        </div>

        <section className="business-panel ops-panel fallback-panel ops-fallback-panel">
          <div className="business-panel-head"><div><h3>AI Fallback & Intervention</h3><p>Câu trả lời dưới ngưỡng Verifier cần người kiểm tra hoặc Sale tiếp quản.</p></div><span className={`admin-count-badge ${data.fallback_alerts.length ? "is-danger" : ""}`}>{data.fallback_alerts.length} cảnh báo</span></div>
          {data.fallback_alerts.length === 0 ? <div className="ops-empty-state compact"><AlertIcon size={23} /><strong>Không có fallback cần can thiệp</strong><span>Hệ thống đang vận hành trong ngưỡng an toàn.</span></div> : <div className="fallback-list">{data.fallback_alerts.map((alert) => <article className={`fallback-row fallback-row--${alert.severity}`} key={alert.message_id}><AlertIcon size={18} /><div><strong>{alert.customer_question ?? `Phiên #${alert.session_id ?? "—"}`}</strong><span>{alert.failure_mode ?? "low_confidence"} · score {alert.verifier_score.toFixed(2)} · {dateTime.format(parseServerDate(alert.created_at))}</span></div><Link className="btn btn-sm btn-outline" to="/sales#sessions">Điều phối Sale</Link></article>)}</div>}
        </section>

        <div className="admin-two-column admin-two-column--wide-left ops-trace-grid">
          <section className="business-panel ops-panel">
            <div className="business-panel-head"><div><h3>Audit Trace Visualizer</h3><p>Prompt → Retrieval → Tool Call → Response; không lưu nội dung prompt.</p></div><span className="ops-panel-icon"><TerminalIcon size={19} /></span></div>
            <div className="trace-layout"><div className="trace-list">{data.traces.length === 0 ? <span className="ops-empty-inline">Chưa có trace mới.</span> : data.traces.map((trace) => <button type="button" key={trace.run_id} className={selectedTrace?.run_id === trace.run_id ? "is-active" : ""} onClick={() => setSelectedTrace(trace)}><code>{trace.run_id}</code><span>{parseServerDate(trace.started_at).toLocaleTimeString("vi-VN")} · {Math.round(trace.duration_ms)} ms</span></button>)}</div><TraceTimeline trace={selectedTrace} /></div>
          </section>
          <section className="business-panel ops-panel"><div className="business-panel-head"><div><h3>Most Used Modules</h3><p>Tần suất business audit event theo module.</p></div><span className="ops-caption-badge">Audit events</span></div><InteractiveBars rows={data.most_used_modules.map((item) => ({ label: item.module, count: item.calls }))} noun="events" onSelect={(row, rank) => showDetail(`Module ${row.label}`, "Tần suất audit event trong khoảng thời gian đang chọn.", [{ label: "Xếp hạng", value: `#${rank}` }, { label: "Số event", value: number.format(row.count) }, { label: "Khoảng thời gian", value: `${days} ngày` }])} /></section>
        </div>

        <section className="business-panel ops-panel ops-log-panel">
          <div className="business-panel-head"><div><h3>Log Stream</h3><p>Business audit log có thể lọc và mở chi tiết từng sự kiện.</p></div><div className="log-filters"><select value={severity} onChange={(event) => setSeverity(event.target.value)} aria-label="Lọc severity"><option value="ALL">Mọi severity</option><option>INFO</option><option>WARN</option><option>ERROR</option></select><select value={module} onChange={(event) => setModule(event.target.value)} aria-label="Lọc module"><option value="ALL">Mọi module</option>{modules.map((value) => <option key={value}>{value}</option>)}</select></div></div>
          <div className="log-stream">{filteredLogs.length === 0 ? <div className="ops-empty-inline">Không có log khớp bộ lọc.</div> : filteredLogs.map((log) => <button type="button" className="log-row ops-log-row" key={log.id} onClick={() => showDetail(log.event, "Chi tiết business audit event.", [{ label: "Thời gian", value: dateTime.format(parseServerDate(log.timestamp)) }, { label: "Severity", value: log.severity }, { label: "Module", value: log.module }, { label: "Người dùng", value: log.username ?? "system" }, { label: "Request ID", value: log.request_id ?? "—" }])}><time>{dateTime.format(parseServerDate(log.timestamp))}</time><span className={`log-level log-level--${log.severity.toLowerCase()}`}>{log.severity}</span><code>{log.module}</code><strong>{log.event}</strong><span>{log.username ?? "system"}</span><code>{log.request_id?.slice(0, 8) ?? "—"}</code></button>)}</div>
        </section>

        <section className="business-panel ops-panel ops-api-panel"><div className="business-panel-head"><div><h3>Interactive API Tester</h3><p>Gọi nhanh RAG, Chat và Lead routing bằng token Admin hiện tại.</p></div><span className="ops-panel-icon"><ApiIcon size={19} /></span></div><ApiTester /></section>

        {detail && <aside className="business-detail-drawer ops-detail-drawer" aria-live="polite"><div><div><p>Chi tiết giám sát</p><h3>{detail.title}</h3><span>{detail.subtitle}</span></div><button type="button" onClick={() => setDetail(null)} aria-label="Đóng chi tiết">×</button></div><dl>{detail.rows.map((row) => <div key={row.label}><dt>{row.label}</dt><dd>{row.value}</dd></div>)}</dl></aside>}
      </>}
      <SwaggerConsoleModal open={swaggerOpen} onClose={() => setSwaggerOpen(false)} />
    </div>
  );
}
