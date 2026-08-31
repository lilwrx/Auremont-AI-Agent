import { useCallback, useEffect, useState, type CSSProperties, type ReactNode } from "react";
import { api } from "../../api/client";
import { AdminMetricCard } from "../../components/admin/AdminMetricCard";
import { AdminPageHeader } from "../../components/admin/AdminPageHeader";
import {
  ActivityIcon,
  ChartIcon,
  CheckIcon,
  ClockIcon,
  RefreshIcon,
  ShieldCheckIcon,
  SparklesIcon,
  XIcon,
} from "../../components/Icons";

interface FailedQuestion {
  message_id: number;
  question: string;
  feedback_count: number;
}

interface EvalScores {
  faithfulness_avg: number | null;
  answer_relevancy_avg: number | null;
  top_failed_questions: FailedQuestion[];
}

interface DeepEvalMetric {
  total: number;
  passed: number;
  failed: number;
  mean_score: number;
  examples: string[];
}

interface DeepEvalCase {
  attempts: number;
  passed: number;
  pass_rate: number;
  flaky: boolean;
}

interface DeepEvalReport {
  cases: number;
  runs: number;
  passed: number;
  failed: number;
  pass_rate: number;
  deterministic_pass_rate: number | null;
  judged_pass_rate: number | null;
  complete: boolean;
  answer_model: string;
  judge_model: string;
  independent_judge: boolean;
  deterministic_metrics: string[];
  metrics: Record<string, DeepEvalMetric>;
  per_case: Record<string, DeepEvalCase>;
  flaky_cases: string[];
}

interface PipelineGrader {
  total: number;
  passed: number;
  failed: number;
  examples: string[];
}

interface PipelineEvalReport {
  runs: number;
  passed: number;
  failed: number;
  pass_rate: number;
  outcomes: Record<string, number>;
  failure_modes: Record<string, number>;
  graders: Record<string, PipelineGrader>;
  latency_ms: { p50: number | null; p95: number | null; max: number | null };
  retries: number;
}

interface EvalArtifact<T> {
  status: "ready" | "missing" | "invalid";
  source: "artifact" | "live_traces" | null;
  generated_at: string | null;
  report: T | null;
  message: string | null;
}

interface EvalReports {
  deepeval: EvalArtifact<DeepEvalReport>;
  evaluation: EvalArtifact<PipelineEvalReport>;
}

const METRIC_LABELS: Record<string, string> = {
  Faithfulness: "Bám sát nguồn",
  AnswerRelevancy: "Độ liên quan",
  "Answer Correctness [GEval]": "Độ chính xác",
  "No Invented Figures [GEval]": "Không bịa số liệu",
  "Required Facts": "Đủ thông tin bắt buộc",
  "Forbidden Content": "Không có nội dung cấm",
  "Listing Discipline": "Kỷ luật gợi ý căn",
  answered_runs_are_grounded: "Câu trả lời có nguồn",
  retrieval_ran_when_needed: "Retrieval chạy khi cần",
  inventory_tool_called_when_needed: "Tra tồn kho khi cần",
  retries_carry_a_correction: "Retry có hiệu chỉnh",
  latency_within_budget: "Latency trong ngân sách",
};

function metricLabel(name: string): string {
  return METRIC_LABELS[name] ?? name.replaceAll("_", " ");
}

function percent(value: number | null): string {
  return value == null ? "—" : `${Math.round(value * 100)}%`;
}

function scoreTone(value: number | null): "success" | "warning" | "danger" {
  if (value == null || value < 0.7) return "danger";
  return value >= 0.85 ? "success" : "warning";
}

function formatGeneratedAt(value: string | null): string {
  if (!value) return "Chưa có lần chạy";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "Không rõ thời gian";
  return parsed.toLocaleString("vi-VN");
}

function formatLatency(value: number | null): string {
  return value == null ? "—" : `${Math.round(value).toLocaleString("vi-VN")} ms`;
}

function QualityGauge({ label, value, description }: { label: string; value: number | null; description: string }) {
  const score = value == null ? 0 : Math.round(value * 100);
  const tone = score >= 85 ? "is-good" : score >= 70 ? "is-warning" : "is-danger";

  return (
    <article className={`eval-gauge ${tone}`}>
      <div className="eval-gauge-ring" style={{ "--score": `${score * 3.6}deg` } as CSSProperties}>
        <div><strong>{value == null ? "—" : `${score}%`}</strong><span>trung bình</span></div>
      </div>
      <div className="eval-gauge-copy"><h3>{label}</h3><p>{description}</p><span>Nguồn: Verifier Agent</span></div>
    </article>
  );
}

function ArtifactEmpty({ message, icon }: { message: string | null; icon: ReactNode }) {
  return (
    <div className="ops-empty-state eval-artifact-empty">
      {icon}
      <strong>Chưa có dữ liệu đánh giá</strong>
      <span>{message ?? "Báo cáo gần nhất chưa sẵn sàng."}</span>
    </div>
  );
}

function MetricRow({ name, passed, total, score, examples, deterministic = false }: {
  name: string;
  passed: number;
  total: number;
  score?: number;
  examples: string[];
  deterministic?: boolean;
}) {
  const rate = total > 0 ? passed / total : 0;
  return (
    <article className="eval-report-metric-row">
      <div className="eval-report-metric-head">
        <div><strong>{metricLabel(name)}</strong><span>{deterministic ? "Deterministic" : "LLM-as-judge"}</span></div>
        <div><strong>{passed}/{total}</strong><span>{score == null ? percent(rate) : `mean ${score.toFixed(2)}`}</span></div>
      </div>
      <div className="eval-report-progress" aria-label={`${metricLabel(name)}: ${percent(rate)} pass`}>
        <span style={{ width: `${Math.round(rate * 100)}%` }} />
      </div>
      {examples.length > 0 ? <p>{examples[0]}</p> : null}
    </article>
  );
}

export function EvalTab() {
  const [scores, setScores] = useState<EvalScores | null>(null);
  const [reports, setReports] = useState<EvalReports | null>(null);
  const [scoresFailed, setScoresFailed] = useState(false);
  const [reportsFailed, setReportsFailed] = useState(false);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<FailedQuestion | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    const [scoreResult, reportResult] = await Promise.allSettled([
      api.get<EvalScores>("/admin/eval/scores"),
      api.get<EvalReports>("/admin/eval/reports"),
    ]);

    if (scoreResult.status === "fulfilled") {
      setScores(scoreResult.value);
      setScoresFailed(false);
    } else {
      setScoresFailed(true);
    }
    if (reportResult.status === "fulfilled") {
      setReports(reportResult.value);
      setReportsFailed(false);
    } else {
      setReportsFailed(true);
    }
    setLoading(false);
  }, []);

  useEffect(() => { void load(); }, [load]);

  const failed = scores?.top_failed_questions ?? [];
  const deepArtifact = reports?.deepeval ?? null;
  const deepReport = deepArtifact?.report ?? null;
  const pipelineArtifact = reports?.evaluation ?? null;
  const pipelineReport = pipelineArtifact?.report ?? null;
  // The rule-based gates are the number to act on; a judge sharing a model with the answer
  // can score its own defects 1.00, so the blended rate is only a fallback for old reports.
  const deepGateRate = deepReport?.deterministic_pass_rate ?? deepReport?.pass_rate ?? null;
  const selfGraded = deepReport != null && !deepReport.independent_judge;
  const deepCasesNeedingAttention = Object.entries(deepReport?.per_case ?? {})
    .filter(([, stats]) => stats.pass_rate < 1 || stats.flaky)
    .sort((left, right) => left[1].pass_rate - right[1].pass_rate);
  const failureModes = Object.entries(pipelineReport?.failure_modes ?? {}).sort((a, b) => b[1] - a[1]);

  return (
    <div className="page admin-dashboard-page business-dashboard admin-workspace admin-eval-page">
      <AdminPageHeader
        eyebrow="AI quality assurance"
        title="Chất lượng trả lời"
        description="Theo dõi Evaluation trên lưu lượng thật, DeepEval trên golden cases và các quality gate xác định của pipeline."
        actions={<button className="business-refresh" type="button" disabled={loading} onClick={() => void load()}><RefreshIcon size={15} className={loading ? "is-spinning" : ""} /> Làm mới</button>}
      />

      {scoresFailed ? <div className="alert alert-danger">Không tải được Evaluation runtime từ backend.</div> : null}
      {reportsFailed ? <div className="alert alert-danger">Không tải được báo cáo DeepEval và Pipeline Evaluation.</div> : null}

      <div className="admin-metric-grid admin-workspace-metrics">
        <AdminMetricCard label="Bám sát nguồn" value={percent(scores?.faithfulness_avg ?? null)} hint="Live Evaluation" icon={<ShieldCheckIcon size={20} />} tone={scoreTone(scores?.faithfulness_avg ?? null)} tooltip="Điểm trung bình từ Verifier Agent trên các câu trả lời thực tế." />
        <AdminMetricCard label="Độ liên quan" value={percent(scores?.answer_relevancy_avg ?? null)} hint="Live Evaluation" icon={<ChartIcon size={20} />} tone={scoreTone(scores?.answer_relevancy_avg ?? null)} tooltip="Mức độ câu trả lời đáp ứng đúng trọng tâm câu hỏi." />
        <AdminMetricCard label="DeepEval quality gate" value={percent(deepGateRate)} hint={deepReport ? `${deepReport.passed}/${deepReport.runs} lượt đạt toàn bộ` : "Golden cases"} icon={<SparklesIcon size={20} />} tone={scoreTone(deepGateRate)} tooltip="Tỷ lệ vượt qua các gate xác định (Đủ thông tin bắt buộc, Không có nội dung cấm, Kỷ luật gợi ý căn). Đây là con số đáng tin cậy nhất vì không do LLM chấm." />
        <AdminMetricCard label="Pipeline pass rate" value={percent(pipelineReport?.pass_rate ?? null)} hint={pipelineReport ? `${pipelineReport.passed}/${pipelineReport.runs} trace đạt` : "Deterministic graders"} icon={<ActivityIcon size={20} />} tone={scoreTone(pipelineReport?.pass_rate ?? null)} tooltip="Tỷ lệ trace vượt qua các grader grounding, tool-call, retry và latency." />
      </div>

      <div className="admin-two-column eval-overview-grid">
        <section className="business-panel admin-ui-panel">
          <div className="business-panel-head"><div><h3>Live Evaluation</h3><p>Điểm Verifier trên các câu trả lời đã phục vụ người dùng.</p></div><span className="ops-caption-badge">Runtime</span></div>
          <div className="eval-gauge-grid">
            <QualityGauge label="Bám sát nguồn" value={scores?.faithfulness_avg ?? null} description="Đo mức độ các khẳng định được hỗ trợ bởi tài liệu truy xuất." />
            <QualityGauge label="Độ liên quan" value={scores?.answer_relevancy_avg ?? null} description="Đo mức độ câu trả lời tập trung đúng nhu cầu của người hỏi." />
          </div>
        </section>

        <section className="business-panel admin-ui-panel eval-priority-panel">
          <div className="business-panel-head"><div><h3>Ưu tiên cải thiện</h3><p>Các câu trả lời nhận feedback tiêu cực từ Sale.</p></div><span className={`admin-count-badge ${failed.length ? "is-danger" : ""}`}>{failed.length} câu</span></div>
          {loading && !scores ? <div className="admin-empty compact">Đang tải điểm đánh giá…</div> : failed.length === 0 ? (
            <div className="ops-empty-state compact"><CheckIcon size={24} /><strong>Chưa có câu hỏi thất bại</strong><span>Feedback tiêu cực mới sẽ xuất hiện tại đây.</span></div>
          ) : (
            <div className="eval-failed-list">
              {failed.map((item, index) => (
                <button type="button" key={item.message_id} className={selected?.message_id === item.message_id ? "is-active" : ""} onClick={() => setSelected(item)}>
                  <span>#{index + 1}</span><strong>{item.question}</strong><em>{item.feedback_count} báo cáo</em>
                </button>
              ))}
            </div>
          )}
        </section>
      </div>

      <section className="business-panel admin-ui-panel eval-report-panel">
        <div className="business-panel-head">
          <div><h3>DeepEval · Golden cases</h3><p>LLM-as-judge và quality gate xác định trên bộ câu hỏi chuẩn.</p></div>
          <span className={`eval-report-status ${deepReport?.complete ? "is-ready" : "is-warning"}`}>{deepReport ? (deepReport.complete ? "Hoàn tất" : "Chưa đủ cases") : "Chưa có report"}</span>
        </div>
        {!deepReport ? <ArtifactEmpty message={deepArtifact?.message ?? null} icon={<SparklesIcon size={25} />} /> : (
          <>
            <div className="eval-report-meta">
              <span><ClockIcon size={14} />{formatGeneratedAt(deepArtifact?.generated_at ?? null)}</span>
              <span>Answer: <strong>{deepReport.answer_model || "—"}</strong></span>
              <span>Judge: <strong>{deepReport.judge_model || "—"}</strong></span>
              <span>{deepReport.independent_judge ? "Judge độc lập" : "Judge cùng model"}</span>
            </div>
            {selfGraded ? (
              <div className="alert alert-warning">
                Judge dùng chung model với model sinh câu trả lời ({deepReport.answer_model || "—"}), nên các metric
                LLM-as-judge bên dưới đo mức độ tự nhất quán chứ không phải chất lượng — mô hình từng chấm 1.00 cho
                câu trả lời có lỗi đã xác nhận. Hãy căn cứ vào các gate xác định (Deterministic) và chạy lại với
                <code> --judge-model</code> khác để có ý kiến độc lập.
              </div>
            ) : null}
            <div className="eval-report-facts">
              <div><span>Golden cases</span><strong>{deepReport.cases}</strong></div>
              <div><span>Lượt chạy</span><strong>{deepReport.runs}</strong></div>
              <div><span>Gate xác định</span><strong className={scoreTone(deepGateRate) === "success" ? "is-success" : "is-danger"}>{percent(deepGateRate)}</strong></div>
              <div><span>LLM-judge {selfGraded ? "(tự chấm)" : ""}</span><strong>{percent(deepReport.judged_pass_rate ?? null)}</strong></div>
              <div><span>Không đạt</span><strong className={deepReport.failed ? "is-danger" : "is-success"}>{deepReport.failed}</strong></div>
            </div>
            <div className="eval-report-columns">
              <div>
                <h4>Metric DeepEval</h4>
                <div className="eval-report-metric-list">
                  {Object.entries(deepReport.metrics).map(([name, metric]) => <MetricRow key={name} name={name} passed={metric.passed} total={metric.total} score={metric.mean_score} examples={metric.examples} deterministic={deepReport.deterministic_metrics.includes(name)} />)}
                </div>
              </div>
              <div>
                <h4>Cases cần chú ý</h4>
                {deepCasesNeedingAttention.length === 0 ? <div className="ops-empty-state compact"><CheckIcon size={22} /><strong>Tất cả case đều đạt</strong></div> : (
                  <div className="eval-case-list">
                    {deepCasesNeedingAttention.map(([caseId, stats]) => <div key={caseId}><span>{stats.flaky ? "Flaky" : "Fail"}</span><strong>{caseId}</strong><em>{stats.passed}/{stats.attempts} đạt · {percent(stats.pass_rate)}</em></div>)}
                  </div>
                )}
              </div>
            </div>
          </>
        )}
      </section>

      <section className="business-panel admin-ui-panel eval-report-panel">
        <div className="business-panel-head">
          <div><h3>Pipeline Evaluation</h3><p>Grader xác định trên trace: grounding, retrieval, inventory, retry và latency.</p></div>
          <span className={`eval-report-status ${pipelineReport ? "is-ready" : ""}`}>{pipelineReport ? "Report sẵn sàng" : "Chưa có report"}</span>
        </div>
        {!pipelineReport ? <ArtifactEmpty message={pipelineArtifact?.message ?? null} icon={<ActivityIcon size={25} />} /> : (
          <>
            <div className="eval-report-meta"><span><ClockIcon size={14} />{formatGeneratedAt(pipelineArtifact?.generated_at ?? null)}</span><span>{pipelineArtifact?.source === "live_traces" ? "Tổng hợp từ trace hiện tại" : "Báo cáo offline"}</span><span>{pipelineReport.retries} trace có retry</span></div>
            <div className="eval-report-facts eval-report-facts--pipeline">
              <div><span>Trace đã chấm</span><strong>{pipelineReport.runs}</strong></div>
              <div><span>Pass rate</span><strong>{percent(pipelineReport.pass_rate)}</strong></div>
              <div><span>Latency p50</span><strong>{formatLatency(pipelineReport.latency_ms.p50)}</strong></div>
              <div><span>Latency p95</span><strong>{formatLatency(pipelineReport.latency_ms.p95)}</strong></div>
            </div>
            <div className="eval-report-columns">
              <div>
                <h4>Quality gates</h4>
                <div className="eval-report-metric-list">
                  {Object.entries(pipelineReport.graders).map(([name, grader]) => <MetricRow key={name} name={name} passed={grader.passed} total={grader.total} examples={grader.examples} deterministic />)}
                </div>
              </div>
              <div>
                <h4>Failure modes</h4>
                {failureModes.length === 0 ? <div className="ops-empty-state compact"><CheckIcon size={22} /><strong>Không có failure mode</strong></div> : (
                  <div className="eval-failure-mode-list">{failureModes.map(([name, count]) => <div key={name}><span>{name}</span><strong>{count}</strong></div>)}</div>
                )}
                <div className="eval-latency-max"><span>Latency cao nhất</span><strong>{formatLatency(pipelineReport.latency_ms.max)}</strong></div>
              </div>
            </div>
          </>
        )}
      </section>

      {selected ? (
        <aside className="business-detail-drawer eval-detail-drawer" aria-live="polite">
          <div><div><p>Chi tiết phản hồi</p><h3>Câu hỏi #{selected.message_id}</h3><span>Ưu tiên kiểm tra tài liệu và câu trả lời gốc.</span></div><button type="button" onClick={() => setSelected(null)} aria-label="Đóng chi tiết"><XIcon size={17} /></button></div>
          <blockquote>{selected.question}</blockquote>
          <dl><div><dt>Số lượt báo cáo</dt><dd>{selected.feedback_count}</dd></div><div><dt>Hướng xử lý</dt><dd>Kiểm tra nguồn / bổ sung tài liệu</dd></div></dl>
        </aside>
      ) : null}
    </div>
  );
}
