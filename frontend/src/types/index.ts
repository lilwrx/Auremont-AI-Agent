// Mirrors backend/schemas/*.py — keep field names in sync with the Pydantic response models.

export type UserRole = "sale" | "admin" | "customer";
export type DocumentVisibility = "internal" | "public";
export type MessageSender = "sale" | "agent" | "customer";
/** Drives AuremontAvatar.tsx — mirrors backend/core/enums.py::MessageEmotion. `null` on a
 * Sale/Customer's own message, or an older AGENT message from before this field existed. */
export type MessageEmotion = "happy" | "regretful" | "respectful";
export type DocumentReviewStatus = "pending" | "approved" | "rejected";
export type LegalStatus =
  | "unknown"
  | "not_yet_effective"
  | "effective"
  | "expired"
  | "repealed"
  | "replaced";
export type DocumentCategory =
  | "sales_policy"
  | "price_list"
  | "inventory_snapshot"
  | "subdivision_info"
  | "building_info"
  | "floor_plan"
  | "payment_schedule"
  | "promotion"
  | "legal_document"
  | "contract_template"
  | "internal_guide"
  | "other";

export interface UserResponse {
  id: number;
  username: string;
  email: string;
  role: UserRole;
  is_active: boolean;
  created_at: string;
}

export interface Citation {
  document_id: number;
  title: string;
  /**
   * Tells two same-named sources apart ("tr.5", "#37"); null when the title is already
   * unique. Deliberately separate from `title`, which must keep its ".pdf" ending for
   * withPageAnchor and the inline preview. Absent on messages stored before this existed.
   */
  qualifier?: string | null;
  page: number | null;
  /** PDF points from the page's top — see CitationList.tsx's withPageAnchor. */
  y_position: number | null;
}

export interface AnswerImage {
  url: string;
  project_id: string;
  project_name: string;
}

/** One recommended unit, rendered as its own card (with paging arrows between cards)
 * instead of as a bullet line in `content` — see backend/ai/prompts.py::PropertyListing.
 * `image_urls`/`amenities`/`project_id` are resolved server-side, never supplied by the
 * model, and default empty when the project/gallery could not be resolved (the card still
 * renders, with a placeholder instead of photos).
 * `unit_code`/`status` are non-empty only when this card was built from one confirmed
 * TỒN KHO REAL-TIME record — a catalogue-only project/subdivision summary card leaves
 * both "". */
export interface PropertyListing {
  project_name: string;
  unit_type: string;
  area_range: string;
  price_range: string;
  image_urls: string[];
  amenities: string[];
  project_id: string | null;
  unit_code: string;
  status: string;
}

export interface MessageResponse {
  id: number;
  session_id: number | null;
  sender: MessageSender;
  content: string;
  citations: Citation[] | null;
  images: AnswerImage[] | null;
  verifier_score: number | null;
  requires_hitl: boolean;
  /** Derived server-side from the audit trail; never sent by this client. */
  hitl_confirmed: boolean;
  emotion: MessageEmotion | null;
  /** Short reply options to tap instead of typing — only ever set on a customer-facing
   * AGENT message asking a discovery question with a natural short list of answers. */
  quick_replies: string[] | null;
  /** Recommended units rendered as their own cards — see PropertyListing above. */
  listings: PropertyListing[] | null;
  /** Follow-up questions the asker may want next, offered on both the Sale and customer
   * surfaces. Distinct from `quick_replies`: those answer a question the assistant just
   * asked, these start the asker's next one. */
  suggested_questions: string[] | null;
  created_at: string;
}

export interface ProjectResponse {
  id: string;
  name: string;
  location: string | null;
  description: string | null;
  created_at: string;
}

export interface ChatSessionResponse {
  id: number;
  sale_id: number;
  title: string | null;
  customer_name: string | null;
  // The project this session is about. The agent needs it to query real-time
  // inventory, so a session without one cannot answer stock questions.
  project_id: string | null;
  created_at: string;
}

// ── Customer chat (public/anonymous flow) — mirrors backend/schemas/customer.py ──

export interface AnonymousSessionResponse {
  session_id: number;
  visitor_token: string;
}

/** Who is currently answering a customer-chat session — see backend/core/enums.py::SessionStatus. */
export type SessionStatus = "bot_handling" | "waiting_sale" | "sale_handling";

export interface CustomerChatSessionResponse {
  id: number;
  customer_id: number | null;
  title: string | null;
  project_id: string | null;
  status: SessionStatus;
  created_at: string;
}

export interface CustomerRegisterRequest {
  email: string;
  password: string;
  full_name?: string | null;
  session_id?: number | null;
  visitor_token?: string | null;
}

/** Which soft-paywall trigger intercepted this turn — null on a normally-answered turn.
 * "human_request" is an anonymous visitor asking for a live Sale — routed into the same
 * register/login gate as every other lead-qualification trigger, not a direct handoff. */
export type CustomerGate = "turn_limit" | "daily_limit" | "closing_intent" | "human_request";

export interface CustomerAskResponse extends MessageResponse {
  gate: CustomerGate | null;
  status: SessionStatus;
}

// ── Sale live inbox (AI -> Sale handoff) — mirrors backend/schemas/sale_live.py ──

export type LeadTier = "hot" | "warm" | "cold";

export interface LiveInboxEntry {
  session_id: number;
  customer_label: string;
  last_message_preview: string;
  // When this session entered the waiting queue — not when the session itself was created.
  waiting_since: string | null;
  // Never null: a lead with no buying signal yet genuinely IS cold, so the badge always
  // renders. See backend/core/enums.py::LeadTier.
  lead_tier: LeadTier;
  lead_score: number;
  // The signals behind the tier, so a Sale can see why before they click.
  lead_reason: string | null;
  customer_name: string | null;
  customer_phone: string | null;
}

export type LeadUrgency = "immediate" | "near_term" | "exploring";
export type LeadPurpose = "living" | "investment" | "business" | "unknown";

export interface LeadSignalDetail {
  label: string;
  points: number;
}

/** Full breakdown behind one lead's tier — GET /sale/live-inbox/{id}/lead.
 * `null` when nobody has scored this session yet. */
export interface LeadDetail {
  customer_label: string;
  customer_name: string | null;
  customer_phone: string | null;
  lead_tier: LeadTier;
  lead_score: number;
  rule_score: number;
  // None means the LLM pass never ran — different from having run and found nothing.
  soft_score: number | null;
  urgency: LeadUrgency | null;
  purpose: LeadPurpose | null;
  confidence: number | null;
  detection_method: string;
  turn_count: number;
  scored_at: string | null;
  signals: LeadSignalDetail[];
  llm_reason: string | null;
  // One concrete thing to do next, decided server-side from the tier plus what is already
  // known — see lead_scoring_service.suggest_next_action.
  next_action: string;
  // What the customer told the AI they want, from the same Redis profile the answer
  // pipeline reads. Lets the Sale open with context instead of re-asking.
  budgets: string[];
  unit_types: string[];
  projects: string[];
}

export interface CustomerSummaryNeeds {
  purchase_purpose: string | null;
  projects: string[];
  property_types: string[];
  unit_types: string[];
  budget_min: number | null;
  budget_max: number | null;
  area_min_m2: number | null;
  area_max_m2: number | null;
  preferred_floor: string | null;
  preferred_view: string | null;
  purchase_timeline: string | null;
}

export interface CustomerSummaryConsideredUnit {
  unit_code: string;
  project_id: string | null;
  customer_reaction: string | null;
  last_mentioned_at: string | null;
  inventory_recheck_required: boolean;
  evidence_message_ids: number[];
}

export interface CustomerSummaryCommitment {
  content: string;
  status: string;
  evidence_message_ids: number[];
}

export interface CustomerSummaryMetadata {
  needs: CustomerSummaryNeeds;
  considered_units: CustomerSummaryConsideredUnit[];
  objections: string[];
  pending_questions: string[];
  commitments: CustomerSummaryCommitment[];
  sentiment: string | null;
  urgency: string | null;
  next_best_actions: string[];
  evidence: Array<{ field: string; message_ids: number[]; source_role: string }>;
}

export interface CustomerConversationSummary {
  customer_id: number;
  customer_label: string;
  summary_text: string;
  metadata: CustomerSummaryMetadata;
  last_processed_message_id: number;
  source_message_count: number;
  newly_processed_message_count: number;
  generated_at: string;
  schema_version: string;
  model_name: string;
  from_cache: boolean;
  is_stale: boolean;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  user: UserResponse;
}

export type DocumentBlockReason =
  | "prompt_injection"
  | "duplicate_content"
  | "legacy_unknown";

export interface DocumentSecurityFinding {
  rule_id: string;
  severity: "warning" | "high_risk";
  description: string;
  page: number | null;
  excerpt: string;
}

export interface DocumentSectionClassification {
  section_index: number;
  category: DocumentCategory;
  page: number | null;
  content_type: string;
  confidence: number;
  reason: string;
  excerpt: string;
}

export interface DocumentResponse {
  id: number;
  title: string;
  file_path: string | null;
  project_id: string | null;
  status: string;
  visibility: DocumentVisibility;
  category: DocumentCategory;
  categories: DocumentCategory[];
  section_classifications: DocumentSectionClassification[];
  subcategory: string | null;
  subdivision_names: string[] | null;
  building_codes: string[] | null;
  unit_types: string[] | null;
  applicable_area: string | null;
  document_summary: string | null;
  version_label: string | null;
  issued_date: string | null;
  effective_date: string | null;
  expiry_date: string | null;
  applicable_period: string | null;
  legal_document_type: string | null;
  legal_document_number: string | null;
  legal_issuer: string | null;
  legal_domain: string | null;
  legal_status: LegalStatus;
  is_current: boolean;
  review_status: DocumentReviewStatus;
  classification_confidence: number | null;
  classification_reason: string | null;
  block_reason: DocumentBlockReason | null;
  security_findings: DocumentSecurityFinding[];
  classification_requires_admin_review: boolean | null;
  classification_version: string | null;
  classified_at: string | null;
  reviewed_by: number | null;
  reviewed_at: string | null;
  uploaded_by: number | null;
  uploaded_at: string | null;
  created_at: string;
}

export interface DocumentClassificationUpdate {
  category: DocumentCategory;
  categories: DocumentCategory[];
  section_classifications: DocumentSectionClassification[];
  subcategory: string | null;
  subdivision_names: string[] | null;
  building_codes: string[] | null;
  unit_types: string[] | null;
  applicable_area: string | null;
  document_summary: string | null;
  version_label: string | null;
  issued_date: string | null;
  effective_date: string | null;
  expiry_date: string | null;
  applicable_period: string | null;
  legal_document_type: string | null;
  legal_document_number: string | null;
  legal_issuer: string | null;
  legal_domain: string | null;
  legal_status: LegalStatus;
}

/**
 * Payload for the controlled reclassification flow. Changing the project or
 * conflict scope can affect retrieval/conflict membership, so these fields are
 * intentionally only sent to POST /documents/{id}/reclassify.
 */
export interface DocumentReclassificationUpdate extends DocumentClassificationUpdate {
  project_id: string | null;
}

export type DocumentRelationType = "replaces" | "amends" | "repeals" | "updates" | "supersedes" | "guides" | "related_to";

export interface DocumentRelationResponse {
  id: number;
  source_document_id: number;
  target_document_id: number;
  relation_type: DocumentRelationType;
  scope_note: string | null;
  evidence: string | null;
  confidence: number | null;
  review_status: DocumentReviewStatus;
  reviewed_by: number | null;
  reviewed_at: string | null;
  created_at: string;
}
