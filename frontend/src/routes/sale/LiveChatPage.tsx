import { useCallback, useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { createPortal } from "react-dom";
import { useNavigate, useParams } from "react-router-dom";
import { ApiError } from "../../api/client";
import { saleLiveApi } from "../../api/saleLive";
import type { CustomerConversationSummary, LeadDetail, MessageResponse } from "../../types";
import { AnswerImageStrip } from "./AnswerImageStrip";
import { LeadContextCard } from "./LeadContextCard";
import { LeadInsightPanel } from "./LeadInsightPanel";
import { AiHistoryModal } from "./AiHistoryModal";
import { PropertyListingCarousel } from "../PropertyListingCarousel";
import { parseServerDate } from "../../utils/datetime";
import { AuremontAvatar } from "../../components/AuremontAvatar";
import { useCursorTrail } from "../../hooks/useCursorTrail";
import { MessageContent } from "../../components/MessageContent";
import { CitationList } from "../../components/CitationList";
import {
  filterAuremontCommands,
  findAuremontCommand,
  isInternalCommandInput,
  type AuremontCommandDefinition,
} from "./auremontCommandRegistry";
import {
  AlertTriangleIcon,
  ArrowLeftIcon,
  ClipboardListIcon,
  ClockIcon,
  LoaderIcon,
  RefreshIcon,
  SendIcon,
  ShieldCheckIcon,
  SparklesIcon,
  UserIcon,
  UsersIcon,
  XIcon,
} from "../../components/Icons";

function formatTime(iso: string): string {
  const d = parseServerDate(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" });
}

const POLL_INTERVAL_MS = 4000;

function formatBudget(value: number | null): string | null {
  if (value === null) return null;
  return new Intl.NumberFormat("vi-VN", {
    style: "currency",
    currency: "VND",
    maximumFractionDigits: 0,
  }).format(value);
}

/** A Sale's view of a claimed live-handoff session: the human-era transcript, a derived
 * cross-channel handoff brief, and a "Gợi ý AI" co-pilot that drafts into the box without
 * ever sending anything automatically. The raw AI-only transcript remains isolated. */
export function LiveChatPage() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const navigate = useNavigate();
  const [messages, setMessages] = useState<MessageResponse[]>([]);
  const [lead, setLead] = useState<LeadDetail | null>(null);
  const [leadLoading, setLeadLoading] = useState(true);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [suggesting, setSuggesting] = useState(false);
  const [summary, setSummary] = useState<CustomerConversationSummary | null>(null);
  const [summaryOpen, setSummaryOpen] = useState(false);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [activeCommandIndex, setActiveCommandIndex] = useState(0);
  const [commandMenuDismissed, setCommandMenuDismissed] = useState(false);
  const [ending, setEnding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showAiHistory, setShowAiHistory] = useState(false);
  // Holds an AI draft that tripped the price/commitment detector and has not been
  // acknowledged yet. Replies here reach the customer directly, with none of the HITL card
  // the AI-consult flow puts in the way, so an AI-authored commitment gets the same
  // read-it-first obligation before it can be sent.
  const [unacknowledgedDraft, setUnacknowledgedDraft] = useState<string | null>(null);

  const scrollRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const { layerRef: particleLayerRef, handleMouseMove: handleChatMouseMove } = useCursorTrail();

  const reload = useCallback(() => {
    if (!sessionId) return;
    saleLiveApi
      .getMessages(Number(sessionId))
      .then(setMessages)
      .catch(() => {});
  }, [sessionId]);

  useEffect(() => {
    reload();
    const interval = setInterval(reload, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [reload]);

  // Re-fetched whenever the message count changes rather than on its own timer: a lead is
  // only ever re-scored after a customer message (see backend/routers/customer_chat.py), so
  // tying this to `messages.length` keeps the panel in sync exactly when it can change and
  // skips a poll on every tick where nothing new was said.
  useEffect(() => {
    if (!sessionId) return;
    setLeadLoading(true);
    saleLiveApi
      .getLead(Number(sessionId))
      .then(setLead)
      .catch(() => setLead(null))
      .finally(() => setLeadLoading(false));
  }, [sessionId, messages.length]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, loading]);

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [input]);

  // Still the untouched risky draft: the acknowledgement banner shows and sending is
  // blocked until the Sale either confirms it or edits it into their own words.
  const awaitingAck = unacknowledgedDraft !== null && input.trim() === unacknowledgedDraft;
  const selectedCommand = findAuremontCommand(input);
  const filteredCommands = filterAuremontCommands(input);
  const showCommandSuggestions =
    isInternalCommandInput(input) && !selectedCommand && !commandMenuDismissed;

  const chooseCommand = useCallback((command: AuremontCommandDefinition) => {
    setInput(command.trigger);
    setActiveCommandIndex(0);
    setCommandMenuDismissed(true);
    textareaRef.current?.focus();
  }, []);

  useEffect(() => {
    setActiveCommandIndex(0);
  }, [input]);

  const loadCustomerSummary = useCallback(async (forceRefresh: boolean) => {
    if (!sessionId || summaryLoading) return;
    setShowAiHistory(false);
    setSummaryOpen(true);
    if (!forceRefresh && summary) return;
    setSummaryLoading(true);
    setSummaryError(null);
    setError(null);
    try {
      let result: CustomerConversationSummary;
      if (forceRefresh) {
        result = await saleLiveApi.refreshCustomerSummary(Number(sessionId));
      } else {
        try {
          result = await saleLiveApi.getCustomerSummary(Number(sessionId));
        } catch (requestError) {
          if (!(requestError instanceof ApiError) || requestError.status !== 404) throw requestError;
          result = await saleLiveApi.refreshCustomerSummary(Number(sessionId));
        }
      }
      setSummary(result);
    } catch (requestError) {
      setSummaryError(
        requestError instanceof Error
          ? requestError.message
          : "Không cập nhật được tóm tắt khách hàng — bản cũ vẫn được giữ nguyên.",
      );
    } finally {
      setSummaryLoading(false);
    }
  }, [sessionId, summaryLoading, summary]);

  const summarizeCustomer = useCallback(() => loadCustomerSummary(false), [loadCustomerSummary]);
  const refreshCustomerSummary = useCallback(() => loadCustomerSummary(true), [loadCustomerSummary]);

  const sendReply = useCallback(async () => {
    if (!sessionId || !input.trim() || loading || awaitingAck) return;
    const content = input.trim();
    setInput("");
    const command = findAuremontCommand(content);
    if (command) {
      if (command.id === "customer-summary") await summarizeCustomer();
      return;
    }
    // Every leading @ is reserved for internal Sale controls. Unknown commands fail
    // locally instead of ever falling through to the customer-facing reply endpoint.
    if (isInternalCommandInput(content)) {
      setError("Không tìm thấy lệnh nội bộ này. Nội dung chưa được gửi cho khách hàng.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const reply = await saleLiveApi.reply(Number(sessionId), content);
      setMessages((prev) => [...prev, reply]);
      setUnacknowledgedDraft(null);
    } catch {
      setError("Không gửi được tin nhắn — vui lòng thử lại.");
    } finally {
      setLoading(false);
    }
  }, [sessionId, input, loading, awaitingAck, summarizeCustomer]);

  const suggest = useCallback(async () => {
    if (!sessionId || suggesting) return;
    setSuggesting(true);
    setError(null);
    try {
      const { draft, requires_hitl } = await saleLiveApi.suggest(Number(sessionId));
      if (draft) {
        setInput(draft);
        setUnacknowledgedDraft(requires_hitl ? draft : null);
      } else setError("AI chưa có đủ ngữ cảnh để gợi ý câu trả lời.");
    } catch {
      setError("Không lấy được gợi ý — vui lòng thử lại.");
    } finally {
      setSuggesting(false);
    }
  }, [sessionId, suggesting]);

  const endChat = useCallback(async () => {
    if (!sessionId || ending) return;
    if (!window.confirm("Kết thúc chat trực tiếp? Khách sẽ quay lại chat với Auremont AI.")) return;
    setEnding(true);
    setError(null);
    try {
      await saleLiveApi.end(Number(sessionId));
      navigate("/live-inbox");
    } catch {
      setError("Không kết thúc được phiên — vui lòng thử lại.");
    } finally {
      setEnding(false);
    }
  }, [sessionId, ending, navigate]);

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    sendReply();
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (showCommandSuggestions) {
      if (e.key === "Escape") {
        e.preventDefault();
        setCommandMenuDismissed(true);
        return;
      }
      if (e.key === "ArrowDown" && filteredCommands.length > 0) {
        e.preventDefault();
        setActiveCommandIndex((current) => (current + 1) % filteredCommands.length);
        return;
      }
      if (e.key === "ArrowUp" && filteredCommands.length > 0) {
        e.preventDefault();
        setActiveCommandIndex((current) => (current - 1 + filteredCommands.length) % filteredCommands.length);
        return;
      }
      if ((e.key === "Enter" && !e.shiftKey) || e.key === "Tab") {
        e.preventDefault();
        const command = filteredCommands[activeCommandIndex] ?? filteredCommands[0];
        if (command) chooseCommand(command);
        else setError("Không tìm thấy lệnh Auremont phù hợp.");
        return;
      }
    }
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendReply();
    }
  };

  const ready =
    Boolean(input.trim()) &&
    !loading &&
    !awaitingAck &&
    (!isInternalCommandInput(input) || Boolean(selectedCommand));

  // Previously hardcoded to "Chat trực tiếp với khách" — the lead lookup already carries
  // the customer's real name (or their label as a fallback), so the topbar can finally show
  // WHO the Sale is talking to instead of nothing at all.
  const topbarName = lead?.customer_name ?? lead?.customer_label ?? "Chat trực tiếp với khách";

  return (
    <div className={`live-chat-layout ${summaryOpen || showAiHistory ? "live-chat-layout--overlay-open" : ""}`}>
    <div className="chat-page chat-page--standalone" onMouseMove={handleChatMouseMove}>
      <div className="cursor-particle-layer" ref={particleLayerRef} aria-hidden="true" />
      <header className="chat-topbar">
        <div className="chat-topbar-info">
          <button className="btn btn-ghost btn-sm" type="button" onClick={() => navigate("/live-inbox")}>
            <ArrowLeftIcon size={14} />
          </button>
          <div className="chat-topbar-icon">
            <UsersIcon size={20} />
          </div>
          <div>
            <div className="chat-topbar-name">{topbarName}</div>
            <div className="chat-topbar-status">
              <span className="chat-status-dot" />
              Bạn đang chat trực tiếp — AI không tự trả lời trong phiên này
            </div>
          </div>
        </div>

        <div className="chat-topbar-actions">
          <button className="btn btn-outline" type="button" onClick={summarizeCustomer} disabled={summaryLoading}>
            {summaryLoading ? <LoaderIcon size={15} className="icon-spin" /> : <ClipboardListIcon size={15} />}
            Tóm tắt khách
          </button>
          <button
            className="btn btn-outline"
            type="button"
            onClick={() => {
              setSummaryOpen(false);
              setShowAiHistory(true);
            }}
          >
            <ClockIcon size={15} />
            Xem lại hội thoại AI
          </button>
          <button className="btn btn-outline" type="button" onClick={endChat} disabled={ending}>
            {ending ? <LoaderIcon size={15} className="icon-spin" /> : null}
            Kết thúc chat
          </button>
        </div>
      </header>

      {summaryOpen &&
        createPortal(
          <>
          <button
            type="button"
            className="customer-summary-scrim"
            aria-label="Đóng tóm tắt khách hàng"
            onClick={() => setSummaryOpen(false)}
          />
          <aside className="customer-summary-drawer" aria-label="Tóm tắt khách hàng">
            <div className="customer-summary-head">
              <div>
                <span className="customer-summary-eyebrow">Auremont AI · hồ sơ bàn giao</span>
                <h2>{summary?.customer_label ?? "Tóm tắt khách hàng"}</h2>
              </div>
              <button
                type="button"
                className="customer-summary-close"
                onClick={() => setSummaryOpen(false)}
                aria-label="Đóng"
              >
                <XIcon size={18} />
              </button>
            </div>

            {summaryError && summary && (
              <div className="customer-summary-error" role="alert">
                <AlertTriangleIcon size={16} />
                <span>{summaryError}</span>
              </div>
            )}

            {summaryLoading && !summary ? (
              <div className="customer-summary-loading">
                <LoaderIcon size={24} className="icon-spin" />
                <strong>Đang tổng hợp hội thoại…</strong>
                <span>AI chỉ đọc các tin nhắn mới kể từ lần tóm tắt gần nhất.</span>
              </div>
            ) : summary ? (
              <div className="customer-summary-body">
                <div className="customer-summary-meta">
                  <span>{summary.source_message_count} tin nhắn</span>
                  <span>
                    {summary.newly_processed_message_count > 0
                      ? `+${summary.newly_processed_message_count} mới`
                      : "Đã cập nhật"}
                  </span>
                  <span>{parseServerDate(summary.generated_at).toLocaleString("vi-VN")}</span>
                </div>

                <section className="customer-summary-hero">
                  <div className="customer-summary-signal-row">
                    {summary.metadata.urgency && (
                      <span className="customer-summary-signal">Mức độ: {summary.metadata.urgency}</span>
                    )}
                    {summary.metadata.sentiment && (
                      <span className="customer-summary-signal">{summary.metadata.sentiment}</span>
                    )}
                  </div>
                  <p>{summary.summary_text}</p>
                </section>

                <section className="customer-summary-section">
                  <h3>Nhu cầu hiện tại</h3>
                  <div className="customer-summary-facts">
                    {summary.metadata.needs.purchase_purpose && (
                      <div><span>Mục đích</span><strong>{summary.metadata.needs.purchase_purpose}</strong></div>
                    )}
                    {(summary.metadata.needs.budget_min !== null || summary.metadata.needs.budget_max !== null) && (
                      <div>
                        <span>Ngân sách</span>
                        <strong>
                          {formatBudget(summary.metadata.needs.budget_min) ?? "—"} – {formatBudget(summary.metadata.needs.budget_max) ?? "—"}
                        </strong>
                      </div>
                    )}
                    {(summary.metadata.needs.area_min_m2 !== null || summary.metadata.needs.area_max_m2 !== null) && (
                      <div>
                        <span>Diện tích</span>
                        <strong>{summary.metadata.needs.area_min_m2 ?? "—"}–{summary.metadata.needs.area_max_m2 ?? "—"} m²</strong>
                      </div>
                    )}
                    {summary.metadata.needs.purchase_timeline && (
                      <div><span>Thời điểm mua</span><strong>{summary.metadata.needs.purchase_timeline}</strong></div>
                    )}
                  </div>
                  {[
                    ...summary.metadata.needs.projects,
                    ...summary.metadata.needs.unit_types,
                    ...summary.metadata.needs.property_types,
                  ].length > 0 && (
                    <div className="customer-summary-tags">
                      {[
                        ...summary.metadata.needs.projects,
                        ...summary.metadata.needs.unit_types,
                        ...summary.metadata.needs.property_types,
                      ].map((item) => <span key={item}>{item}</span>)}
                    </div>
                  )}
                </section>

                {summary.metadata.considered_units.length > 0 && (
                  <section className="customer-summary-section">
                    <h3>Căn đã quan tâm</h3>
                    <div className="customer-summary-list">
                      {summary.metadata.considered_units.map((unit) => (
                        <div key={`${unit.project_id ?? "project"}-${unit.unit_code}`} className="customer-summary-unit">
                          <div><strong>{unit.unit_code}</strong><span>{unit.project_id ?? "Chưa rõ dự án"}</span></div>
                          {unit.customer_reaction && <p>{unit.customer_reaction}</p>}
                          <small><AlertTriangleIcon size={12} /> Cần kiểm tra lại tồn kho</small>
                        </div>
                      ))}
                    </div>
                  </section>
                )}

                {summary.metadata.pending_questions.length > 0 && (
                  <section className="customer-summary-section">
                    <h3>Chờ xử lý</h3>
                    <ul className="customer-summary-checklist">
                      {summary.metadata.pending_questions.map((item) => <li key={item}>{item}</li>)}
                    </ul>
                  </section>
                )}

                {summary.metadata.objections.length > 0 && (
                  <section className="customer-summary-section">
                    <h3>Băn khoăn của khách</h3>
                    <ul className="customer-summary-checklist customer-summary-checklist--warning">
                      {summary.metadata.objections.map((item) => <li key={item}>{item}</li>)}
                    </ul>
                  </section>
                )}

                {summary.metadata.commitments.length > 0 && (
                  <section className="customer-summary-section">
                    <h3>Cam kết của Sale</h3>
                    <ul className="customer-summary-checklist">
                      {summary.metadata.commitments.map((item) => <li key={item.content}>{item.content}</li>)}
                    </ul>
                  </section>
                )}

                {summary.metadata.next_best_actions.length > 0 && (
                  <section className="customer-summary-section customer-summary-section--actions">
                    <h3>Việc nên làm tiếp theo</h3>
                    <ol>
                      {summary.metadata.next_best_actions.map((item) => <li key={item}>{item}</li>)}
                    </ol>
                  </section>
                )}
              </div>
            ) : (
              <div className="customer-summary-loading">
                <AlertTriangleIcon size={24} />
                <strong>Chưa tạo được bản tóm tắt</strong>
                <span>{summaryError ?? "Bạn có thể thử làm mới mà không làm mất dữ liệu cũ."}</span>
              </div>
            )}

            <div className="customer-summary-footer">
              <span className="customer-summary-private">
                <ShieldCheckIcon size={14} />
                Chỉ Sale nhìn thấy · khách hàng không nhận được lệnh hoặc bản tóm tắt này.
              </span>
              <button
                type="button"
                className="btn btn-sm btn-primary"
                onClick={refreshCustomerSummary}
                disabled={summaryLoading}
              >
                {summaryLoading ? <LoaderIcon size={13} className="icon-spin" /> : <RefreshIcon size={13} />}
                Làm mới
              </button>
            </div>
          </aside>
          </>,
          document.body,
        )}

      {sessionId && (
        <AiHistoryModal sessionId={Number(sessionId)} open={showAiHistory} onClose={() => setShowAiHistory(false)} />
      )}

      <div className="chat-messages" ref={scrollRef}>
        <div className="chat-messages-inner">
          <LeadContextCard lead={lead} />
          {messages.map((m) => {
            const isCustomer = m.sender === "customer";
            const isSaleMessage = m.sender === "sale";
            return (
              <div key={m.id} className={`chat-message ${isCustomer ? "chat-message--bot" : "chat-message--user"}`}>
                <div className={`chat-avatar ${isCustomer ? "chat-avatar--bot" : "chat-avatar--user"}`}>
                  {isCustomer ? (
                    <UserIcon size={16} />
                  ) : isSaleMessage ? (
                    <UsersIcon size={16} />
                  ) : (
                    <AuremontAvatar size={20} emotion={m.emotion ?? "idle"} variant="face" />
                  )}
                </div>

                <div className="chat-bubble-wrap">
                  {!isCustomer && (
                    <span className="chat-sale-label">{isSaleMessage ? "Bạn" : "Auremont AI (trước khi chuyển giao)"}</span>
                  )}
                  <div className={`chat-bubble ${isCustomer ? "chat-bubble--bot" : "chat-bubble--user"}`}>
                    <MessageContent content={m.content} className="chat-bubble-text" />

                    {!isCustomer && m.citations && m.citations.length > 0 && (
                      <CitationList citations={m.citations} className="chat-citations" label="Nguồn" />
                    )}

                    {!isCustomer && m.images && m.images.length > 0 && <AnswerImageStrip images={m.images} />}

                    {!isCustomer && m.listings && m.listings.length > 0 && (
                      <PropertyListingCarousel listings={m.listings} />
                    )}
                  </div>
                  <span className="chat-timestamp">{formatTime(m.created_at)}</span>
                </div>
              </div>
            );
          })}

          {error && <div className="alert alert-danger">{error}</div>}
        </div>
      </div>

      <div className="chat-input-wrapper">
        {awaitingAck && (
          <div className="live-hitl-ack">
            <AlertTriangleIcon size={16} />
            <p>
              Gợi ý này có thông tin giá/cam kết và sẽ gửi thẳng cho khách. Hãy đọc kỹ trước khi gửi.
            </p>
            <button type="button" className="btn btn-sm btn-primary" onClick={() => setUnacknowledgedDraft(null)}>
              Tôi đã đọc, cho phép gửi
            </button>
          </div>
        )}
        <form className="chat-input-area" onSubmit={handleSubmit}>
          {showCommandSuggestions && (
            <div className="chat-command-menu" id="auremont-command-menu" role="listbox" aria-label="Lệnh Auremont">
              <div className="chat-command-menu-head">
                <div>
                  <span className="chat-command-menu-kicker">Auremont AI</span>
                  <strong>Gợi ý lệnh nội bộ</strong>
                </div>
                <span className="chat-command-prefix" aria-label="Tiền tố lệnh">@</span>
              </div>
              <div className="chat-command-menu-label">
                {filteredCommands.length > 0 ? `Thường dùng · ${filteredCommands.length} lệnh` : "Không có kết quả"}
              </div>
              <div className="chat-command-results">
                {filteredCommands.length > 0 ? (
                  filteredCommands.map((command, index) => (
                    <button
                      type="button"
                      id={`auremont-command-${command.id}`}
                      className={`chat-command-item ${index === activeCommandIndex ? "chat-command-item--active" : ""}`}
                      role="option"
                      aria-selected={index === activeCommandIndex}
                      key={command.id}
                      onMouseEnter={() => setActiveCommandIndex(index)}
                      onClick={() => chooseCommand(command)}
                    >
                      <span className="chat-command-icon"><ClipboardListIcon size={18} /></span>
                      <span className="chat-command-copy">
                        <strong>{command.trigger}</strong>
                        <small>{command.description}</small>
                      </span>
                      <span className="chat-command-privacy">
                        <ShieldCheckIcon size={12} /> Chỉ Sale
                      </span>
                    </button>
                  ))
                ) : (
                  <div className="chat-command-empty">
                    <strong>Không tìm thấy lệnh phù hợp</strong>
                    <span>Thử gõ “@”, “@Auremont” hoặc một từ khóa khác.</span>
                  </div>
                )}
              </div>
              <div className="chat-command-menu-footer" aria-hidden="true">
                <span><kbd>↑</kbd><kbd>↓</kbd> di chuyển</span>
                <span><kbd>Enter</kbd> chọn</span>
                <span><kbd>Esc</kbd> đóng</span>
              </div>
            </div>
          )}
          <div className={`chat-input-box ${input.trim() ? "chat-input-box--active" : ""}`}>
            <textarea
              ref={textareaRef}
              className="chat-input"
              placeholder="Nhập tin gửi khách hoặc gõ @ để mở lệnh Auremont…"
              value={input}
              onChange={(e) => {
                setInput(e.target.value);
                setCommandMenuDismissed(false);
              }}
              onKeyDown={handleKeyDown}
              disabled={loading}
              rows={1}
              aria-autocomplete="list"
              aria-expanded={showCommandSuggestions}
              aria-controls={showCommandSuggestions ? "auremont-command-menu" : undefined}
              aria-activedescendant={
                showCommandSuggestions && filteredCommands[activeCommandIndex]
                  ? `auremont-command-${filteredCommands[activeCommandIndex].id}`
                  : undefined
              }
            />
            <button type="submit" className={`chat-send-btn ${ready ? "chat-send-btn--ready" : ""}`} disabled={!ready} aria-label="Gửi">
              {loading ? <LoaderIcon size={18} className="icon-spin" /> : <SendIcon size={18} />}
            </button>
          </div>
          <div className="chat-input-hint" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span>Enter để gửi · Shift + Enter để xuống dòng</span>
            <button type="button" className="btn btn-sm btn-outline" onClick={suggest} disabled={suggesting}>
              {suggesting ? <LoaderIcon size={13} className="icon-spin" /> : <SparklesIcon size={13} />}
              Gợi ý AI
            </button>
          </div>
        </form>
      </div>
    </div>

      <LeadInsightPanel lead={lead} loading={leadLoading} />
    </div>
  );
}
