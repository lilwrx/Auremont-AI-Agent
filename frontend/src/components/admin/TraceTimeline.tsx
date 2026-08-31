import type { TraceSummary } from "../../types/admin";

const STEP_LABELS: Record<string, string> = {
  cache_check: "Kiểm tra cache",
  intent: "Nhận diện ý định",
  retrieve: "RAG retrieval",
  "tool.inventory": "Inventory tool",
  "tool.images": "Image resolver",
  "llm.usage": "LLM token usage",
  generate: "Sinh câu trả lời",
  verify: "Verifier",
  risk_check: "Kiểm tra rủi ro",
};

export function TraceTimeline({ trace }: { trace: TraceSummary | null }) {
  if (!trace) {
    return <div className="admin-empty compact">Chưa có trace trong khoảng thời gian này.</div>;
  }

  return (
    <div className="trace-detail">
      <div className="trace-summary-line">
        <code>{trace.run_id}</code>
        <span>{Math.round(trace.duration_ms)} ms</span>
        <span>{trace.project_id ?? "Không giới hạn dự án"}</span>
        <span className={`status-chip status-chip--${trace.outcome === "crash" ? "error" : "success"}`}>{trace.outcome}</span>
      </div>
      <ol className="trace-timeline">
        {trace.steps.map((step, index) => (
          <li key={`${step.name}-${index}`} className={`trace-step trace-step--${step.status}`}>
            <span className="trace-step-dot" />
            <div className="trace-step-body">
              <div>
                <strong>{STEP_LABELS[step.name] ?? step.name}</strong>
                <span>+{Math.round(step.at_ms)} ms</span>
              </div>
              <p>{step.detail ?? (step.duration_ms != null ? `${Math.round(step.duration_ms)} ms` : "Hoàn tất")}</p>
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}
