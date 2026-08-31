export type SalePresence = "online" | "offline" | "busy";

export interface SaleAccountCreate {
  username: string;
  email: string;
  password: string;
  is_active: boolean;
}

export interface SaleStatus {
  id: number;
  username: string;
  email: string;
  is_active: boolean;
  presence: SalePresence;
  active_chat_sessions: number;
  handled_sessions: number;
  interaction_rate: number | null;
  conversion_rate: number | null;
  last_activity_at: string | null;
}

export interface ManagedLiveSession {
  session_id: number;
  customer_label: string;
  current_sale_id: number | null;
  current_sale_name: string | null;
  status: "waiting_sale" | "sale_handling" | "bot_handling";
  waiting_since: string | null;
  project_id: string | null;
  last_message_preview: string;
}

export interface SalesBoard {
  generated_at: string;
  presence_window_minutes: number;
  summary: {
    total_sales: number;
    active_accounts: number;
    online_sales: number;
    busy_sales: number;
    waiting_customers: number;
    live_customers: number;
  };
  sales: SaleStatus[];
  live_sessions: ManagedLiveSession[];
}

export interface ToolReliabilityMetric {
  key: string;
  name: string;
  calls: number;
  errors: number;
  success_rate: number | null;
  average_latency_ms: number | null;
}

export interface TraceStep {
  name: string;
  at_ms: number;
  duration_ms: number | null;
  status: "success" | "error" | "skipped";
  detail: string | null;
}

export interface TraceSummary {
  run_id: string;
  started_at: string;
  duration_ms: number;
  project_id: string | null;
  clearance: string;
  outcome: string;
  verifier_score: number | null;
  steps: TraceStep[];
}

export interface AuditLogEntry {
  id: number;
  timestamp: string;
  severity: "INFO" | "WARN" | "ERROR";
  module: string;
  event: string;
  username: string | null;
  request_id: string | null;
}

export interface ObservabilityOverview {
  generated_at: string;
  period_days: number;
  tracing_enabled: boolean;
  tool_reliability: ToolReliabilityMetric[];
  users: { dau: number; mau: number; active_sessions: number; waiting_sessions: number };
  tokens: {
    input_tokens: number;
    output_tokens: number;
    estimated_cost_usd: number;
    projected_monthly_cost_usd: number;
    cost_configured: boolean;
    daily: { date: string; input_tokens: number; output_tokens: number; estimated_cost_usd: number }[];
  };
  most_used_modules: { module: string; calls: number }[];
  logs: AuditLogEntry[];
  traces: TraceSummary[];
  budget_intents: { label: string; count: number }[];
  popular_projects: { project_id: string; project_name: string; count: number }[];
  fallback_alerts: {
    message_id: number;
    session_id: number | null;
    severity: "warning" | "critical";
    verifier_score: number;
    failure_mode: string | null;
    customer_question: string | null;
    created_at: string;
  }[];
}

export interface ConflictDocumentSummary {
  id: number;
  title: string;
  project_id: string | null;
  version_label: string | null;
  issued_date: string | null;
  effective_date: string | null;
  uploaded_at: string | null;
  category: string;
  visibility: string;
  summary: string | null;
  classification_reason: string | null;
}

export interface ConflictSemanticEvidenceItem {
  quote_a: string;
  quote_b: string;
  fact_key: string;
  same_business_fact: boolean;
  same_scope_and_conditions: boolean;
  effective_periods_overlap: boolean;
  claims_mutually_exclusive: boolean;
  explanation: string;
}

export interface ConflictEvidence {
  schema_version?: number;
  semantic?: {
    decision: "conflict" | "compatible" | "uncertain";
    confidence: number;
    conflict_type: string | null;
    summary: string;
    evidence: ConflictSemanticEvidenceItem[];
  };
  rule?: {
    price_differences?: Array<{ fact_key: string; document_a: number[]; document_b: number[] }>;
    fact_differences?: Array<{ fact_key: string; document_a: string[]; document_b: string[] }>;
  };
}

export interface ConflictDetail {
  id: number;
  document_id_a: number;
  document_id_b: number;
  description: string | null;
  detection_method: "rule" | "llm" | "hybrid";
  confidence: number | null;
  conflict_type: string | null;
  severity: "low" | "medium" | "high";
  evidence: ConflictEvidence | null;
  analysis_version: string | null;
  status: "open" | "resolved";
  created_at: string;
  resolved_at: string | null;
  similarity_score: number | null;
  project_id: string | null;
  project_name: string | null;
  document_a: ConflictDocumentSummary;
  document_b: ConflictDocumentSummary;
}

export interface BusinessSummaryBase {
  sessions: number;
  customers: number;
  questions: number;
  active_sales: number;
  helpful_rate: number | null;
  verifier_avg: number | null;
  hitl_required: number;
  hitl_confirmed: number;
}

export interface BusinessSummary extends BusinessSummaryBase {
  ready_documents: number;
}

export interface BusinessDashboard {
  period_days: number;
  period: {
    current_start: string;
    current_end: string;
    previous_start: string;
    previous_end: string;
    timezone: string;
  };
  applied_filters: { project_id: string | null; sale_id: number | null };
  filter_options: {
    projects: { id: string; name: string }[];
    sales: { id: number; username: string }[];
  };
  verifier_threshold: number;
  summary: BusinessSummary;
  previous_summary: BusinessSummaryBase;
  activity: { date: string; sessions: number; questions: number }[];
  top_projects: { project_id: string | null; name: string; sessions: number }[];
  top_sales: { sale_id: number; username: string; sessions: number; customers: number; questions: number }[];
  feedback_distribution: { helpful: number; wrong: number; incomplete: number; unrated: number };
  quality_trend: { date: string; faithfulness: number | null; relevancy: number | null }[];
  hitl_funnel: { answers: number; required: number; confirmed: number };
  document_coverage: {
    project_id: string;
    name: string;
    ready_count: number;
    categories: Record<string, "ready" | "pending_review" | "unavailable" | "missing">;
  }[];
}

export interface LegacyReclassificationCandidate {
  document_id: number;
  title: string;
  status: string;
  category: string;
  project_id: string | null;
  classification_version: string | null;
  classification_confidence: number | null;
}

export interface ReclassificationMetadataChange {
  stored: unknown;
  suggested: unknown;
}

export interface ReclassificationProjectCandidate {
  project_id: string;
  project_name: string;
  confidence: number;
  reason: string;
}

export interface ReclassificationProjectResolution {
  stored_project_id: string | null;
  llm_project_id: string | null;
  recommended_project_id: string | null;
  candidates: ReclassificationProjectCandidate[];
  requires_confirmation: boolean;
  warning: string | null;
}

export interface ReclassificationPreviewItem {
  document_id: number;
  title: string;
  status: string;
  source_sha256: string | null;
  suggestion: Record<string, unknown> | null;
  changes: Record<string, ReclassificationMetadataChange>;
  project_resolution: ReclassificationProjectResolution | null;
  confirmation_token: string | null;
  error: string | null;
}

export interface ReclassificationPreviewResponse {
  items: ReclassificationPreviewItem[];
  previewed: number;
  failed: number;
}

export type ReclassificationProjectAction = "keep" | "assign" | "clear";

export interface ReclassificationApplyItem {
  confirmation_token: string;
  project_action: ReclassificationProjectAction;
  project_id?: string;
}

export interface ReclassificationApplyResult {
  document_id: number | null;
  title: string | null;
  status: string;
  category: string | null;
  project_id: string | null;
  is_current: boolean | null;
  reindexed: boolean;
  conflict_ids: number[];
  duplicate_document_ids: number[];
  error: string | null;
}

export interface ReclassificationApplyResponse {
  items: ReclassificationApplyResult[];
  applied: number;
  failed: number;
}


// ── Lead capture & scoring — mirrors backend/schemas/admin_dashboard.py::LeadStatsResponse ──

export interface LeadTierCounts {
  hot: number;
  warm: number;
  cold: number;
  total: number;
}

export interface LeadTrendPoint {
  date: string;
  hot: number;
  warm: number;
  cold: number;
}

export interface LeadEnrichmentStats {
  scored: number;
  llm_calls: number;
  call_rate: number;
}

export interface LeadStats {
  period_days: number;
  totals: LeadTierCounts;
  trend: LeadTrendPoint[];
  registered: number;
  anonymous: number;
  /** Leads whose account carries a phone number — the lead-capture KPI. */
  contactable: number;
  contact_rate: number;
  avg_score: number;
  llm_enrichment: LeadEnrichmentStats;
}
